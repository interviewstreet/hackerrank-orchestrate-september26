"""
payment_option.py — SellerPaymentOption domain model.

Parses a row from dataset/request_payment_options.csv.

CSV columns:
    payment_option_id, request_id, payment_method,
    payment_amount, number_of_payments, first_payment_date,
    payment_frequency_days, financing_fee, total_payable_amount

Each request has 2–4 payment options. An option may be rejected if it
conflicts with the user's preferences or max_installment_months.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import PaymentMethod


class SellerPaymentOption(BaseModel):
    """Strongly-typed representation of one row in request_payment_options.csv."""

    model_config = {"frozen": True, "str_strip_whitespace": True}

    payment_option_id: str
    request_id: str

    payment_method: PaymentMethod

    payment_amount: Decimal = Field(
        gt=Decimal("0"),
        description="Amount per payment instalment (or full amount for full_payment).",
    )
    number_of_payments: int = Field(ge=1)

    first_payment_date: date

    payment_frequency_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Days between instalments. None for single-payment options.",
    )

    financing_fee: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Total financing/interest fee added on top of the principal.",
    )

    total_payable_amount: Decimal = Field(
        gt=Decimal("0"),
        description="payment_amount × number_of_payments + financing_fee.",
    )

    # ── Validators ──────────────────────────────────────────────────────────
    @field_validator("payment_method", mode="before")
    @classmethod
    def parse_payment_method(cls, v: object) -> PaymentMethod:
        return PaymentMethod(str(v).strip().lower())

    @field_validator(
        "payment_amount",
        "financing_fee",
        "total_payable_amount",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, v: object) -> Decimal:
        if v is None or str(v).strip() == "":
            return Decimal("0")
        return Decimal(str(v).strip())

    @field_validator("first_payment_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date:
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v).strip())

    @field_validator("payment_frequency_days", mode="before")
    @classmethod
    def parse_optional_int(cls, v: object) -> Optional[int]:
        if v is None or str(v).strip() == "":
            return None
        return int(str(v).strip())

    # ── Helpers ─────────────────────────────────────────────────────────────
    def get_payment_schedule(self) -> List[tuple[date, Decimal]]:
        """Return a chronological list of (payment_date, amount) tuples."""
        schedule: List[tuple[date, Decimal]] = []
        current_date = self.first_payment_date
        freq = self.payment_frequency_days or 0
        for i in range(self.number_of_payments):
            schedule.append((current_date, self.payment_amount))
            if freq > 0:
                current_date = current_date + timedelta(days=freq)
        return schedule

    def installment_months(self) -> int:
        """Approximate number of months covered by the instalment plan."""
        if self.number_of_payments <= 1:
            return 1
        total_days = (self.payment_frequency_days or 30) * (self.number_of_payments - 1)
        return max(1, round(total_days / 30))

    def is_compatible_with_profile(
        self,
        user_methods: list[PaymentMethod],
        max_installment_months: Optional[int],
    ) -> bool:
        """Return True if this option fits the user's payment preferences."""
        if self.payment_method not in user_methods:
            return False
        if self.payment_method == PaymentMethod.INSTALLMENTS and max_installment_months is not None:
            if self.installment_months() > max_installment_months:
                return False
        return True
