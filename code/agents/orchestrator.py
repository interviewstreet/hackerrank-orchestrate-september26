"""The agent loop: the model routes, the tools compute, the validator decides.

The model is never asked to do arithmetic. It chooses which evidence to gather
for this particular request, judges what that evidence means, picks among the
plans the tools verified, and writes the explanation. Every number in the output
comes from a deterministic tool, and the answer is re-simulated independently
before it is accepted -- so a reasoning slip cannot produce an unsafe plan.

If the loop cannot finish (budget exhausted, the model unavailable, iterations
spent), the deterministic engine's own answer is used. Never no answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Callable

from agents.prompts import ORCHESTRATOR_SYSTEM, tools_for
from config import Settings
from tools.balance_forecaster import ForecastConfig, ForecastModel, build_forecast_model
from tools.decision_engine import decide
from tools.evidence_cache import EvidenceCache
from tools.exchange_converter import ExchangeConverter
from tools.image_extractor import ImageExtractor
from tools.message_resolver import MessageResolver, apply_modifications
from tools.plan_generator import PlanGenerator
from tools.retriever import SampleRetriever
from tools.safety_gate import SafetyGate
from tools.spending_optimizer import suggest_spending_changes
from utils.llm_client import LLMClient
from utils.token_tracker import BudgetExhausted, TokenTracker
from validators.output_validator import validate_output
from validators.schemas import (
    AffordabilityStatus,
    AgentOutput,
    CandidatePlan,
    FinancialEvent,
    FinancialProfile,
    ImageRef,
    Message,
    PaymentMethod,
    PaymentOption,
    RequestRow,
    SpendingChange,
)

MAX_TOOL_RESULT_CHARS = 1800
# Tool results are resent on every subsequent turn, so an un-compacted
# conversation costs far more than the calls themselves. Keep the most recent
# results in full and stub out the ones already acted on.
KEEP_TOOL_RESULTS_IN_FULL = 3


@dataclass
class RequestBundle:
    """Everything the agent may look at for one request."""

    request: RequestRow
    profile: FinancialProfile
    events: list[FinancialEvent]
    messages: list[Message]
    images: list[ImageRef]
    options: list[PaymentOption]


@dataclass
class AgentState:
    """Working memory that accumulates across tool calls."""

    model: ForecastModel
    resolved_amounts: dict[str, float] = field(default_factory=dict)
    spending_changes: list[SpendingChange] = field(default_factory=list)
    plans: list[CandidatePlan] = field(default_factory=list)
    # Tracked explicitly rather than inferred from `plans`: when no plan is safe
    # that list is legitimately empty, and inferring from it would keep offering
    # load_context after it had already run.
    context_loaded: bool = False
    spending_searched: bool = False


class OrchestratorAgent:
    """Runs one request through the tool-calling loop."""

    def __init__(
        self,
        settings: Settings,
        client: LLMClient,
        tracker: TokenTracker,
        converter: ExchangeConverter,
        extractor: ImageExtractor,
        resolver: MessageResolver,
        gate: SafetyGate,
        retriever: SampleRetriever | None = None,
        forecast_config: ForecastConfig | None = None,
        evidence: EvidenceCache | None = None,
        logger: Any = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.tracker = tracker
        self.converter = converter
        self.extractor = extractor
        self.resolver = resolver
        self.gate = gate
        self.retriever = retriever
        self.forecast_config = forecast_config or ForecastConfig()
        self.evidence = evidence
        self.log = logger

    # ---- entry point -------------------------------------------------------

    def run(self, bundle: RequestBundle) -> AgentOutput:
        """Produce one validated output row for `bundle`."""
        baseline = self._deterministic(bundle)
        try:
            agent_output = self._loop(bundle, baseline)
        except BudgetExhausted:
            self._note("budget exhausted; using deterministic answer")
            return self._with_explanation(bundle, baseline)
        except Exception as error:  # noqa: BLE001 - never lose a row
            self._note(f"agent loop failed ({type(error).__name__}); using deterministic")
            return self._with_explanation(bundle, baseline)
        return agent_output or self._with_explanation(bundle, baseline)

    # ---- the loop ----------------------------------------------------------

    def _loop(self, bundle: RequestBundle, baseline: AgentOutput) -> AgentOutput | None:
        state = AgentState(model=self._build_model(bundle))
        tools = self._tool_table(bundle, state)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM},
            {"role": "user", "content": self._opening(bundle)},
        ]

        rejections = 0
        for _ in range(self.settings.max_iterations):
            _compact(messages)
            # After the validator has turned the answer away twice, the model
            # that produced those answers is unlikely to find the problem on a
            # third try, so fall back to the strongest one available. For a
            # request already routed to that model this changes nothing -- there
            # is nothing stronger to reach for -- but it rescues the other half
            # of the pool, and it moves onto a different token bucket.
            model_name = (
                self.settings.escalation_model
                if rejections >= 2
                else self._pick_model(bundle.request.request_id)
            )
            reply = self.client.converse(
                model=model_name,
                messages=messages,
                tools=tools_for(
                    has_blank_amounts=any(e.amount is None for e in bundle.events),
                    has_messages=bool(bundle.messages),
                    context_loaded=state.context_loaded,
                    spending_searched=state.spending_searched,
                ),
                request_id=bundle.request.request_id,
            )
            if reply is None:
                # A failed call is not an exception, so without this the row
                # would quietly fall back to the deterministic answer with
                # nothing in the log to say it had happened.
                self._note(f"model call failed on {model_name}; using deterministic")
                return None

            calls = getattr(reply, "tool_calls", None)
            if not calls:
                # The model answered in prose instead of submitting; nudge once.
                messages.append({"role": "assistant", "content": reply.content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Use the tools. Call submit_answer once you have "
                            "evaluated the plans."
                        ),
                    }
                )
                continue

            self._note(
                "turn: " + ", ".join(c.function.name for c in calls)
            )
            messages.append(self._assistant_turn(reply, calls))
            finished: AgentOutput | None = None

            for call in calls:
                name = call.function.name
                arguments = _parse_arguments(call.function.arguments)
                handler = tools.get(name)
                if handler is None:
                    result: Any = {"error": f"unknown tool {name}"}
                elif name == "submit_answer":
                    candidate, errors = handler(arguments)
                    if not errors:
                        finished = candidate
                        result = {"accepted": True}
                    else:
                        rejections += 1
                        self._note(f"answer rejected: {errors[0]}")
                        result = {
                            "accepted": False,
                            "errors": errors,
                            "note": (
                                "Fix these and submit again. The plan was "
                                "re-simulated independently, so these are real "
                                "breaches, not warnings."
                            ),
                        }
                else:
                    result = handler(arguments)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _render(result),
                    }
                )

            if finished is not None:
                return finished

        self._note("iteration cap reached; using deterministic answer")
        return None

    def _pick_model(self, request_id: str) -> str:
        """Spread requests deterministically across the orchestrator pool.

        Each model has its own tokens-per-minute bucket, so alternating between
        them doubles available throughput. The choice is keyed on request_id so
        a re-run routes identically.
        """
        pool = self.settings.orchestrator_pool or (self.settings.orchestrator_model,)
        digest = sha1(request_id.encode("utf-8")).digest()
        return pool[digest[0] % len(pool)]

    @staticmethod
    def _assistant_turn(reply: Any, calls: list) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": reply.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in calls
            ],
        }

    # ---- prompt ------------------------------------------------------------

    def _opening(self, bundle: RequestBundle) -> str:
        request = bundle.request
        lines = [
            f"request_id: {request.request_id}",
            f"type: {request.request_type}",
            f"requested_amount: {request.requested_amount:,.2f} "
            f"{bundle.profile.home_currency}",
            f"request_date: {request.request_date.isoformat()}",
            f"desired_completion_date: {request.desired_completion_date.isoformat()}",
            f"allows_partial_payment: {str(request.allows_partial_payment).lower()}",
            f"the person asks: {request.request_text}",
            "",
            f"evidence attached: {len(bundle.messages)} message(s), "
            f"{len(bundle.images)} receipt image(s)",
            "",
            "Begin by calling load_context.",
        ]
        if self.retriever is not None:
            examples = self.retriever.examples(
                request.request_type, request.request_text, self.settings.few_shot_k
            )
            if examples:
                lines += ["", examples]
        return "\n".join(lines)

    # ---- tools -------------------------------------------------------------

    def _tool_table(
        self, bundle: RequestBundle, state: AgentState
    ) -> dict[str, Callable[[dict], Any]]:
        return {
            "load_context": lambda _: self._tool_load_context(bundle, state),
            "read_receipt": lambda a: self._tool_read_receipt(bundle, state, a),
            "resolve_messages": lambda _: self._tool_resolve_messages(bundle, state),
            "run_forecast": lambda a: self._tool_run_forecast(bundle, state, a),
            "evaluate_plans": lambda a: self._tool_evaluate_plans(bundle, state, a),
            "suggest_spending_changes": lambda _: self._tool_spending(bundle, state),
            "submit_answer": lambda a: self._tool_submit(bundle, state, a),
        }

    def _tool_load_context(self, bundle: RequestBundle, state: AgentState) -> dict:
        state.context_loaded = True
        profile = bundle.profile
        missing = [
            {
                "event_id": event.event_id,
                "description": event.description,
                "category": event.category,
                "date": event.cash_date.isoformat(),
                "has_image": any(
                    ref.related_event_id == event.event_id for ref in bundle.images
                ),
            }
            for event in bundle.events
            if event.amount is None
        ]
        return {
            "home_currency": profile.home_currency,
            "current_available_balance": round(profile.current_available_balance, 2),
            "minimum_balance_to_keep": round(profile.minimum_balance_to_keep, 2),
            "payment_methods_user_will_consider": profile.payment_methods_user_will_consider,
            "max_installment_months": profile.max_installment_months,
            "protected_categories": profile.expense_categories_to_protect,
            "willing_to_reduce": profile.expense_categories_user_is_willing_to_reduce,
            "willing_to_stop": profile.expense_categories_user_is_willing_to_stop,
            "recurring_series": [
                f"{s.key} {s.direction.value} {round(s.amount, 2)} every "
                f"{s.cadence_days}d last {s.last_seen.isoformat()} {s.flexibility.value}"
                for s in state.model.series
            ],
            # Summarised rather than itemised: the resolver sees the full list,
            # and the orchestrator only needs to know the scale of what is due.
            "known_future_commitments": {
                "count": len(state.model.known_flows),
                "net_total": round(sum(f.amount for f in state.model.known_flows), 2),
            },
            "payment_options": [
                f"{o.payment_option_id} {o.payment_method} "
                f"{o.number_of_payments}x{round(o.payment_amount, 2)} from "
                f"{o.first_payment_date.isoformat()} every {o.payment_frequency_days}d "
                f"total {round(o.total_payable_amount, 2)} spans {o.months_span}mo"
                for o in bundle.options
            ],
            "events_missing_amount": missing,
            "message_count": len(bundle.messages),
            "untrusted_messages_flagged": [
                m.message_id for m in bundle.messages if not m.is_trusted
            ],
            # The baseline forecast and ranked plans come back with the context so
            # a request carrying no evidence needs no further round trip. When a
            # receipt or message does change something, run_forecast and
            # evaluate_plans supersede these.
            "baseline_forecast": self._tool_run_forecast(bundle, state, {}),
            "baseline_ranked_plans": self._tool_evaluate_plans(bundle, state, {}),
            "evidence_still_to_resolve": bool(missing) or bool(bundle.messages),
        }

    def _tool_read_receipt(
        self, bundle: RequestBundle, state: AgentState, arguments: dict
    ) -> dict:
        event_id = str(arguments.get("event_id") or "")
        event = next((e for e in bundle.events if e.event_id == event_id), None)
        if event is None:
            return {"error": f"{event_id} is not an event for this person"}
        if event.amount is not None:
            return {"event_id": event_id, "amount": event.amount, "note": "already known"}
        ref = next(
            (r for r in bundle.images if r.related_event_id == event_id), None
        )
        if ref is None:
            return {
                "event_id": event_id,
                "amount": None,
                "note": "no receipt image is linked; do not assume a value",
            }

        amount = self.extractor.resolve_amount(
            ref, event, bundle.profile.home_currency, bundle.request.request_id
        )
        if amount is None:
            return {
                "event_id": event_id,
                "amount": None,
                "note": "receipt unreadable; the amount stays unknown, not zero",
            }

        state.resolved_amounts[event_id] = amount
        if self.evidence is not None:
            self.evidence.record_amount(bundle.request.request_id, event_id, amount)
        state.model = self._build_model(bundle, state.resolved_amounts)
        return {
            "event_id": event_id,
            "amount": round(amount, 2),
            "currency": event.currency or bundle.profile.home_currency,
            # The refreshed picture comes back with the evidence, so no separate
            # recompute turn is needed.
            "updated_forecast": self._tool_run_forecast(bundle, state, {}),
            "updated_ranked_plans": self._tool_evaluate_plans(bundle, state, {}),
        }

    def _tool_resolve_messages(self, bundle: RequestBundle, state: AgentState) -> dict:
        if not bundle.messages:
            return {"modifications": [], "note": "no messages attached"}
        analysis = self.resolver.resolve(
            bundle.messages, state.model, bundle.request.request_id
        )
        if self.evidence is not None:
            self.evidence.record_modifications(
                bundle.request.request_id, analysis.modifications
            )
        state.model = apply_modifications(state.model, analysis.modifications)
        result = {
            "modifications": [
                {
                    "action": m.action.value,
                    "event_id": m.event_id,
                    "series_key": m.series_key,
                    "new_amount": m.new_amount,
                    "new_date": m.new_date.isoformat() if m.new_date else None,
                    "reason": m.reason[:160],
                }
                for m in analysis.modifications
            ],
            "reasoning": analysis.reasoning[:400],
        }
        # As with read_receipt: hand back the picture these changes produce so
        # the model can answer without another round trip.
        result["updated_forecast"] = self._tool_run_forecast(bundle, state, {})
        result["updated_ranked_plans"] = self._tool_evaluate_plans(bundle, state, {})
        return result

    def _tool_run_forecast(
        self, bundle: RequestBundle, state: AgentState, arguments: dict
    ) -> dict:
        changes = (
            state.spending_changes if arguments.get("apply_spending_changes") else None
        )
        forecast = state.model.summarise(bundle.request.requested_amount, changes)
        return {
            "amount_safe_to_pay_today": forecast.amount_safe_to_pay,
            "earliest_date_for_full_payment": (
                forecast.earliest_full_payment_date.isoformat()
                if forecast.earliest_full_payment_date
                else None
            ),
            "lowest_projected_balance": forecast.minimum_balance_reached,
            "minimum_balance_to_keep": round(
                bundle.profile.minimum_balance_to_keep, 2
            ),
            "stays_above_minimum": forecast.is_safe,
            "spending_changes_applied": bool(changes),
        }

    def _tool_evaluate_plans(
        self, bundle: RequestBundle, state: AgentState, arguments: dict
    ) -> dict:
        changes = (
            state.spending_changes if arguments.get("use_spending_changes") else []
        )
        generator = PlanGenerator(
            bundle.request, bundle.profile, bundle.options, state.model
        )
        safe_today = state.model.amount_safe_today(
            bundle.request.requested_amount, changes or None
        )
        earliest = state.model.earliest_full_payment(
            bundle.request.requested_amount, changes or None
        )
        plans = generator.candidates(safe_today, earliest, changes)
        ranked = sorted(plans, key=generator._sort_key)
        state.plans = ranked

        return {
            "ranked_plans": [
                {
                    "method": p.method.value,
                    "payment_option_id": p.payment_option_id,
                    "plan": p.render_plan(),
                    "total_paid": round(p.total_cost, 2),
                    "payments": len(p.payments),
                    "completes_by_deadline": p.completes_by_deadline,
                    "uses_spending_changes": bool(p.spending_changes),
                }
                for p in ranked
            ],
            "rejected": self._rejection_notes(bundle, state, safe_today, earliest),
            "note": (
                "Plans are ranked best first: completes by deadline, then no "
                "spending changes, then cheapest, then earliest start, then "
                "fewest payments."
            ),
        }

    def _rejection_notes(
        self, bundle: RequestBundle, state: AgentState, safe_today: float, earliest
    ) -> list[str]:
        """Why the obvious alternatives are not on the list."""
        profile, request = bundle.profile, bundle.request
        notes: list[str] = []
        if not profile.accepts(PaymentMethod.FULL_PAYMENT):
            notes.append("full_payment: not a method this person will consider")
        if not profile.accepts(PaymentMethod.INSTALLMENTS):
            notes.append("installments: not a method this person will consider")
        elif profile.max_installment_months is None:
            notes.append("installments: max_installment_months is blank")
        else:
            for option in bundle.options:
                if (
                    option.payment_method == "installments"
                    and option.months_span > profile.max_installment_months
                ):
                    notes.append(
                        f"{option.payment_option_id}: spans {option.months_span} "
                        f"months, over the {profile.max_installment_months}-month limit"
                    )
        if not request.allows_partial_payment:
            notes.append("partial_payment: this request does not allow it")
        elif not profile.accepts(PaymentMethod.PARTIAL_PAYMENT):
            notes.append("partial_payment: not a method this person will consider")
        elif not 0 < safe_today < request.requested_amount:
            notes.append(
                f"partial_payment: needs 0 < safe today ({safe_today:,.2f}) < "
                f"requested ({request.requested_amount:,.2f})"
            )
        elif earliest is None or earliest > request.desired_completion_date:
            notes.append(
                "partial_payment: the remainder cannot be paid by the completion date"
            )
        return notes

    def _tool_spending(self, bundle: RequestBundle, state: AgentState) -> dict:
        forecast = state.model.summarise(bundle.request.requested_amount)
        deficit = max(
            0.0, bundle.request.requested_amount - forecast.amount_safe_to_pay
        )
        changes = suggest_spending_changes(state.model, bundle.profile, deficit)
        state.spending_changes = changes
        if not changes:
            return {
                "spending_changes": [],
                "note": (
                    "nothing may be changed: the flexible expenses are either "
                    "protected or not ones this person will adjust"
                ),
            }
        return {
            "spending_changes": [c.render() for c in changes],
            "deficit_to_cover": round(deficit, 2),
            "note": "pass use_spending_changes=true to evaluate_plans to apply these",
        }

    def _tool_submit(
        self, bundle: RequestBundle, state: AgentState, arguments: dict
    ) -> tuple[AgentOutput | None, list[str]]:
        request, profile = bundle.request, bundle.profile
        use_changes = bool(arguments.get("use_spending_changes"))
        changes = state.spending_changes if use_changes else []

        # Headline figures always exclude optional spending changes, per spec.
        clean = state.model.summarise(request.requested_amount)
        chosen = self._select_plan(state, str(arguments.get("plan_choice") or "none"))

        try:
            status = AffordabilityStatus(str(arguments.get("affordability_status")))
            method = PaymentMethod(str(arguments.get("recommended_payment_method")))
        except ValueError as error:
            return None, [f"invalid enum value: {error}"]

        candidate = AgentOutput(
            request_id=request.request_id,
            amount_safe_to_pay=clean.amount_safe_to_pay,
            affordability_status=status,
            recommended_payment_method=method,
            payment_plan=chosen.render_plan() if chosen else "none",
            earliest_date_for_full_payment=(
                request.request_date.isoformat()
                if status is AffordabilityStatus.AFFORDABLE_NOW
                else (
                    clean.earliest_full_payment_date.isoformat()
                    if clean.earliest_full_payment_date
                    else ""
                )
            ),
            spending_changes_needed=(
                "|".join(c.render() for c in changes[:3]) if changes and chosen else "none"
            ),
            decision_explanation=str(arguments.get("decision_explanation") or ""),
            requested_amount=request.requested_amount,
        )

        result = validate_output(
            candidate, request, profile, bundle.options, bundle.events, state.model
        )
        return (candidate if result.ok else None), result.errors

    @staticmethod
    def _select_plan(state: AgentState, choice: str) -> CandidatePlan | None:
        if choice in ("none", ""):
            return None
        for plan in state.plans:
            if plan.payment_option_id == choice:
                return plan
        for plan in state.plans:
            if plan.method.value == choice:
                return plan
        return state.plans[0] if state.plans else None

    # ---- deterministic fallback -------------------------------------------

    def _deterministic(self, bundle: RequestBundle) -> AgentOutput:
        """The engine's own answer, used as a floor the agent must beat."""
        model = self._build_model(bundle)
        decision = decide(
            bundle.request, bundle.profile, bundle.options, model, bundle.events
        )
        return decision.output

    def _with_explanation(
        self, bundle: RequestBundle, output: AgentOutput
    ) -> AgentOutput:
        """Finish the deterministic answer, and hold it to the same checks.

        The fallback used to bypass validation entirely, which let an
        internally inconsistent row reach output.csv unchallenged. It now faces
        the validator like any other answer, and a failure is logged rather than
        shipped in silence.
        """
        if not output.decision_explanation:
            output = output.model_copy(
                update={"decision_explanation": _template_explanation(bundle, output)}
            )
        result = validate_output(
            output,
            bundle.request,
            bundle.profile,
            bundle.options,
            bundle.events,
            self._build_model(bundle),
        )
        if not result.ok:
            self._note(f"deterministic answer failed validation: {result.errors[0]}")
        return output

    def _build_model(
        self, bundle: RequestBundle, resolved: dict[str, float] | None = None
    ) -> ForecastModel:
        events = bundle.events
        if resolved:
            events = [
                event.model_copy(update={"amount": resolved[event.event_id]})
                if event.event_id in resolved and event.amount is None
                else event
                for event in events
            ]
        return build_forecast_model(
            bundle.profile,
            events,
            bundle.request.request_date,
            self.converter,
            self.forecast_config,
        )

    def _note(self, text: str) -> None:
        if self.log is not None:
            self.log.info(text)


