"""
plan_ranking.py

Builds every eligible candidate plan (full_payment, partial_payment,
installments, wait, not_recommended) for a request, then ranks them using
the exact tie-break order from problem_statement.md:

  1. Completes the full request by desired_completion_date
  2. Requires no spending changes
  3. Minimizes the total amount paid
  4. Starts payment earlier
  5. Uses fewer payments
  6. Lowest payment_option_id as final tie-breaker
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from forecast import is_schedule_safe
from state_reconstruction import ForwardEvent
from utils import days_between, format_amount, parse_date, safe_float


@dataclass
class CandidatePlan:
    method: str  # full_payment | partial_payment | installments | wait | not_recommended
    affordability_status: str
    payments: list[tuple[str, float]] = field(default_factory=list)  # [(date, amount), ...]
    spending_changes: list[str] = field(default_factory=list)  # e.g. ["stop:event_14"]
    total_paid: float = 0.0
    start_date: str = "9999-99-99"
    num_payments: int = 0
    payment_option_id: str = "zzzz"  # sorts last if absent
    completes_by_deadline: bool = False
    explanation: str = ""

    def payment_plan_str(self) -> str:
        if not self.payments:
            return "none"
        return "|".join(f"{d}:{format_amount(a)}" for d, a in self.payments)

    def spending_changes_str(self) -> str:
        if not self.spending_changes:
            return "none"
        return "|".join(self.spending_changes[:3])


def build_full_payment_plan(
    request: dict, accepted_methods: set[str], safe_amount: float,
) -> Optional[CandidatePlan]:
    if "full_payment" not in accepted_methods:
        return None
    requested_amount = safe_float(request["requested_amount"], 0.0)
    if safe_amount < requested_amount:
        return None  # not safe today for the full amount

    request_date = request["request_date"]
    return CandidatePlan(
        method="full_payment",
        affordability_status="affordable_now",
        payments=[(request_date, requested_amount)],
        total_paid=requested_amount,
        start_date=request_date,
        num_payments=1,
        completes_by_deadline=request_date <= request["desired_completion_date"],
        explanation=f"Full amount of {requested_amount} is safe to pay on {request_date} "
                    f"without breaching the minimum balance over the 90-day forecast.",
    )


def build_wait_plan(
    request: dict, accepted_methods: set[str], earliest_full_date: Optional[str],
) -> Optional[CandidatePlan]:
    if "full_payment" not in accepted_methods or earliest_full_date is None:
        return None
    if earliest_full_date > request["desired_completion_date"]:
        return None

    requested_amount = safe_float(request["requested_amount"], 0.0)
    return CandidatePlan(
        method="wait",
        affordability_status="affordable_later",
        payments=[(earliest_full_date, requested_amount)],
        total_paid=requested_amount,
        start_date=earliest_full_date,
        num_payments=1,
        completes_by_deadline=earliest_full_date <= request["desired_completion_date"],
        explanation=f"Full amount becomes safe to pay on {earliest_full_date}, "
                    f"on or before the desired completion date.",
    )


def build_partial_payment_plan(
    request: dict, accepted_methods: set[str], safe_amount: float,
    earliest_full_date: Optional[str],
) -> Optional[CandidatePlan]:
    if request.get("allows_partial_payment", "").strip().lower() != "true":
        return None
    if "partial_payment" not in accepted_methods:
        return None

    requested_amount = safe_float(request["requested_amount"], 0.0)
    if not (0 < safe_amount < requested_amount):
        return None
    if earliest_full_date is None or earliest_full_date > request["desired_completion_date"]:
        return None

    request_date = request["request_date"]
    remainder = round(requested_amount - safe_amount, 2)
    return CandidatePlan(
        method="partial_payment",
        affordability_status="affordable_with_plan",
        payments=[(request_date, round(safe_amount, 2)), (earliest_full_date, remainder)],
        total_paid=requested_amount,
        start_date=request_date,
        num_payments=2,
        completes_by_deadline=True,
        explanation=f"Pay {round(safe_amount, 2)} on {request_date}, "
                    f"remaining {remainder} on {earliest_full_date}.",
    )


def build_installment_plans(
    request: dict, accepted_methods: set[str], payment_options: list[dict],
    start_balance: float, events: list[ForwardEvent], minimum_balance_to_keep: float,
) -> list[CandidatePlan]:
    if "installments" not in accepted_methods:
        return []

    plans: list[CandidatePlan] = []
    for opt in payment_options:
        if opt.get("payment_method", "").strip().lower() != "installments":
            continue

        payment_amount = safe_float(opt.get("payment_amount"))
        number_of_payments = int(safe_float(opt.get("number_of_payments"), 0) or 0)
        first_date = opt.get("first_payment_date")
        frequency_days = int(safe_float(opt.get("payment_frequency_days"), 0) or 0)
        total_payable = safe_float(opt.get("total_payable_amount"), 0.0)

        if not (payment_amount and number_of_payments and first_date):
            continue

        payments = []
        current = parse_date(first_date)
        for i in range(number_of_payments):
            payments.append((current.strftime("%Y-%m-%d"), payment_amount))
            from datetime import timedelta
            current = current + timedelta(days=frequency_days)

        if not is_schedule_safe(start_balance, events, request["request_date"],
                                 minimum_balance_to_keep, payments):
            continue

        last_payment_date = payments[-1][0]
        plans.append(CandidatePlan(
            method="installments",
            affordability_status="affordable_with_plan",
            payments=payments,
            total_paid=total_payable or sum(p[1] for p in payments),
            start_date=payments[0][0],
            num_payments=len(payments),
            payment_option_id=opt.get("payment_option_id", "zzzz"),
            completes_by_deadline=last_payment_date <= request["desired_completion_date"],
            explanation=f"Installment plan {opt.get('payment_option_id')}: "
                        f"{number_of_payments} payments of {payment_amount} "
                        f"every {frequency_days} days, verified safe over the forecast.",
        ))

    return plans


def build_candidate_plans(
    request: dict, profile: dict, payment_options: list[dict],
    safe_amount: float, earliest_full_date: Optional[str],
    start_balance: float, events: list[ForwardEvent],
) -> list[CandidatePlan]:
    accepted_methods = {
        m.strip() for m in profile.get("payment_methods_user_will_consider", "").split("|") if m.strip()
    }
    minimum_balance_to_keep = safe_float(profile.get("minimum_balance_to_keep"), 0.0)

    plans: list[CandidatePlan] = []

    full = build_full_payment_plan(request, accepted_methods, safe_amount)
    if full:
        plans.append(full)

    partial = build_partial_payment_plan(request, accepted_methods, safe_amount, earliest_full_date)
    if partial:
        plans.append(partial)

    plans.extend(build_installment_plans(
        request, accepted_methods, payment_options, start_balance, events, minimum_balance_to_keep
    ))

    wait = build_wait_plan(request, accepted_methods, earliest_full_date)
    if wait:
        plans.append(wait)

    if not plans:
        plans.append(CandidatePlan(
            method="not_recommended",
            affordability_status="not_affordable",
            explanation="No safe, user-accepted payment plan exists within the 90-day forecast.",
        ))

    return plans


def rank_plans(plans: list[CandidatePlan]) -> CandidatePlan:
    """Apply the exact 6-rule tie-break order from the spec."""
    def sort_key(p: CandidatePlan):
        return (
            0 if p.completes_by_deadline else 1,
            0 if not p.spending_changes else 1,
            p.total_paid,
            p.start_date,
            p.num_payments,
            p.payment_option_id,
        )

    return sorted(plans, key=sort_key)[0]