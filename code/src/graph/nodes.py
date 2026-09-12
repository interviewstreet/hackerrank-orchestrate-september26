from datetime import date
from code.src.state import AgentState
from code.src.data.repository import DataRepository
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    FinancialEvent,
    NormalizedFinancialEvent,
    ImageFact,
    MessageFact,
    PaymentPlan,
    PlanEvaluation,
    SpendingChange,
    Decision,
    OutputRow,
    Forecast,
)
from code.src.finance.lifecycle import resolve_event_lifecycle
from code.src.finance.currency import convert_currency, convert_currency_detailed
from code.src.finance.recurrence import generate_missing_recurrences
from code.src.finance.capacity import (
    calculate_baseline_amount_safe_to_pay,
    calculate_earliest_full_payment_date,
)
from code.src.finance.plans import generate_candidate_plans, evaluate_plan
from code.src.finance.optimizer import search_best_spending_changes
from code.src.finance.ranking import select_final_decision
from code.src.finance.simulator import simulate_plan
from code.src.llm.message_extractor import extract_message_fact
from code.src.llm.image_extractor import extract_image_fact
from code.src.llm.explanation import generate_explanation


def make_audit_entry(node_name: str, action: str, **kwargs) -> dict:
    return {"node": node_name, "action": action, **kwargs}


def load_request_node(state: AgentState, repo: DataRepository) -> dict:
    req_id = state.get("run_id")
    request = repo.get_request(req_id)
    if not request:
        return {
            "errors": [f"Request ID '{req_id}' not found in repository."],
            "audit_log": [make_audit_entry("load_request", "error_request_not_found", request_id=req_id)],
        }
    return {
        "request": request,
        "audit_log": [make_audit_entry("load_request", "loaded_request", request_id=req_id, user_id=request.user_id)],
    }


def load_user_context_node(state: AgentState, repo: DataRepository) -> dict:
    request = state["request"]
    profile = repo.get_profile(request.user_id)
    if not profile:
        return {
            "errors": [f"Profile for user '{request.user_id}' not found."],
            "audit_log": [make_audit_entry("load_user_context", "error_profile_not_found", user_id=request.user_id)],
        }
    return {
        "profile": profile,
        "audit_log": [make_audit_entry("load_user_context", "loaded_profile", user_id=request.user_id, currency=profile.home_currency)],
    }


def load_financial_data_node(state: AgentState, repo: DataRepository) -> dict:
    request = state["request"]
    u_id = request.user_id

    raw_events = repo.get_events(u_id)
    payment_options = repo.get_payment_options(request.request_id)
    messages = repo.get_messages(u_id, request.request_id)
    images = repo.get_images(u_id, request.request_id)

    return {
        "raw_events": raw_events,
        "payment_options": payment_options,
        "messages": messages,
        "images": images,
        "audit_log": [
            make_audit_entry(
                "load_financial_data",
                "loaded_data",
                events_count=len(raw_events),
                options_count=len(payment_options),
                messages_count=len(messages),
                images_count=len(images),
            )
        ],
    }


def resolve_images_node(state: AgentState, repo: DataRepository) -> dict:
    images = state.get("images", [])
    raw_events = state.get("raw_events", [])
    missing_events = {e.event_id: e for e in raw_events if e.amount is None}

    image_facts: list[ImageFact] = []
    for img in images:
        ev_id = img.get("related_event_id")
        if ev_id and ev_id in missing_events:
            fact = extract_image_fact(img)
            image_facts.append(fact)

    return {
        "image_facts": image_facts,
        "audit_log": [make_audit_entry("resolve_images", "extracted_image_facts", count=len(image_facts))],
    }


def resolve_messages_node(state: AgentState) -> dict:
    messages = state.get("messages", [])
    message_facts: list[MessageFact] = []

    for msg in messages:
        fact = extract_message_fact(msg)
        message_facts.append(fact)

    return {
        "message_facts": message_facts,
        "audit_log": [make_audit_entry("resolve_messages", "extracted_message_facts", count=len(message_facts))],
    }


def resolve_event_lifecycle_node(state: AgentState) -> dict:
    raw_events = state.get("raw_events", [])
    lifecycle_events = resolve_event_lifecycle(raw_events)

    return {
        "raw_events": lifecycle_events,
        "audit_log": [
            make_audit_entry(
                "resolve_event_lifecycle",
                "resolved_lifecycles",
                initial_count=len(raw_events),
                active_count=len(lifecycle_events),
            )
        ],
    }


