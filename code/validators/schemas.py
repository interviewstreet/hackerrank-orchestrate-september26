"""Pydantic models for every data boundary.

Field names mirror the actual dataset/*.csv headers exactly. Where the CSV
uses a blank string for "absent", the loaders coerce to None so that a blank
amount is never silently read as zero.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from math import ceil

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Enums ───────────────────────────────────────────────────────────────────

class AffordabilityStatus(str, Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventStatus(str, Enum):
    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class Flexibility(str, Enum):
    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


class ModAction(str, Enum):
    CANCEL = "CANCEL"
    AMEND_AMOUNT = "AMEND_AMOUNT"
    AMEND_DATE = "AMEND_DATE"
    DELAY = "DELAY"
    CONFIRM = "CONFIRM"
    INFORMATIONAL = "INFORMATIONAL"


# ── Input rows (one model per CSV) ──────────────────────────────────────────

class RequestRow(BaseModel):
    """dataset/requests.csv"""

    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str = ""


class FinancialProfile(BaseModel):
    """dataset/financial_profiles.csv"""

    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str] = Field(default_factory=list)
    expense_categories_to_protect: list[str] = Field(default_factory=list)
    expense_categories_user_is_willing_to_reduce: list[str] = Field(default_factory=list)
    expense_categories_user_is_willing_to_stop: list[str] = Field(default_factory=list)
    payment_methods_user_will_consider: list[str] = Field(default_factory=list)
    max_installment_months: int | None = None

    def accepts(self, method: PaymentMethod) -> bool:
        return method.value in self.payment_methods_user_will_consider

    def may_reduce(self, category: str) -> bool:
        return category in self.expense_categories_user_is_willing_to_reduce

    def may_stop(self, category: str) -> bool:
        return category in self.expense_categories_user_is_willing_to_stop

    def is_protected(self, category: str) -> bool:
        return category in self.expense_categories_to_protect


class FinancialEvent(BaseModel):
    """dataset/financial_events.csv"""

    event_id: str
    user_id: str
    event_type: str
    description: str = ""
    category: str = ""
    direction: Direction
    amount: float | None = None  # None => must be recovered from a linked image
    currency: str | None = None
    event_date: date
    settlement_date: date | None = None
    status: EventStatus
    linked_event_id: str | None = None
    flexibility: Flexibility = Flexibility.FIXED
    minimum_allowed_amount: float | None = None

    @property
    def cash_date(self) -> date:
        """The date money actually moves."""
        return self.settlement_date or self.event_date

    @property
    def is_cash(self) -> bool:
        """Non-cash rows (unrealized investment value) never affect balance."""
        return self.direction is not Direction.NON_CASH

    @property
    def can_stop(self) -> bool:
        return self.flexibility in (
            Flexibility.STOPPABLE,
            Flexibility.REDUCIBLE_OR_STOPPABLE,
        )

    @property
    def can_reduce(self) -> bool:
        return self.flexibility in (
            Flexibility.REDUCIBLE,
            Flexibility.REDUCIBLE_OR_STOPPABLE,
        )


class Message(BaseModel):
    """dataset/messages.csv -- untrusted evidence."""

    message_id: str
    user_id: str
    request_id: str | None = None
    related_event_id: str | None = None
    sent_at: date
    source_type: str = ""
    message_text: str = ""
    is_trusted: bool = True  # cleared by the safety gate on injection signals
    injection_note: str | None = None


class ImageRef(BaseModel):
    """dataset/images.csv"""

    image_id: str
    user_id: str
    request_id: str | None = None
    related_event_id: str | None = None


class PaymentOption(BaseModel):
    """dataset/request_payment_options.csv"""

    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None = None
    financing_fee: float = 0.0
    total_payable_amount: float

    @property
    def months_span(self) -> int:
        """Installment horizon in whole months, for max_installment_months."""
        if self.number_of_payments <= 1:
            return 0
        days = (self.payment_frequency_days or 30) * self.number_of_payments
        return max(1, ceil(days / 30))

    def schedule(self) -> list[tuple[date, float]]:
        """The option's payments, exactly as supplied."""
        step = self.payment_frequency_days or 30
        return [
            (self.first_payment_date + timedelta(days=step * i), self.payment_amount)
            for i in range(self.number_of_payments)
        ]


class ExchangeRate(BaseModel):
    """dataset/exchange_rates.csv"""

    rate_date: date
    from_currency: str
    to_currency: str
    rate: float


# ── Tool I/O ────────────────────────────────────────────────────────────────

