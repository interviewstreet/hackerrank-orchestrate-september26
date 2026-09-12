"""
output.py — OutputRecord domain model.

Represents one row in dataset/output.csv. Produced by the solver/explainer
and serialized by to_csv_row().

Required output columns (in exact order per §6.2):
    request_id, amount_safe_to_pay, affordability_status,
    recommended_payment_method, payment_plan,
    earliest_date_for_full_payment, spending_changes_needed,
    decision_explanation
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from pydantic import BaseModel, Field

from .enums import AffordabilityStatus, PaymentMethod

# Exact column order required by the submission contract.
OUTPUT_COLUMNS: List[str] = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


class OutputRecord(BaseModel):
    """One prediction row for output.csv."""

    model_config = {"frozen": False}  # mutable so explainer can fill in explanation

    request_id: str

    amount_safe_to_pay: Decimal = Field(
        ge=Decimal("0"),
        description="Max safe payment on request_date, before any spending changes.",
    )

    affordability_status: AffordabilityStatus

    recommended_payment_method: PaymentMethod

    payment_plan: str = Field(
        description="Pipe-delimited YYYY-MM-DD:amount entries, or 'none'.",
    )

    earliest_date_for_full_payment: Optional[date] = Field(
        default=None,
        description="First date a safe full payment is possible. Empty if never.",
    )

    spending_changes_needed: str = Field(
        default="none",
        description="Pipe-delimited stop/reduce_to actions, or 'none'.",
    )

    decision_explanation: str = ""

    # ── Serialization ───────────────────────────────────────────────────────
    def to_csv_row(self) -> dict[str, str]:
        """Return an ordered dict suitable for csv.DictWriter."""
        rounded_amount = self.amount_safe_to_pay.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        earliest = (
            self.earliest_date_for_full_payment.isoformat()
            if self.earliest_date_for_full_payment is not None
            else ""
        )
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": str(rounded_amount),
            "affordability_status": self.affordability_status.value,
            "recommended_payment_method": self.recommended_payment_method.value,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": earliest,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }
