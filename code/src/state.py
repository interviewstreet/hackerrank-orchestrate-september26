import operator
from datetime import date
from typing import Annotated, TypedDict

from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    FinancialEvent,
    NormalizedFinancialEvent,
    ImageFact,
    MessageFact,
    SpendingChange,
    ChangeSetEvaluation,
    PaymentOption,
    PaymentPlan,
    PlanEvaluation,
    Forecast,
    Decision,
    OutputRow,
)


class AgentState(TypedDict, total=False):
    run_id: str

    request: RequestContext
    profile: UserFinancialProfile

    raw_events: list[FinancialEvent]
    messages: list[dict]
    images: list[dict]
    payment_options: list[PaymentOption]
    exchange_rates: list[dict]

    image_facts: list[ImageFact]
    message_facts: list[MessageFact]

    resolved_events: list[NormalizedFinancialEvent]

    financial_state: dict

    base_forecast: Forecast

    baseline_amount_safe_to_pay: float
    earliest_baseline_full_payment_date: date | None

    candidate_plans: list[PaymentPlan]
    evaluated_plans: list[PlanEvaluation]

    candidate_change_sets: list[list[SpendingChange]]
    evaluated_change_sets: list[ChangeSetEvaluation]

    applied_spending_changes: list[SpendingChange]
    optimized_evaluations: list[PlanEvaluation]

    decision: Decision
    explanation: str
    output_row: OutputRow

    optimization_iteration: int

    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    audit_log: Annotated[list[dict], operator.add]
