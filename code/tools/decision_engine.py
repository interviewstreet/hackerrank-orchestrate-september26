"""Turn a forecast into a complete, validated recommendation.

Two headline fields are reported *before* optional spending changes, per the
spec: ``amount_safe_to_pay`` and ``earliest_date_for_full_payment``. Spending
changes may only be used to make a *plan* viable, never to inflate those two
numbers -- so the engine keeps an unmodified forecast alongside the modified one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tools.balance_forecaster import ForecastModel
from tools.plan_generator import PlanGenerator, classify
from tools.spending_optimizer import suggest_spending_changes
from validators.schemas import (
    AffordabilityStatus,
    AgentOutput,
    BalanceForecast,
    CandidatePlan,
    FinancialEvent,
    FinancialProfile,
    PaymentMethod,
    PaymentOption,
    RequestRow,
    SpendingChange,
)


@dataclass
class Decision:
    """The engine's full working, so the agent can explain and audit it."""

    output: AgentOutput
    forecast: BalanceForecast
    plan: CandidatePlan | None
    considered: list[CandidatePlan]
    spending_changes: list[SpendingChange]


def decide(
    request: RequestRow,
    profile: FinancialProfile,
    options: list[PaymentOption],
    model: ForecastModel,
    events: list[FinancialEvent],
) -> Decision:
    """Produce the best safe recommendation for one request."""
    forecast = model.summarise(request.requested_amount)
    generator = PlanGenerator(request, profile, options, model)

    # Pass 1: no spending changes -- always preferred by the ranking rules.
    considered = generator.candidates(
        forecast.amount_safe_to_pay, forecast.earliest_full_payment_date
    )
    best = generator.rank(considered)
    changes: list[SpendingChange] = []

    # Pass 2: only if nothing completes the request without help.
    if best is None or not best.completes_by_deadline:
        deficit = max(
            0.0, request.requested_amount - forecast.amount_safe_to_pay
        )
        changes = suggest_spending_changes(model, profile, deficit)
        if changes:
            with_changes = generator.candidates(
                model.amount_safe_today(request.requested_amount, changes),
                model.earliest_full_payment(request.requested_amount, changes),
                changes,
            )
            improved = generator.rank(with_changes)
            if improved is not None and _prefer(improved, best):
                best, considered = improved, considered + with_changes
            else:
                changes = []

    status = classify(best, request, profile, forecast.earliest_full_payment_date)
    method = best.method if best is not None else PaymentMethod.NOT_RECOMMENDED
    output = AgentOutput(
        request_id=request.request_id,
        amount_safe_to_pay=forecast.amount_safe_to_pay,
        affordability_status=status,
        recommended_payment_method=method,
        payment_plan=best.render_plan() if best is not None else "none",
        earliest_date_for_full_payment=_render_date(
            forecast.earliest_full_payment_date, status, request
        ),
        spending_changes_needed=_render_changes(best),
        decision_explanation="",
        requested_amount=request.requested_amount,
    )
    return Decision(
        output=output,
        forecast=forecast,
        plan=best,
        considered=considered,
        spending_changes=best.spending_changes if best else [],
    )


def _prefer(candidate: CandidatePlan, incumbent: CandidatePlan | None) -> bool:
    """A plan needing changes only wins if it actually completes the request."""
    if not candidate.completes_by_deadline:
        return False
    return incumbent is None or not incumbent.completes_by_deadline


def _render_date(
    earliest: date | None, status: AffordabilityStatus, request: RequestRow
) -> str:
    if status is AffordabilityStatus.AFFORDABLE_NOW:
        return request.request_date.isoformat()
    return earliest.isoformat() if earliest is not None else ""


def _render_changes(plan: CandidatePlan | None) -> str:
    if plan is None or not plan.spending_changes:
        return "none"
    return "|".join(change.render() for change in plan.spending_changes[:3])
