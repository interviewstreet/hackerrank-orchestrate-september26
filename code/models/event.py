"""
event.py — FinancialEvent domain model.

Parses a row from dataset/financial_events.csv.

CSV columns:
    event_id, user_id, event_type, description, category,
    direction, amount, currency, event_date, settlement_date,
    status, linked_event_id, flexibility, minimum_allowed_amount

Key rules (from §6.3):
- pending debits: reserved immediately.
- pending credits / unrealized gains: excluded from cash.
- settled events take precedence over estimates.
- amount may be blank (to be filled from images.csv + OCR).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import EventDirection, EventStatus, EventType, Flexibility


class FinancialEvent(BaseModel):
    """Strongly-typed representation of one row in financial_events.csv."""

    model_config = {"frozen": True, "str_strip_whitespace": True}

    event_id: str
    user_id: str

    event_type: EventType = EventType.OTHER
    description: str = ""
    category: str = ""

    direction: EventDirection
    amount: Optional[Decimal] = Field(
        default=None,
        description="May be None if amount is missing and must be filled via OCR.",
    )
    currency: str = Field(min_length=3, max_length=3)

    event_date: date
    settlement_date: date

    status: EventStatus
    linked_event_id: Optional[str] = None
    flexibility: Flexibility = Flexibility.FIXED
    minimum_allowed_amount: Optional[Decimal] = None

    # ── Validators ──────────────────────────────────────────────────────────
    @field_validator("event_type", mode="before")
    @classmethod
    def parse_event_type(cls, v: object) -> EventType:
        try:
            return EventType(str(v).strip().lower())
        except ValueError:
            return EventType.OTHER

    @field_validator("direction", mode="before")
    @classmethod
    def parse_direction(cls, v: object) -> EventDirection:
        return EventDirection(str(v).strip().lower())

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, v: object) -> EventStatus:
        return EventStatus(str(v).strip().lower())

    @field_validator("flexibility", mode="before")
    @classmethod
    def parse_flexibility(cls, v: object) -> Flexibility:
        raw = str(v).strip().lower() if v else "fixed"
        return Flexibility(raw) if raw else Flexibility.FIXED

    @field_validator("amount", "minimum_allowed_amount", mode="before")
    @classmethod
    def parse_optional_decimal(cls, v: object) -> Optional[Decimal]:
        if v is None or str(v).strip() == "":
            return None
        return Decimal(str(v).strip())

    @field_validator("event_date", "settlement_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date:
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v).strip())

    @field_validator("linked_event_id", mode="before")
    @classmethod
    def parse_optional_str(cls, v: object) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()

    # ── Cash-flow helpers ───────────────────────────────────────────────────
    @property
    def is_debit(self) -> bool:
        return self.direction == EventDirection.DEBIT

    @property
    def is_credit(self) -> bool:
        return self.direction == EventDirection.CREDIT

    @property
    def counts_as_cash_outflow(self) -> bool:
        """Pending and settled debits reduce available cash.
        Cancelled / failed debits do not.
        """
        return self.is_debit and self.status in (
            EventStatus.SETTLED,
            EventStatus.PENDING,
            EventStatus.SCHEDULED,
        )

    @property
    def counts_as_confirmed_inflow(self) -> bool:
        """Only settled credits count as confirmed cash. Pending/unrealized excluded."""
        return self.is_credit and self.status == EventStatus.SETTLED

    @property
    def is_excluded_inflow(self) -> bool:
        """Pending credits, bonuses, commissions, unrealized — excluded per §6.3."""
        return self.is_credit and self.status in (
            EventStatus.PENDING,
            EventStatus.UNREALIZED,
            EventStatus.SCHEDULED,
        )

    def signed_amount_home(self, home_amount: Decimal) -> Decimal:
        """Return +/- home-currency amount suitable for balance arithmetic."""
        return -home_amount if self.is_debit else home_amount