def normalize_events_node(state: AgentState, repo: DataRepository) -> dict:
    request = state["request"]
    profile = state["profile"]
    raw_events = state.get("raw_events", [])
    image_facts = {f.related_event_id: f for f in state.get("image_facts", [])}
    message_facts = {f.related_event_id: f for f in state.get("message_facts", []) if f.related_event_id}

    # Apply image facts and direct message facts to all raw events (both historical and future)
    for e in raw_events:
        if e.event_id in image_facts:
            img_fact = image_facts[e.event_id]
            if img_fact.extracted_amount is not None:
                e.amount = img_fact.extracted_amount
            if img_fact.extracted_currency:
                e.currency = img_fact.extracted_currency
        if e.event_id in message_facts:
            msg_fact = message_facts[e.event_id]
            if msg_fact.new_amount is not None:
                e.amount = msg_fact.new_amount
            if msg_fact.new_date is not None:
                e.settlement_date = msg_fact.new_date
            if msg_fact.new_status is not None:
                e.status = msg_fact.new_status

    # Separate historical vs explicit future events
    historical_events = [e for e in raw_events if e.settlement_date < request.request_date]
    explicit_future_events = [e for e in raw_events if e.settlement_date >= request.request_date]

    # Generate missing recurrences (preventing duplicates with explicit future events)
    missing_recurrences = generate_missing_recurrences(
        historical_events=historical_events,
        request_date=request.request_date,
        horizon_days=90,
        explicit_future_events=explicit_future_events,
        user_home_currency=profile.home_currency,
    )

    combined_events: list[NormalizedFinancialEvent] = []

    # 1. Normalize explicit future events
    for e in explicit_future_events:
        amt = e.amount
        curr = e.currency
        settle_d = e.settlement_date
        st = e.status

        # If amount still missing, fallback safely
        final_amt = amt if amt is not None else 0.0

        # Currency conversion
        converted_amt = convert_currency(
            amount=final_amt,
            from_currency=curr,
            to_currency=profile.home_currency,
            rate_date=settle_d,
            repo=repo,
        )

        norm_ev = NormalizedFinancialEvent(
            event_id=e.event_id,
            user_id=e.user_id,
            event_type=e.event_type,
            description=e.description,
            category=e.category,
            direction=e.direction,
            amount=final_amt,
            currency=curr,
            converted_amount=converted_amt,
            event_date=e.event_date,
            settlement_date=settle_d,
            status=st,
            linked_event_id=e.linked_event_id,
            flexibility=e.flexibility,
            minimum_allowed_amount=e.minimum_allowed_amount,
            is_recurring=(e.event_type == "subscription" or e.category in ("rent", "housing", "utilities", "salary")),
            evidence_source="explicit_event",
        )
        combined_events.append(norm_ev)

    # 2. Add generated recurrences (normalizing their currencies)
    for rec in missing_recurrences:
        rec.converted_amount = convert_currency(
            amount=rec.amount,
            from_currency=rec.currency,
            to_currency=profile.home_currency,
            rate_date=rec.settlement_date,
            repo=repo,
        )
        combined_events.append(rec)

    # Check general messages affecting user salary without explicit event link
    for m_fact in state.get("message_facts", []):
        if not m_fact.related_event_id:
            sal_events = [ev for ev in combined_events if ev.category == "salary"]
            if not sal_events:
                continue

            # Case 1: Message specifies a date change (and optionally amount)
            if m_fact.new_date is not None:
                new_day = m_fact.new_date.day
                # Target the salary event in the same month/year or the immediate next salary
                matched = False
                for ev in sal_events:
                    if ev.settlement_date.year == m_fact.new_date.year and ev.settlement_date.month == m_fact.new_date.month:
                        if m_fact.new_amount is not None:
                            ev.amount = m_fact.new_amount
                            ev.original_amount = m_fact.new_amount
                        ev.settlement_date = m_fact.new_date
                        ev.event_date = m_fact.new_date
                        ev.converted_amount = convert_currency(
                            ev.amount, ev.currency, profile.home_currency, ev.settlement_date, repo
                        )
                        matched = True
                        break
                if not matched and sal_events:
                    if m_fact.new_amount is not None:
                        sal_events[0].amount = m_fact.new_amount
                        sal_events[0].original_amount = m_fact.new_amount
                    sal_events[0].settlement_date = m_fact.new_date
                    sal_events[0].event_date = m_fact.new_date
                    sal_events[0].converted_amount = convert_currency(
                        sal_events[0].amount, sal_events[0].currency, profile.home_currency, sal_events[0].settlement_date, repo
                    )

                # Subsequent salary events shift to this new day of month
                for ev in sal_events:
                    if ev.settlement_date > m_fact.new_date:
                        import calendar
                        max_d = calendar.monthrange(ev.settlement_date.year, ev.settlement_date.month)[1]
                        shifted_d = min(new_day, max_d)
                        ev.settlement_date = ev.settlement_date.replace(day=shifted_d)
                        ev.event_date = ev.settlement_date
                        if m_fact.new_amount is not None and (getattr(m_fact, "affects_recurrence", False) or "monthly" in m_fact.evidence.lower() or "bulanan" in m_fact.evidence.lower()):
                            ev.amount = m_fact.new_amount
                            ev.original_amount = m_fact.new_amount
                        ev.converted_amount = convert_currency(
                            ev.amount, ev.currency, profile.home_currency, ev.settlement_date, repo
                        )

            # Case 2: Only amount specified (no date change)
            elif m_fact.new_amount is not None:
                affects_rec = getattr(m_fact, "affects_recurrence", False) or "monthly" in m_fact.evidence.lower() or "bulanan" in m_fact.evidence.lower()
                if affects_rec:
                    for ev in sal_events:
                        ev.amount = m_fact.new_amount
                        ev.original_amount = m_fact.new_amount
                        ev.converted_amount = convert_currency(
                            ev.amount, ev.currency, profile.home_currency, ev.settlement_date, repo
                        )
                elif sal_events:
                    sal_events[0].amount = m_fact.new_amount
                    sal_events[0].original_amount = m_fact.new_amount
                    sal_events[0].converted_amount = convert_currency(
                        sal_events[0].amount, sal_events[0].currency, profile.home_currency, sal_events[0].settlement_date, repo
                    )

    combined_events.sort(key=lambda x: x.settlement_date)

    return {
        "resolved_events": combined_events,
        "audit_log": [
            make_audit_entry(
                "normalize_events",
                "normalized_events",
                explicit_count=len(explicit_future_events),
                recurrence_count=len(missing_recurrences),
                total_count=len(combined_events),
            )
        ],
    }


