"""Dataclasses and Pydantic models for financial plans, decisions, and evidence extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Core Dataclasses for Plans and Decisions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pydantic Schemas for AI Evidence Extraction
# ---------------------------------------------------------------------------

class ImageEvidence(BaseModel):
    image_id: str = Field(..., description="ID of the image, e.g., image_01")
    event_id: str = Field(..., description="ID of the related financial event, e.g., event_253")
    amount: float | None = Field(
        None,
        description="The exact monetary amount shown in the document. None if not legible."
    )
    currency: str | None = Field(
        None,
        description="Currency code such as IDR, INR, USD, EUR, etc."
    )
    date: str | None = Field(
        None,
        description="Date in YYYY-MM-DD format if visible on the document, or None."
    )
    document_type: str = Field(
        "receipt",
        description="Type of document, e.g., payslip, invoice, bill, receipt, ticket"
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0"
    )
    notes: str = Field(
        "",
        description="Brief factual notes describing how the amount was identified"
    )


class MessageEvidenceItem(BaseModel):
    message_id: str = Field(..., description="ID of the message, e.g., message_01")
    user_id: str = Field(..., description="User ID, e.g., user_02")
    event_type: Literal[
        "salary_confirmation",
        "salary_revision",
        "bonus_unconfirmed",
        "bonus_delayed",
        "contract_ended",
        "rent_increase",
        "transfer_between_accounts",
        "cancellation",
        "refund_pending",
        "invoice_confirmed",
        "unconfirmed_earnings",
        "other"
    ] = Field(
        "other",
        description="Categorization of the financial message"
    )
    related_event_id: str | None = Field(
        None,
        description="Existing related event ID from the dataset (starts with 'event_') if supplied"
    )
    external_reference: str | None = Field(
        None,
        description="External reference identifier such as EMP-0001, SER-0012, MER-0014, BAN-0013"
    )
    is_confirmed_income: bool = Field(
        False,
        description="True ONLY if BOTH a positive amount AND a settlement date are explicitly confirmed"
    )
    confirmed_income_amount: float | None = Field(
        None,
        description="Amount of confirmed income in the stated currency"
    )
    confirmed_income_date: str | None = Field(
        None,
        description="Settlement/credit date for confirmed income in YYYY-MM-DD format"
    )
    confirmed_income_currency: str | None = Field(
        None,
        description="Currency of confirmed income, e.g., EUR, IDR, INR, USD"
    )
    is_cancelled_event: bool = Field(
        False,
        description="True if an existing event or pending item is explicitly cancelled or invalid"
    )
    cancelled_event_id: str | None = Field(
        None,
        description="Supplied event ID to cancel. Must start with 'event_', else null"
    )
    is_amended_event: bool = Field(
        False,
        description="True if an existing event has a revised amount or revised date"
    )
    amended_event_id: str | None = Field(
        None,
        description="Supplied event ID being amended. Must start with 'event_', else null"
    )
    amended_amount: float | None = Field(
        None,
        description="Revised amount if amended"
    )
    amended_date: str | None = Field(
        None,
        description="Revised settlement date (YYYY-MM-DD) if amended"
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0"
    )
    notes: str = Field(
        "",
        description="Concise factual explanation of what was extracted"
    )

    @field_validator("cancelled_event_id", mode="after")
    @classmethod
    def validate_cancelled_event_id(cls, v: str | None) -> str | None:
        if v and not v.startswith("event_"):
            return None
        return v

    @field_validator("amended_event_id", mode="after")
    @classmethod
    def validate_amended_event_id(cls, v: str | None) -> str | None:
        if v and not v.startswith("event_"):
            return None
        return v

    @model_validator(mode="after")
    def validate_confirmed_income(self) -> MessageEvidenceItem:
        if self.is_confirmed_income:
            if self.confirmed_income_amount is None or self.confirmed_income_amount <= 0 or not self.confirmed_income_date:
                self.is_confirmed_income = False
        return self


class MessageBatchExtraction(BaseModel):
    items: list[MessageEvidenceItem] = Field(
        default_factory=list,
        description="List of extracted evidence items for the batch of messages"
    )
