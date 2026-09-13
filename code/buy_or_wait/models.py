"""Immutable domain models used by the input layer and later decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

Currency = Literal["EUR", "IDR", "INR", "USD", "ZAR"]
EventType = Literal[
    "expense", "debt_payment", "subscription", "income", "refund",
    "investment_purchase", "investment_valuation", "investment_sale",
]
Direction = Literal["debit", "credit", "non_cash"]
EventStatus = Literal["settled", "cancelled", "pending", "scheduled", "failed", "unrealized"]
Flexibility = Literal["fixed", "stoppable", "reducible", "reducible_or_stoppable"]
PaymentMethod = Literal["full_payment", "partial_payment", "installments", "wait", "not_recommended"]


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: Currency
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: tuple[str, ...]
    expense_categories_to_protect: tuple[str, ...]
    expense_categories_user_is_willing_to_reduce: tuple[str, ...]
    expense_categories_user_is_willing_to_stop: tuple[str, ...]
    payment_methods_user_will_consider: tuple[PaymentMethod, ...]
    max_installment_months: int | None


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: Direction
    amount: Decimal
    currency: Currency
    event_date: date
    settlement_date: date | None
    status: EventStatus
    linked_event_id: str | None
    flexibility: Flexibility
    minimum_allowed_amount: Decimal | None
    amount_from_image_evidence: bool = False


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: Literal["full_payment", "installments"]
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: datetime
    source_type: Literal["employer", "service_provider", "bank", "merchant", "financial_service"]
    message_text: str


@dataclass(frozen=True)
class ImageLink:
    image_id: str
    user_id: str
    request_id: str
    related_event_id: str


@dataclass(frozen=True)
class CashFlow:
    """A normalized dated cash movement for the future simulator."""

    flow_date: date
    amount: Decimal
    currency: Currency
    direction: Direction
    source_event_id: str | None
    description: str
    is_recurring: bool = False
    is_message_amendment: bool = False
    original_currency: Currency | None = None
    conversion_rate: Decimal | None = None
    sequence: int = 0


@dataclass(frozen=True)
class MessageAmendment:
    """A narrow, deterministic interpretation of supporting message evidence."""

    message_id: str
    related_event_id: str | None
    kind: str
    details: str


@dataclass(frozen=True)
class EvidenceAmendment:
    amendment_id: str
    amendment_type: str
    source_message_id: str
    affected_event_id: str
    effective_date: date
    old_amount: Decimal | None
    new_amount: Decimal | None
    old_status: EventStatus | None
    new_status: EventStatus | None
    explanation: str


@dataclass(frozen=True)
class BaselineAffordabilityResult:
    """Financial capacity before payment preferences or spending changes."""

    amount_safe_to_pay: Decimal
    earliest_date_for_full_payment: date | None
