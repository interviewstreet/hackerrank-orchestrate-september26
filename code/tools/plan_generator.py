"""Generate every candidate payment plan, verify safety, and rank them.

Eligibility comes from the user's stated preferences; safety comes from
re-simulating the plan's payments against the 90-day forecast. Ranking follows
the spec's tie-break order exactly:

1. completes the full request by ``desired_completion_date``
2. requires no spending changes
3. minimises the total amount paid
4. starts payment earlier
5. uses fewer payments
6. lowest ``payment_option_id``
"""

from __future__ import annotations

from datetime import date

from tools.balance_forecaster import ForecastModel
from validators.schemas import (
    AffordabilityStatus,
    CandidatePlan,
    CashFlow,
    FinancialProfile,
    PaymentMethod,
    PaymentOption,
    PaymentPlanEntry,
    RequestRow,
    SpendingChange,
)


class PlanGenerator:
    """Builds and ranks the candidate plans for one request."""

    def __init__(
        self,
        request: RequestRow,
        profile: FinancialProfile,
        options: list[PaymentOption],
        model: ForecastModel,
    ) -> None:
        self.request = request
        self.profile = profile
        self.options = options
        self.model = model

    # ---- candidate construction -------------------------------------------

    def candidates(
        self,
        amount_safe_today: float,
        earliest_full: date | None,
        spending_changes: list[SpendingChange] | None = None,
    ) -> list[CandidatePlan]:
        changes = spending_changes or []
        out: list[CandidatePlan] = []

        full = self._full_payment(changes)
        if full is not None:
            out.append(full)

        out.extend(self._installment_plans(changes))

        partial = self._partial_payment(amount_safe_today, earliest_full, changes)
        if partial is not None:
            out.append(partial)

        # `wait` means "the same full payment, just later" -- it is a statement
        # about time, not about cutting spending. Offering it alongside spending
        # changes produced plans whose payment date came from the changed
        # forecast while the reported earliest date (which must exclude optional
        # changes) stayed empty, leaving the two contradicting each other.
        if not changes:
            waiting = self._wait(earliest_full)
            if waiting is not None:
                out.append(waiting)

        return [plan for plan in out if plan.is_safe]

    def _full_payment(self, changes: list[SpendingChange]) -> CandidatePlan | None:
        if not self.profile.accepts(PaymentMethod.FULL_PAYMENT):
            return None
        when = self.request.request_date
        total = self.request.requested_amount
        return CandidatePlan(
            method=PaymentMethod.FULL_PAYMENT,
            payments=[PaymentPlanEntry(payment_date=when, amount=total)],
            total_cost=total,
            payment_option_id=self._option_id_for_full_payment(),
            spending_changes=list(changes),
            completes_by_deadline=when <= self.request.desired_completion_date,
            completes_request=True,
            is_safe=self.model.is_safe_with(
                [CashFlow(on=when, amount=-total, label="full payment", sequence=1)],
                changes,
            ),
        )

    def _installment_plans(self, changes: list[SpendingChange]) -> list[CandidatePlan]:
        if not self.profile.accepts(PaymentMethod.INSTALLMENTS):
            return []
        # A blank max_installment_months means the user will not consider them.
        cap = self.profile.max_installment_months
        if cap is None:
            return []

        plans: list[CandidatePlan] = []
        for option in self.options:
            if option.payment_method != "installments":
                continue
            if option.months_span > cap:
                continue
            schedule = option.schedule()
            payments = [
                PaymentPlanEntry(payment_date=when, amount=amount)
                for when, amount in schedule
            ]
            flows = [
                CashFlow(
                    on=when,
                    amount=-amount,
                    label=f"installment {option.payment_option_id}",
                    sequence=1,
                )
                for when, amount in schedule
            ]
            plans.append(
                CandidatePlan(
                    method=PaymentMethod.INSTALLMENTS,
                    payments=payments,
                    total_cost=option.total_payable_amount,
                    payment_option_id=option.payment_option_id,
                    spending_changes=list(changes),
                    completes_by_deadline=(
                        payments[-1].payment_date <= self.request.desired_completion_date
                    ),
                    completes_request=True,
                    is_safe=self.model.is_safe_with(flows, changes),
                )
            )
        return plans

    def _partial_payment(
        self,
        amount_safe_today: float,
        earliest_full: date | None,
        changes: list[SpendingChange],
    ) -> CandidatePlan | None:
        """Pay what is safe today, settle the remainder on the earliest safe date."""
        if not self.request.allows_partial_payment:
            return None
        if not self.profile.accepts(PaymentMethod.PARTIAL_PAYMENT):
            return None
        total = self.request.requested_amount
        first = round(amount_safe_today, 2)
        if not 0 < first < total:
            return None
        if earliest_full is None or earliest_full > self.request.desired_completion_date:
            return None
        if earliest_full <= self.request.request_date:
            return None

        remainder = round(total - first, 2)
        flows = [
            CashFlow(
                on=self.request.request_date,
                amount=-first,
                label="partial payment 1",
                sequence=1,
            ),
            CashFlow(on=earliest_full, amount=-remainder, label="partial payment 2", sequence=1),
        ]
        return CandidatePlan(
            method=PaymentMethod.PARTIAL_PAYMENT,
            payments=[
                PaymentPlanEntry(payment_date=self.request.request_date, amount=first),
                PaymentPlanEntry(payment_date=earliest_full, amount=remainder),
            ],
            total_cost=total,
            spending_changes=list(changes),
            completes_by_deadline=earliest_full <= self.request.desired_completion_date,
            completes_request=True,
            is_safe=self.model.is_safe_with(flows, changes),
        )

    def _wait(self, earliest_full: date | None) -> CandidatePlan | None:
        """Pay the full amount later, once it becomes safe without any changes."""
        if not self.profile.accepts(PaymentMethod.FULL_PAYMENT):
            return None
        if earliest_full is None or earliest_full <= self.request.request_date:
            return None
        total = self.request.requested_amount
        return CandidatePlan(
            method=PaymentMethod.WAIT,
            payments=[PaymentPlanEntry(payment_date=earliest_full, amount=total)],
            total_cost=total,
            completes_by_deadline=earliest_full <= self.request.desired_completion_date,
            completes_request=True,
            is_safe=self.model.is_safe_with(
                [CashFlow(on=earliest_full, amount=-total, label="deferred full", sequence=1)]
            ),
        )

    def _option_id_for_full_payment(self) -> str | None:
        for option in self.options:
            if option.payment_method == "full_payment":
                return option.payment_option_id
        return None

    # ---- ranking -----------------------------------------------------------

    def rank(self, plans: list[CandidatePlan]) -> CandidatePlan | None:
        """Best plan under the spec's ordered preferences."""
        if not plans:
            return None
        return sorted(plans, key=self._sort_key)[0]

    def _sort_key(self, plan: CandidatePlan) -> tuple:
        first_payment = (
            plan.payments[0].payment_date if plan.payments else date.max
        )
        return (
            not plan.completes_by_deadline,          # completing by deadline wins
            len(plan.spending_changes) > 0,           # no spending changes next
            round(plan.total_cost, 2),                # cheapest total
            first_payment,                            # start earlier
            len(plan.payments),                       # fewer payments
            plan.payment_option_id or "",             # lowest option id
        )


def classify(
    plan: CandidatePlan | None,
    request: RequestRow,
    profile: FinancialProfile,
    earliest_full: date | None,
) -> AffordabilityStatus:
    """Map the chosen plan onto an affordability status."""
    if plan is None:
        # Capacity may still arrive later even when no plan is eligible now.
        if earliest_full is not None and earliest_full > request.request_date:
            return AffordabilityStatus.AFFORDABLE_LATER
        return AffordabilityStatus.NOT_AFFORDABLE

    if plan.method is PaymentMethod.FULL_PAYMENT:
        if plan.payments[0].payment_date == request.request_date and not plan.spending_changes:
            return AffordabilityStatus.AFFORDABLE_NOW
        return AffordabilityStatus.AFFORDABLE_WITH_PLAN
    if plan.method is PaymentMethod.WAIT:
        return AffordabilityStatus.AFFORDABLE_LATER
    return AffordabilityStatus.AFFORDABLE_WITH_PLAN
