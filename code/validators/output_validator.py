"""Independent verification of a proposed output row.

Nothing reaches output.csv without passing through here. The checks do not
trust the agent's arithmetic: the payment plan is parsed back out of its string
form and re-simulated against the forecast, so a plan that breaches the user's
minimum balance is rejected even if the agent asserted it was safe.
"""

from __future__ import annotations

from datetime import date

from tools.balance_forecaster import ForecastModel
from validators.schemas import (
    AffordabilityStatus,
    AgentOutput,
    CashFlow,
    FinancialEvent,
    FinancialProfile,
    PaymentMethod,
    PaymentOption,
    RequestRow,
    ValidationResult,
)

CENT = 0.02


def validate_output(
    output: AgentOutput,
    request: RequestRow,
    profile: FinancialProfile,
    options: list[PaymentOption],
    events: list[FinancialEvent],
    model: ForecastModel,
) -> ValidationResult:
    """Run every structural, semantic and safety check on one row."""
    errors: list[str] = []
    errors += _check_amount(output, request)
    payments, plan_errors = _parse_plan(output.payment_plan)
    errors += plan_errors
    errors += _check_dates(output, request, payments)
    errors += _check_method_consistency(output, request, profile, payments)
    errors += _check_installments(output, options, payments)
    errors += _check_partial(output, request, payments)
    errors += _check_spending_changes(output, profile, events)
    if not errors:
        errors += _check_safety(output, profile, model, payments)
    return ValidationResult(ok=not errors, errors=errors)


def _check_amount(output: AgentOutput, request: RequestRow) -> list[str]:
    if output.amount_safe_to_pay < -CENT:
        return ["amount_safe_to_pay is negative"]
    if output.amount_safe_to_pay > request.requested_amount + CENT:
        return [
            f"amount_safe_to_pay {output.amount_safe_to_pay} exceeds "
            f"requested_amount {request.requested_amount}"
        ]
    return []


def _parse_plan(plan: str) -> tuple[list[tuple[date, float]], list[str]]:
    if plan.strip() == "none":
        return [], []
    payments: list[tuple[date, float]] = []
    for entry in plan.split("|"):
        head, _, tail = entry.partition(":")
        try:
            payments.append((date.fromisoformat(head), float(tail)))
        except ValueError:
            return payments, [f"unparseable payment_plan entry {entry!r}"]
    errors: list[str] = []
    if any(amount <= 0 for _, amount in payments):
        errors.append("payment_plan contains a non-positive amount")
    if payments != sorted(payments, key=lambda p: p[0]):
        errors.append("payment_plan is not in chronological order")
    return payments, errors


def _check_dates(
    output: AgentOutput, request: RequestRow, payments: list[tuple[date, float]]
) -> list[str]:
    errors: list[str] = []
    earliest = output.earliest_date_for_full_payment.strip()
    if earliest:
        try:
            parsed = date.fromisoformat(earliest)
        except ValueError:
            return [f"earliest_date_for_full_payment {earliest!r} is not YYYY-MM-DD"]
        if parsed < request.request_date:
            errors.append("earliest_date_for_full_payment precedes request_date")

    if output.affordability_status is AffordabilityStatus.AFFORDABLE_NOW:
        if earliest != request.request_date.isoformat():
            errors.append("affordable_now requires earliest date == request_date")
    return errors


def _check_method_consistency(
    output: AgentOutput,
    request: RequestRow,
    profile: FinancialProfile,
    payments: list[tuple[date, float]],
) -> list[str]:
    errors: list[str] = []
    method = output.recommended_payment_method
    status = output.affordability_status

    if method is not PaymentMethod.NOT_RECOMMENDED and not payments:
        errors.append(f"{method.value} requires a payment_plan")
    if method is PaymentMethod.NOT_RECOMMENDED and payments:
        errors.append("not_recommended must have payment_plan 'none'")

    # An actionable method must be one the user actually accepts.
    if method in (
        PaymentMethod.FULL_PAYMENT,
        PaymentMethod.PARTIAL_PAYMENT,
        PaymentMethod.INSTALLMENTS,
    ) and not profile.accepts(method):
        errors.append(f"{method.value} is not in payment_methods_user_will_consider")
    if method is PaymentMethod.WAIT and not profile.accepts(PaymentMethod.FULL_PAYMENT):
        errors.append("wait requires the user to accept full_payment")

    if status is AffordabilityStatus.AFFORDABLE_NOW and method is not PaymentMethod.FULL_PAYMENT:
        errors.append("affordable_now requires full_payment")
    if method is PaymentMethod.WAIT and status is not AffordabilityStatus.AFFORDABLE_LATER:
        errors.append("wait requires affordable_later")
    if method is PaymentMethod.WAIT:
        earliest = output.earliest_date_for_full_payment.strip()
        if not earliest:
            errors.append("wait requires a non-empty earliest_date_for_full_payment")
        elif payments and payments[0][0].isoformat() != earliest:
            errors.append(
                "wait must pay on earliest_date_for_full_payment "
                f"({payments[0][0].isoformat()} != {earliest})"
            )
        if len(payments) != 1:
            errors.append("wait must be a single payment")
        if payments and abs(payments[0][1] - request.requested_amount) > CENT:
            errors.append("wait must pay the whole requested_amount")
    if method is PaymentMethod.NOT_RECOMMENDED and status not in (
        AffordabilityStatus.NOT_AFFORDABLE,
        AffordabilityStatus.AFFORDABLE_LATER,
    ):
        errors.append("not_recommended requires not_affordable or affordable_later")

    if method is PaymentMethod.FULL_PAYMENT and payments:
        if abs(payments[0][1] - request.requested_amount) > CENT:
            errors.append("full_payment must pay the whole requested_amount")
        if len(payments) != 1:
            errors.append("full_payment must be a single payment")
    return errors


