from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class FinancialEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: Literal["debit", "credit", "non_cash"]
    amount: float | None = None
    currency: str
    event_date: date
    settlement_date: date
    status: Literal["settled", "pending", "scheduled", "cancelled", "failed", "unrealized"]
    linked_event_id: str | None = None
    flexibility: Literal["fixed", "stoppable", "reducible", "reducible_or_stoppable"]
    minimum_allowed_amount: float | None = None


class NormalizedFinancialEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: Literal["debit", "credit", "non_cash"]
    amount: float
    currency: str
    original_amount: float | None = None
    original_currency: str | None = None
    converted_amount: float  # In user's home currency
    home_currency: str = ""
    exchange_rate_used: float = 1.0
    exchange_rate_date: date | None = None
    event_date: date
    settlement_date: date
    status: Literal["settled", "pending", "scheduled", "cancelled", "failed", "unrealized"]
    linked_event_id: str | None = None
    flexibility: Literal["fixed", "stoppable", "reducible", "reducible_or_stoppable"]
    minimum_allowed_amount: float | None = None
    is_recurring: bool = False
    evidence_source: str = "csv"

    @model_validator(mode="after")
    def populate_currency_fields(self):
        if self.original_amount is None:
            self.original_amount = self.amount
        if self.original_currency is None:
            self.original_currency = self.currency
        if not self.home_currency:
            self.home_currency = self.currency
        return self


class ImageFact(BaseModel):
    image_id: str
    related_event_id: str
    extracted_amount: float | None = None
    extracted_currency: str | None = None
    extracted_date: date | None = None
    merchant_or_issuer: str | None = None
    confidence: float = 1.0
    evidence: str = ""


class MessageFact(BaseModel):
    message_id: str
    related_event_id: str | None = None
    action: Literal["confirm", "amend", "delay", "cancel", "replace", "clarify", "unknown"]
    affected_field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    new_amount: float | None = None
    new_currency: str | None = None
    new_date: date | None = None
    new_status: str | None = None
    confidence: float = 1.0
    evidence: str = ""


class SpendingChange(BaseModel):
    event_id: str
    action: Literal["stop", "reduce"]
    old_amount: float
    new_amount: float | None = None
    category: str


class ChangeSetEvaluation(BaseModel):
    changes: list[SpendingChange]
    safe: bool
    best_plan_id: str | None = None
    lowest_balance: float
    cost_score: float = 0.0
