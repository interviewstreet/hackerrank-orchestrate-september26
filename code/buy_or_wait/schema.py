"""Typed records and closed vocabularies for the Buy or Wait? engine.

Two things live here and nowhere else:

1. The **output contract** -- the eight CSV columns, in order, and the enum
   values they may hold (`problem_statement.md` "Allowed values").
2. The **input vocabularies** actually present in ``dataset/``.

The vocabularies are documentation-grade regression constants, not prediction
logic. ``audit.py`` re-derives each one from the CSV and fails loudly if the
dataset ever disagrees, so a silent dataset change cannot slip past as a
mysterious validation failure later.

Note on categories: the dataset carries **two separate vocabularies** that look
alike and are not interchangeable.

* ``EVENT_CATEGORIES`` -- the 22 expense/income categories on financial events,
  also used by the profile's protect / willing-to-reduce / willing-to-stop lists.
* ``FINANCIAL_PRIORITIES`` -- a goal vocabulary used only by
  ``financial_profiles.financial_priorities``. Three of its members
  (``retirement_investment``, ``emergency_savings``, ``travel``) are not event
  categories at all. Validating a priority against the event vocabulary would
  produce a spurious failure on 278 profile tokens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

# --------------------------------------------------------------- output ------

#: The submission contract. Order is part of the contract.
OUTPUT_COLUMNS: tuple[str, ...] = (
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
)

AFFORDABILITY_STATUSES: frozenset[str] = frozenset({
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
})

PAYMENT_METHODS: frozenset[str] = frozenset({
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
})

#: Sentinel written into `payment_plan` / `spending_changes_needed` when empty.
NONE_LITERAL = "none"

# ---------------------------------------------------------------- input ------

REQUEST_INPUT_COLUMNS: tuple[str, ...] = (
    "request_id",
    "user_id",
    "request_date",
    "request_type",
    "requested_amount",
    "desired_completion_date",
    "allows_partial_payment",
    "request_text",
)

#: `sample_requests.csv` = the input columns followed by the seven label columns.
SAMPLE_LABEL_COLUMNS: tuple[str, ...] = OUTPUT_COLUMNS[1:]
SAMPLE_COLUMNS: tuple[str, ...] = REQUEST_INPUT_COLUMNS + SAMPLE_LABEL_COLUMNS

REQUEST_TYPES: frozenset[str] = frozenset({
    "purchase", "travel", "education", "family_transfer", "debt_repayment",
    "investment", "housing", "emergency_expense", "other",
})

EVENT_TYPES: frozenset[str] = frozenset({
    "expense", "subscription", "income", "debt_payment",
    "investment_purchase", "investment_sale", "investment_valuation", "refund",
})

DIRECTIONS: frozenset[str] = frozenset({"debit", "credit", "non_cash"})

EVENT_STATUSES: frozenset[str] = frozenset({
    "settled", "pending", "scheduled", "cancelled", "failed", "unrealized",
})

FLEXIBILITIES: frozenset[str] = frozenset({
    "fixed", "reducible", "stoppable", "reducible_or_stoppable",
})

#: A spending action is only structurally possible on these.
STOPPABLE_FLEXIBILITIES: frozenset[str] = frozenset({"stoppable", "reducible_or_stoppable"})
REDUCIBLE_FLEXIBILITIES: frozenset[str] = frozenset({"reducible", "reducible_or_stoppable"})

SOURCE_TYPES: frozenset[str] = frozenset({
    "bank", "employer", "financial_service", "merchant", "service_provider",
})

#: Offer methods present in request_payment_options.csv. Partial payment is
#: granted by the request + profile contract, never by a seller offer.
PAYMENT_OPTION_METHODS: frozenset[str] = frozenset({"full_payment", "installments"})

CURRENCIES: frozenset[str] = frozenset({"INR", "EUR", "IDR", "ZAR", "USD"})

EVENT_CATEGORIES: frozenset[str] = frozenset({
    "cloud_storage", "debt_repayment", "delivery_membership", "dining",
    "education", "entertainment", "family_support", "groceries", "gym",
    "healthcare", "housing", "insurance", "investment", "music_subscription",
    "rent", "salary", "shopping", "streaming", "transport", "utilities",
    "windfall", "work_expense",
})

#: Goal vocabulary -- profiles only. Deliberately NOT a subset of EVENT_CATEGORIES:
#: `emergency_savings`, `retirement_investment` and `travel` are goals with no
#: matching event category.
#:
#: This set is OBSERVED, not gating. Priorities express ranking preference; they
#: never authorize a spending change or unlock a payment method, so an unknown
#: token here cannot make an unsafe decision possible. The loader therefore
#: accepts any token and `audit.py` reports drift as a warning. Contrast with
#: `expense_categories_*`, which do authorize interventions and are validated
#: strictly against EVENT_CATEGORIES.
OBSERVED_FINANCIAL_PRIORITIES: frozenset[str] = frozenset({
    "debt_repayment", "education", "emergency_savings", "family_support",
    "healthcare", "housing", "retirement_investment", "travel",
})

# ----------------------------------------------------------- input records ---


@dataclass(frozen=True)
class RequestInput:
    """One evaluation request.

    This record has **no field capable of holding an expected output**. That is
    the structural half of label isolation: prediction code cannot read a label
    because there is nowhere to put one. `sample_requests.csv` labels are loaded
    separately, by the evaluator only (`code/evaluation/labels.py`).
    """

    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: tuple[str, ...]
    expense_categories_to_protect: frozenset[str]
    expense_categories_user_is_willing_to_reduce: frozenset[str]
    expense_categories_user_is_willing_to_stop: frozenset[str]
    payment_methods_user_will_consider: frozenset[str]
    #: Blank in 119 of 275 profiles -- means the user will not consider
    #: installments at all. `None` is not `0` and is not "unlimited".
    max_installment_months: Optional[int]


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    #: `None` means the amount is UNKNOWN, never zero. 15 of the 16 blank
    #: amounts are debits; resolving them is M2 work via the linked image.
    amount: Optional[Decimal]
    currency: str
    event_date: date
    settlement_date: Optional[date]
    status: str
    linked_event_id: Optional[str]
    flexibility: str
    minimum_allowed_amount: Optional[Decimal]

    @property
    def amount_is_unknown(self) -> bool:
        return self.amount is None

    @property
    def cash_date(self) -> date:
        """The date the money actually moves."""
        return self.settlement_date or self.event_date


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    #: Blank for `full_payment` offers (a single payment has no cadence).
    payment_frequency_days: Optional[int]
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    #: Populated only when the message describes one supplied event row. Blank
    #: means "no one-to-one event row", NOT "irrelevant".
    related_event_id: Optional[str]
    sent_at: str          # ISO-8601 with timezone, kept verbatim
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageRef:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]

    def filename(self) -> str:
        return f"{self.image_id}.png"


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class RequestContext:
    """Everything scoped to one request, assembled by `data.py`.

    Scoping rule: user-level records are included for the request's user;
    records that carry their own `request_id` are included only when it matches.
    A message for the same user but a different request must not leak in.
    """

    request: RequestInput
    profile: Profile
    events: tuple[FinancialEvent, ...]
    messages: tuple[Message, ...]
    images: tuple[ImageRef, ...]
    payment_options: tuple[PaymentOption, ...]

    @property
    def home_currency(self) -> str:
        return self.profile.home_currency

    def event_ids(self) -> frozenset[str]:
        return frozenset(e.event_id for e in self.events)