def _compact(messages: list[dict[str, Any]]) -> None:
    """Shrink tool results the model has already acted on.

    The whole conversation is resent every turn, so leaving five full tool
    payloads in place triples the token cost of a request that needed evidence.
    The newest results stay intact; older ones keep only their identity.
    """
    positions = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for index in positions[:-KEEP_TOOL_RESULTS_IN_FULL]:
        content = messages[index].get("content") or ""
        if content.startswith('{"superseded"'):
            continue
        messages[index]["content"] = (
            '{"superseded":true,"note":"result already used; '
            f'was {len(content)} chars"}}'
        )


def _parse_arguments(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _render(result: Any) -> str:
    text = json.dumps(result, default=str, separators=(",", ":"))
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + '..."truncated":true}'


def _template_explanation(bundle: RequestBundle, output: AgentOutput) -> str:
    """Grounded fallback wording when no model explanation is available."""
    currency = bundle.profile.home_currency
    floor = bundle.profile.minimum_balance_to_keep
    amount = bundle.request.requested_amount
    method = output.recommended_payment_method

    if method is PaymentMethod.FULL_PAYMENT:
        return (
            f"Pay {currency} {amount:,.2f} in full on "
            f"{bundle.request.request_date.isoformat()}. This keeps at least "
            f"{currency} {floor:,.2f} available across the next 90 days."
        )
    if method is PaymentMethod.PARTIAL_PAYMENT:
        return (
            f"Pay {currency} {output.amount_safe_to_pay:,.2f} now and the "
            f"remaining {currency} {amount - output.amount_safe_to_pay:,.2f} on "
            f"{output.earliest_date_for_full_payment}, which protects the "
            f"{currency} {floor:,.2f} minimum balance throughout."
        )
    if method is PaymentMethod.INSTALLMENTS:
        return (
            f"Use the installment plan {output.payment_plan.replace('|', ', ')}. "
            f"Each payment is affordable on its date and the balance stays above "
            f"{currency} {floor:,.2f}."
        )
    if method is PaymentMethod.WAIT:
        when = output.earliest_date_for_full_payment.strip()
        if not when:
            # Should be unreachable now that `wait` always carries its date, but
            # a blank here would read as "pay in full on ." to the user.
            return (
                f"Hold off on {currency} {amount:,.2f} for now. Paying today "
                f"would take the balance below the {currency} {floor:,.2f} "
                f"minimum you want to keep."
            )
        return (
            f"Wait and pay {currency} {amount:,.2f} in full on {when}. Paying "
            f"sooner would take the balance below the {currency} {floor:,.2f} "
            f"minimum."
        )
    return (
        f"Do not commit {currency} {amount:,.2f} by "
        f"{bundle.request.desired_completion_date.isoformat()}. No available "
        f"option keeps the {currency} {floor:,.2f} minimum balance protected "
        f"across the next 90 days."
    )
