"""
profile.py — FinancialProfile domain model.

Parses a row from dataset/financial_profiles.csv.

CSV columns:
    user_id, home_currency, current_available_balance,
    minimum_balance_to_keep, financial_priorities,
    expense_categories_to_protect,
    expense_categories_user_is_willing_to_reduce,
    expense_categories_user_is_willing_to_stop,
    payment_methods_user_will_consider, max_installment_months

Pipe-delimited list fields (e.g. "education|debt_repayment") are parsed
into Python lists automatically by the Pydantic validator.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import PaymentMethod


def _split_pipe(v: str | list) -> list[str]:
    """Parse a pipe-delimited CSV cell into a list, stripping whitespace."""
    if isinstance(v, list):
        return v
    if not v or str(v).strip() == "":
        return []
    return [item.strip() for item in str(v).split("|") if item.strip()]


class FinancialProfile(BaseModel):
    """Strongly-typed representation of one row in financial_profiles.csv."""

    model_config = {"frozen": True, "str_strip_whitespace": True}

    user_id: str

    home_currency: str = Field(min_length=3, max_length=3)

    current_available_balance: Decimal = Field(
        description="Current liquid cash balance in home_currency."
    )

    minimum_balance_to_keep: Decimal = Field(
        ge=Decimal("0"),
        description="The minimum balance the user wants maintained at all times.",
    )

    financial_priorities: List[str] = Field(default_factory=list)
    expense_categories_to_protect: List[str] = Field(default_factory=list)
    expense_categories_user_is_willing_to_reduce: List[str] = Field(
        default_factory=list
    )
    expense_categories_user_is_willing_to_stop: List[str] = Field(
        default_factory=list
    )

    payment_methods_user_will_consider: List[PaymentMethod] = Field(
        default_factory=list,
        description="Subset of PaymentMethod the user is open to.",
    )

    max_installment_months: Optional[int] = Field(
        default=None,
        ge=1,
        description="None means the user will not consider installments.",
    )

    # ── Pipe-list validators ────────────────────────────────────────────────
    @field_validator(
        "financial_priorities",
        "expense_categories_to_protect",
        "expense_categories_user_is_willing_to_reduce",
        "expense_categories_user_is_willing_to_stop",
        mode="before",
    )
    @classmethod
    def parse_pipe_list(cls, v: object) -> list[str]:
        return _split_pipe(str(v) if v is not None else "")

    @field_validator("payment_methods_user_will_consider", mode="before")
    @classmethod
    def parse_payment_methods(cls, v: object) -> list[str]:
        return _split_pipe(str(v) if v is not None else "")

    @field_validator("max_installment_months", mode="before")
    @classmethod
    def parse_optional_int(cls, v: object) -> Optional[int]:
        if v is None or str(v).strip() == "":
            return None
        return int(v)

    @field_validator("current_available_balance", "minimum_balance_to_keep", mode="before")
    @classmethod
    def parse_decimal(cls, v: object) -> Decimal:
        return Decimal(str(v).strip())

    # ── Convenience helpers ─────────────────────────────────────────────────
    def considers_installments(self) -> bool:
        return PaymentMethod.INSTALLMENTS in self.payment_methods_user_will_consider

    def considers_partial_payment(self) -> bool:
        return PaymentMethod.PARTIAL_PAYMENT in self.payment_methods_user_will_consider

    def considers_full_payment(self) -> bool:
        return PaymentMethod.FULL_PAYMENT in self.payment_methods_user_will_consider

    def is_category_protected(self, category: str) -> bool:
        return category in self.expense_categories_to_protect

    def is_category_reducible(self, category: str) -> bool:
        return category in self.expense_categories_user_is_willing_to_reduce

    def is_category_stoppable(self, category: str) -> bool:
        return category in self.expense_categories_user_is_willing_to_stop