def convert_currencies_node(state: AgentState, repo: DataRepository) -> dict:
    """
    Dedicated node responsible for currency conversion adhering strictly to CURRENCY RULE:

    All financial calculations must be performed in the user's home currency.

    For every financial event:
    IF event.currency == user.home_currency:
        converted_amount = original_amount
    ELSE:
        look up the applicable exchange rate from exchange_rates.csv
        using the challenge-specified date and currency pair.
        converted_amount = original_amount * rate

    Never perform arithmetic across mixed currencies.

    Store both:
    - original_amount
    - original_currency
    - converted_amount
    - home_currency
    - exchange_rate_used
    - exchange_rate_date

    If a required exchange rate is unavailable:
        do NOT invent a rate.
        Record an error/warning and follow the repository's specified fallback.
    """
    profile = state["profile"]
    home_currency = profile.home_currency
    events = state.get("resolved_events", [])
    warnings: list[str] = []
    converted_events: list[NormalizedFinancialEvent] = []

    for ev in events:
        orig_amt = ev.original_amount if ev.original_amount is not None else ev.amount
        orig_curr = ev.original_currency or ev.currency

        if orig_curr == home_currency:
            ev.original_amount = orig_amt
            ev.original_currency = orig_curr
            ev.converted_amount = orig_amt
            ev.home_currency = home_currency
            ev.exchange_rate_used = 1.0
            ev.exchange_rate_date = ev.settlement_date
        else:
            conv = convert_currency_detailed(
                original_amount=orig_amt,
                from_currency=orig_curr,
                home_currency=home_currency,
                rate_date=ev.settlement_date,
                repo=repo,
            )
            ev.original_amount = conv.original_amount
            ev.original_currency = conv.original_currency
            ev.converted_amount = conv.converted_amount
            ev.home_currency = conv.home_currency
            ev.exchange_rate_used = conv.exchange_rate_used
            ev.exchange_rate_date = conv.exchange_rate_date

            if conv.warning:
                warnings.append(f"Event {ev.event_id}: {conv.warning}")

        converted_events.append(ev)

    return {
        "resolved_events": converted_events,
        "warnings": warnings,
        "audit_log": [
            make_audit_entry(
                "convert_currencies",
                "applied_currency_rule",
                home_currency=home_currency,
                converted_count=len(converted_events),
                warnings_count=len(warnings),
            )
        ],
    }