def _check_installments(
    output: AgentOutput, options: list[PaymentOption], payments: list[tuple[date, float]]
) -> list[str]:
    if output.recommended_payment_method is not PaymentMethod.INSTALLMENTS:
        return []
    for option in options:
        if option.payment_method != "installments":
            continue
        expected = [
            (when, round(amount, 2)) for when, amount in option.schedule()
        ]
        actual = [(when, round(amount, 2)) for when, amount in payments]
        if expected == actual:
            return []
    return ["installment plan does not match any supplied payment option"]


def _check_partial(
    output: AgentOutput, request: RequestRow, payments: list[tuple[date, float]]
) -> list[str]:
    if output.recommended_payment_method is not PaymentMethod.PARTIAL_PAYMENT:
        return []
    errors: list[str] = []
    if not request.allows_partial_payment:
        errors.append("partial_payment used where the request forbids it")
    if output.affordability_status is not AffordabilityStatus.AFFORDABLE_WITH_PLAN:
        errors.append("partial_payment requires affordable_with_plan")
    if len(payments) != 2:
        return errors + ["partial_payment requires exactly two payments"]

    if abs(sum(amount for _, amount in payments) - request.requested_amount) > CENT:
        errors.append("partial_payment total does not equal requested_amount")
    if abs(payments[0][1] - output.amount_safe_to_pay) > CENT:
        errors.append("first partial payment must equal amount_safe_to_pay")
    if payments[0][0] != request.request_date:
        errors.append("first partial payment must fall on request_date")
    if not 0 < output.amount_safe_to_pay < request.requested_amount:
        errors.append("partial_payment needs 0 < amount_safe_to_pay < requested_amount")

    earliest = output.earliest_date_for_full_payment.strip()
    if earliest and payments[1][0] != date.fromisoformat(earliest):
        errors.append("second partial payment must fall on earliest_date_for_full_payment")
    if payments[1][0] > request.desired_completion_date:
        errors.append("partial_payment completes after desired_completion_date")
    return errors


def _check_spending_changes(
    output: AgentOutput, profile: FinancialProfile, events: list[FinancialEvent]
) -> list[str]:
    raw = output.spending_changes_needed.strip()
    if raw == "none" or not raw:
        return []

    by_id = {event.event_id: event for event in events}
    errors: list[str] = []
    seen: set[str] = set()
    parts = raw.split("|")
    if len(parts) > 3:
        errors.append("more than three spending changes")

    for part in parts:
        fields = part.split(":")
        if fields[0] == "stop" and len(fields) == 2:
            event_id, new_amount = fields[1], None
        elif fields[0] == "reduce_to" and len(fields) == 3:
            event_id = fields[1]
            try:
                new_amount = float(fields[2])
            except ValueError:
                errors.append(f"reduce_to amount is not numeric in {part!r}")
                continue
        else:
            errors.append(f"malformed spending change {part!r}")
            continue

        if event_id in seen:
            errors.append(f"{event_id} is changed more than once")
        seen.add(event_id)

        event = by_id.get(event_id)
        if event is None:
            errors.append(f"{event_id} is not one of this user's events")
            continue
        if profile.is_protected(event.category):
            errors.append(f"{event_id} is in a protected category ({event.category})")
        if new_amount is None:
            if not (event.can_stop and profile.may_stop(event.category)):
                errors.append(f"{event_id} may not be stopped")
        else:
            if not (event.can_reduce and profile.may_reduce(event.category)):
                errors.append(f"{event_id} may not be reduced")
            floor = event.minimum_allowed_amount
            if floor is not None and new_amount < floor - CENT:
                errors.append(f"{event_id} reduced below minimum_allowed_amount {floor}")
            if event.amount is not None and new_amount > event.amount + CENT:
                errors.append(f"{event_id} 'reduced' to more than its current amount")
    return errors


def _check_safety(
    output: AgentOutput,
    profile: FinancialProfile,
    model: ForecastModel,
    payments: list[tuple[date, float]],
) -> list[str]:
    """Re-simulate the recommended plan rather than trusting the agent."""
    if not payments:
        return []
    changes = _rebuild_changes(output.spending_changes_needed)
    flows = [
        CashFlow(on=when, amount=-amount, label="recommended payment", sequence=1)
        for when, amount in payments
    ]
    if not model.is_safe_with(flows, changes):
        lowest, _ = model.simulate(changes, extra=flows)
        return [
            f"plan breaches minimum balance: lowest projected {lowest:.2f} "
            f"< floor {profile.minimum_balance_to_keep:.2f}"
        ]
    return []


def _rebuild_changes(raw: str):
    from validators.schemas import SpendingChange

    raw = raw.strip()
    if raw in ("", "none"):
        return []
    changes = []
    for part in raw.split("|"):
        fields = part.split(":")
        if fields[0] == "stop" and len(fields) == 2:
            changes.append(SpendingChange(change_type="stop", event_id=fields[1]))
        elif fields[0] == "reduce_to" and len(fields) == 3:
            try:
                changes.append(
                    SpendingChange(
                        change_type="reduce_to",
                        event_id=fields[1],
                        new_amount=float(fields[2]),
                    )
                )
            except ValueError:
                continue
    return changes
