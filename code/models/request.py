"""
request.py — EvaluationRequest domain model.

Parses a row from dataset/requests.csv.

CSV columns:
    request_id, user_id, request_date, request_type,
    requested_amount, desired_completion_date,
    allows_partial_payment, request_text
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class EvaluationRequest(BaseModel):
    """Strongly-typed representation of one row in requests.csv."""

    model_config = {"frozen": True, "str_strip_whitespace": True}

    request_id: str
    user_id: str

    request_date: date
    request_type: str

    requested_amount: Decimal = Field(
        gt=Decimal("0"),
        description="Total amount the user wants to pay, in the user's home currency.",
    )

    desired_completion_date: date = Field(
        description="Deadline by which the user wants the full payment completed."
    )

    allows_partial_payment: bool = Field(
        description="Whether the seller/provider accepts a partial upfront payment."
    )

    request_text: str = ""

    # ── Validators ──────────────────────────────────────────────────────────
    @field_validator("request_date", "desired_completion_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date:
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v).strip())

    @field_validator("requested_amount", mode="before")
    @classmethod
    def parse_decimal(cls, v: object) -> Decimal:
        return Decimal(str(v).strip())

    @field_validator("allows_partial_payment", mode="before")
    @classmethod
    def parse_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def days_until_deadline(self) -> int:
        """Calendar days from request_date to desired_completion_date."""
        return (self.desired_completion_date - self.request_date).days