def validate_resolved_data_node(state: AgentState) -> dict:
    """
    Mandatory validation node (Issue 21) verifying data consistency before simulation.
    """
    events = state.get("resolved_events", [])
    errors = []

    profile = state["profile"]
    for ev in events:
        if ev.amount is None or ev.converted_amount < 0:
            errors.append(f"Invalid amount for event {ev.event_id}: {ev.amount}")
        if not ev.settlement_date:
            errors.append(f"Missing settlement date for event {ev.event_id}")
        if ev.home_currency != profile.home_currency:
            errors.append(f"Event {ev.event_id} home_currency '{ev.home_currency}' does not match user '{profile.home_currency}'")

    return {
        "errors": errors,
        "audit_log": [make_audit_entry("validate_resolved_data", "validated", error_count=len(errors))],
    }


def build_financial_state_node(state: AgentState) -> dict:
    profile = state["profile"]
    request = state["request"]
    resolved_events = state.get("resolved_events", [])

    canonical_state = {
        "user_id": profile.user_id,
        "request_id": request.request_id,
        "request_date": request.request_date.isoformat(),
        "starting_balance": profile.current_available_balance,
        "minimum_balance_to_keep": profile.minimum_balance_to_keep,
        "home_currency": profile.home_currency,
        "future_events_count": len(resolved_events),
    }

    return {
        "financial_state": canonical_state,
        "audit_log": [make_audit_entry("build_financial_state", "built_canonical_state", **canonical_state)],
    }


def generate_base_forecast_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    resolved_events = state.get("resolved_events", [])

    res = simulate_plan(
        starting_balance=profile.current_available_balance,
        base_events=resolved_events,
        payment_plan=None,
        minimum_balance=profile.minimum_balance_to_keep,
        start_date=request.request_date,
        horizon_days=90,
    )

    base_forecast = Forecast(
        start_date=request.request_date,
        end_date=request.request_date,
        starting_balance=profile.current_available_balance,
        lowest_balance=res["lowest_balance"],
        lowest_balance_date=res["lowest_balance_date"],
        ending_balance=res["ending_balance"],
        safe=res["safe"],
    )

    return {
        "base_forecast": base_forecast,
        "audit_log": [
            make_audit_entry(
                "generate_base_forecast",
                "simulated_base_forecast",
                lowest_balance=res["lowest_balance"],
                safe=res["safe"],
            )
        ],
    }


def calculate_baseline_capacity_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    resolved_events = state.get("resolved_events", [])

    safe_amount = calculate_baseline_amount_safe_to_pay(
        starting_balance=profile.current_available_balance,
        base_events=resolved_events,
        minimum_balance=profile.minimum_balance_to_keep,
        request_date=request.request_date,
        requested_amount=request.requested_amount,
    )

    earliest_date = calculate_earliest_full_payment_date(
        starting_balance=profile.current_available_balance,
        base_events=resolved_events,
        minimum_balance=profile.minimum_balance_to_keep,
        request_date=request.request_date,
        requested_amount=request.requested_amount,
        desired_completion_date=request.desired_completion_date,
    )

    return {
        "baseline_amount_safe_to_pay": safe_amount,
        "earliest_baseline_full_payment_date": earliest_date,
        "audit_log": [
            make_audit_entry(
                "calculate_baseline_capacity",
                "calculated_capacity",
                baseline_safe_amount=safe_amount,
                earliest_full_payment_date=earliest_date.isoformat() if earliest_date else None,
            )
        ],
    }


