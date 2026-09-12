"""
plan.py — PaymentPlan and SpendingChange value objects.

These are intermediate solver artifacts, not directly sourced from CSVs.
They are constructed by the solver and ultimately serialized into output.csv.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class SpendingChange(BaseModel):
    """
    One spending-reduction action the solver recommends.

    Format in output.csv:
        stop:<event_id>
        reduce_to:<event_id>:<new_amount>
    """

    model_config = {"frozen": True}

    action: str = Field(
        description="'stop' or 'reduce_to'",
        pattern=r"^(stop|reduce_to)$",
    )
    event_id: str
    new_amount: Optional[Decimal] = Field(
        default=None,
        description="Required when action == 'reduce_to'.",
    )

    @model_validator(mode="after")
    def validate_reduce_to(self) -> "SpendingChange":
        if self.action == "reduce_to" and self.new_amount is None:
            raise ValueError("new_amount is required when action is 'reduce_to'")
        return self

    def to_csv_token(self) -> str:
        """Serialize to the pipe-separated token used in spending_changes_needed."""
        if self.action == "stop":
            return f"stop:{self.event_id}"
        amt = self.new_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"reduce_to:{self.event_id}:{amt}"


class PaymentPlan(BaseModel):
    """
    A complete recommended payment plan produced by the solver.

    schedule: list of (date, amount) payments in chronological order.
    """

    model_config = {"frozen": True}

    schedule: List[tuple[date, Decimal]] = Field(default_factory=list)
    spending_changes: List[SpendingChange] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return len(self.schedule) == 0

    @property
    def total_payable(self) -> Decimal:
        return sum((amt for _, amt in self.schedule), Decimal("0"))

    @property
    def first_payment_date(self) -> Optional[date]:
        return self.schedule[0][0] if self.schedule else None

    @property
    def last_payment_date(self) -> Optional[date]:
        return self.schedule[-1][0] if self.schedule else None

    @property
    def num_payments(self) -> int:
        return len(self.schedule)

    def to_payment_plan_str(self) -> str:
        """Serialize to pipe-delimited YYYY-MM-DD:amount format, or 'none'."""
        if not self.schedule:
            return "none"
        tokens = []
        for d, amt in self.schedule:
            rounded = amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tokens.append(f"{d.isoformat()}:{rounded}")
        return "|".join(tokens)

    def to_spending_changes_str(self) -> str:
        """Serialize spending changes to pipe-delimited string, or 'none'."""
        if not self.spending_changes:
            return "none"
        return "|".join(sc.to_csv_token() for sc in self.spending_changes)