class ReceiptExtraction(BaseModel):
    """Structured result of reading a receipt image."""

    amount: float | None = Field(None, gt=0, lt=1e12)
    currency: str | None = Field(None, min_length=3, max_length=3)
    vendor: str | None = None
    receipt_date: date | None = None
    confidence: str = Field("medium", pattern=r"^(high|medium|low)$")

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class EventModification(BaseModel):
    """A change to a known event or recurring series, derived from a message."""

    # Models reliably pick the right action but not always the right key name,
    # and Groq rejects a tool call whose arguments miss a required property.
    # Accepting the common synonyms keeps a correct answer from being thrown away.
    action: ModAction = Field(
        validation_alias=AliasChoices("action", "type", "intent", "kind")
    )
    event_id: str | None = None
    series_key: str | None = None  # when the message describes a series
    new_amount: float | None = Field(
        None, validation_alias=AliasChoices("new_amount", "amount", "value")
    )
    new_date: date | None = Field(
        None,
        validation_alias=AliasChoices(
            "new_date", "date", "effective_date", "new_settlement_date"
        ),
    )
    source_message_id: str = ""
    reason: str = ""

    model_config = ConfigDict(populate_by_name=True)


class MessageAnalysis(BaseModel):
    modifications: list[EventModification] = Field(default_factory=list)
    reasoning: str = ""


class SpendingChange(BaseModel):
    change_type: str = Field(pattern=r"^(stop|reduce_to)$")
    event_id: str
    new_amount: float | None = None

    def render(self) -> str:
        if self.change_type == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{_num(self.new_amount or 0.0)}"


class CashFlow(BaseModel):
    """One projected movement of money, in home currency."""

    on: date
    amount: float  # positive = credit, negative = debit
    label: str
    event_id: str | None = None
    series_key: str | None = None
    projected: bool = False
    # Intra-day ordering: 0 for the user's existing commitments, 1 for a
    # payment the recommendation adds. A payment is made once the day's
    # income has landed, while commitments are reserved conservatively.
    sequence: int = 0


class BalanceForecast(BaseModel):
    minimum_balance_reached: float
    amount_safe_to_pay: float = Field(ge=0.0)
    earliest_full_payment_date: date | None = None
    headroom_today: float
    is_safe: bool
    flow_count: int = 0


class PaymentPlanEntry(BaseModel):
    payment_date: date
    amount: float = Field(gt=0.0)

    def render(self) -> str:
        return f"{self.payment_date.isoformat()}:{_num(self.amount)}"


class CandidatePlan(BaseModel):
    method: PaymentMethod
    payments: list[PaymentPlanEntry] = Field(default_factory=list)
    total_cost: float = 0.0
    payment_option_id: str | None = None
    spending_changes: list[SpendingChange] = Field(default_factory=list)
    completes_by_deadline: bool = False
    completes_request: bool = False
    is_safe: bool = False

    def render_plan(self) -> str:
        if not self.payments:
            return "none"
        return "|".join(p.render() for p in self.payments)


# ── Output ──────────────────────────────────────────────────────────────────

class AgentOutput(BaseModel):
    """One fully validated row of output.csv."""

    request_id: str
    amount_safe_to_pay: float = Field(ge=0.0)
    affordability_status: AffordabilityStatus
    recommended_payment_method: PaymentMethod
    payment_plan: str
    earliest_date_for_full_payment: str = ""
    spending_changes_needed: str = "none"
    decision_explanation: str = ""

    # Carried for cross-field validation; excluded from CSV serialisation.
    requested_amount: float = Field(default=0.0, exclude=True)

    @field_validator("decision_explanation")
    @classmethod
    def _truncate(cls, v: str) -> str:
        """Truncate rather than raise -- a verbose model must not lose the row."""
        v = " ".join(v.split())
        return v if len(v) <= 500 else v[:497].rstrip() + "..."

    @field_validator("payment_plan")
    @classmethod
    def _plan_shape(cls, v: str) -> str:
        if v == "none":
            return v
        for entry in v.split("|"):
            parts = entry.split(":")
            if len(parts) != 2 or len(parts[0]) != 10:
                raise ValueError(f"malformed payment_plan entry: {entry!r}")
        return v

    @model_validator(mode="after")
    def _cap_amount(self) -> "AgentOutput":
        if self.requested_amount > 0:
            capped = min(max(0.0, self.amount_safe_to_pay), self.requested_amount)
            object.__setattr__(self, "amount_safe_to_pay", round(capped, 2))
        return self

    def to_row(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": _num(self.amount_safe_to_pay),
            "affordability_status": self.affordability_status.value,
            "recommended_payment_method": self.recommended_payment_method.value,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)


def _num(value: float) -> str:
    """Render a money amount without trailing .0 noise."""
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")