def generate_candidate_plans_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    options = state.get("payment_options", [])
    safe_amt = state["baseline_amount_safe_to_pay"]
    earliest_date = state["earliest_baseline_full_payment_date"]

    plans = generate_candidate_plans(
        request=request,
        profile=profile,
        options=options,
        baseline_safe_amount=safe_amt,
        earliest_full_payment_date=earliest_date,
    )

    return {
        "candidate_plans": plans,
        "audit_log": [make_audit_entry("generate_candidate_plans", "generated_plans", count=len(plans))],
    }


def evaluate_plans_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    resolved_events = state.get("resolved_events", [])
    candidate_plans = state.get("candidate_plans", [])

    evaluations = [
        evaluate_plan(
            plan=p,
            request=request,
            profile=profile,
            base_events=resolved_events,
        )
        for p in candidate_plans
    ]

    safe_count = sum(1 for e in evaluations if e.eligible)

    return {
        "evaluated_plans": evaluations,
        "audit_log": [
            make_audit_entry(
                "evaluate_plans",
                "evaluated_plans",
                total=len(evaluations),
                safe_and_eligible=safe_count,
            )
        ],
    }


def generate_change_sets_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    resolved_events = state.get("resolved_events", [])
    options = state.get("payment_options", [])

    best_changes, opt_evals = search_best_spending_changes(
        request=request,
        profile=profile,
        base_events=resolved_events,
        options=options,
        max_changes=3,
    )

    return {
        "applied_spending_changes": best_changes,
        "optimized_evaluations": opt_evals,
        "evaluated_change_sets": [],
        "audit_log": [
            make_audit_entry(
                "generate_change_sets",
                "optimized_spending",
                changes_count=len(best_changes),
                eligible_plans=len(opt_evals),
            )
        ],
    }


def evaluate_change_sets_node(state: AgentState) -> dict:
    # Passthrough since search_best_spending_changes already performed bounded evaluation
    return {"audit_log": [make_audit_entry("evaluate_change_sets", "completed")]}


def select_decision_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    safe_amt = state["baseline_amount_safe_to_pay"]
    earliest_date = state["earliest_baseline_full_payment_date"]
    base_evals = state.get("evaluated_plans", [])
    applied_changes = state.get("applied_spending_changes", [])
    opt_evals = state.get("optimized_evaluations", [])

    decision = select_final_decision(
        request=request,
        profile=profile,
        baseline_safe_amount=safe_amt,
        earliest_full_payment_date=earliest_date,
        base_evaluations=base_evals,
        optimized_evaluations=opt_evals,
        applied_changes=applied_changes,
    )

    return {
        "decision": decision,
        "audit_log": [
            make_audit_entry(
                "select_decision",
                "selected_decision",
                status=decision.affordability_status,
                method=decision.recommended_payment_method,
            )
        ],
    }


def generate_explanation_node(state: AgentState) -> dict:
    request = state["request"]
    profile = state["profile"]
    decision = state["decision"]
    applied_changes = state.get("applied_spending_changes", [])

    # Find the chosen evaluation if any
    plan_eval = None
    for ev in state.get("evaluated_plans", []):
        if ev.plan.method == decision.recommended_payment_method and ev.eligible:
            plan_eval = ev
            break

    explanation = generate_explanation(
        request=request,
        profile=profile,
        decision=decision,
        plan_eval=plan_eval,
        applied_changes=applied_changes,
    )

    decision.decision_explanation = explanation

    return {
        "decision": decision,
        "explanation": explanation,
        "audit_log": [make_audit_entry("generate_explanation", "generated_explanation")],
    }


def validate_output_node(state: AgentState) -> dict:
    decision = state["decision"]

    output_row = OutputRow(
        request_id=decision.request_id,
        amount_safe_to_pay=decision.amount_safe_to_pay,
        affordability_status=decision.affordability_status,
        recommended_payment_method=decision.recommended_payment_method,
        payment_plan=decision.payment_plan,
        earliest_date_for_full_payment=decision.earliest_date_for_full_payment,
        spending_changes_needed=decision.spending_changes_needed,
        decision_explanation=decision.decision_explanation,
    )

    return {
        "output_row": output_row,
        "audit_log": [make_audit_entry("validate_output", "validated_output_row", request_id=output_row.request_id)],
    }
