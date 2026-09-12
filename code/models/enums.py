"""
enums.py — All enumerated types used across the Buy or Wait? domain models.

Every string value matches exactly what appears in the dataset CSVs.
"""
from enum import Enum


class AffordabilityStatus(str, Enum):
    """Output field: affordability_status."""
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class PaymentMethod(str, Enum):
    """Output field: recommended_payment_method.
    Also used in financial_profiles.payment_methods_user_will_consider
    and request_payment_options.payment_method.
    """
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class EventStatus(str, Enum):
    """financial_events.status"""
    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNREALIZED = "unrealized"


class EventDirection(str, Enum):
    """financial_events.direction"""
    DEBIT = "debit"
    CREDIT = "credit"


class EventType(str, Enum):
    """financial_events.event_type — broad taxonomy."""
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    INVESTMENT = "investment"
    LOAN = "loan"
    SALARY = "salary"
    BONUS = "bonus"
    REFUND = "refund"
    # Allow unknown types to pass through without validation failure
    OTHER = "other"

    @classmethod
    def _missing_(cls, value: object) -> "EventType":  # type: ignore[override]
        return cls.OTHER


class Flexibility(str, Enum):
    """financial_events.flexibility"""
    FIXED = "fixed"
    FLEXIBLE = "flexible"
