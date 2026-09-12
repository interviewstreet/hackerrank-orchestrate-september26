"""Dataclass models for payment-plan candidates and the final in-memory decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Payment:
    pay_date: date
    amount: float


@dataclass(frozen=True)
class SpendingChange:
    action: str  # "stop" or "reduce"
    event_id: str
    new_amount: float | None = None

    def to_output(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{_format_money(self.new_amount or 0.0)}"


@dataclass
class CandidatePlan:
    method: str
    payments: list[Payment]
    spending_changes: list[SpendingChange] = field(default_factory=list)
    payment_option_id: str | None = None
    total_paid: float = 0.0
    meets_deadline: bool = False
    is_safe: bool = False
    eligible: bool = False
    notes: str = ""

    @property
    def start_date(self) -> date | None:
        if not self.payments:
            return None
        return min(payment.pay_date for payment in self.payments)

    @property
    def last_date(self) -> date | None:
        if not self.payments:
            return None
        return max(payment.pay_date for payment in self.payments)

    @property
    def payment_count(self) -> int:
        return len(self.payments)


@dataclass
class Decision:
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str
    selected_plan: CandidatePlan | None = None
    candidates: list[CandidatePlan] = field(default_factory=list)


def _format_money(amount: float) -> str:
    rounded = round(float(amount) + 1e-9, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.2f}"


def format_payment_plan(payments: list[Payment]) -> str:
    if not payments:
        return "none"
    ordered = sorted(payments, key=lambda payment: (payment.pay_date, payment.amount))
    return "|".join(
        f"{payment.pay_date.isoformat()}:{_format_money(payment.amount)}"
        for payment in ordered
    )


def format_spending_changes(changes: list[SpendingChange]) -> str:
    if not changes:
        return "none"
    return "|".join(change.to_output() for change in changes[:3])


def option_id_sort_key(payment_option_id: str | None) -> tuple[int, str]:
    """Lower numeric IDs rank better. Missing IDs lose the final tie-break."""
    if not payment_option_id:
        return (10**12, "")
    digits = "".join(ch for ch in payment_option_id if ch.isdigit())
    if digits:
        return (int(digits), payment_option_id)
    return (10**12, payment_option_id)
