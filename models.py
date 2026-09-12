from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class FinancialProfile(BaseModel):
    user_id: str
    home_currency: str
    current_balance: float
    minimum_balance_to_keep: float
    priorities: List[str]
    protected_spending_categories: List[str]
    flexible_spending_categories: List[str]
    payment_preferences: List[str]
    max_installment_months: Optional[int] = None

    @validator('current_balance', 'minimum_balance_to_keep')
    def non_negative(cls, v):
        if v < 0:
            raise ValueError('Balance values must be non‑negative')
        return v


class FinancialEvent(BaseModel):
    event_id: str
    user_id: str
    amount: float
    currency: str
    event_type: str  # e.g., "salary", "expense", "pending_debit", etc.
    status: str      # "settled", "pending", "scheduled", "failed", "cancelled"
    date: date
    linked_event_id: Optional[str] = None

    @validator('amount')
    def amount_non_negative(cls, v):
        if v < 0:
            raise ValueError('Amount must be non‑negative')
        return v


class ExchangeRate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float
    date: date

    @validator('rate')
    def positive_rate(cls, v):
        if v <= 0:
            raise ValueError('Rate must be positive')
        return v


class PaymentOption(BaseModel):
    option_id: str
    request_id: str
    method: str           # "full", "partial", "installment"
    installment_months: Optional[int] = None
    interval_days: Optional[int] = None
    fee: Optional[float] = None
    total_amount: float
    start_date: date

    @validator('total_amount')
    def total_positive(cls, v):
        if v <= 0:
            raise ValueError('Total amount must be positive')
        return v


class Request(BaseModel):
    request_id: str
    user_id: str
    requested_amount: float
    request_date: date
    desired_completion_date: date
    # other fields may be added later

    @validator('requested_amount')
    def pos_amount(cls, v):
        if v <= 0:
            raise ValueError('Requested amount must be positive')
        return v


class CandidatePlan(BaseModel):
    plan_id: str
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date] = None
    spending_changes_needed: List[str] = Field(default_factory=list)
    decision_explanation: str
    # Helper fields for ranking (not part of output CSV)
    meets_deadline: bool = False
    uses_spending_changes: bool = False
    total_paid: float = 0.0
    start_date: Optional[date] = None
    payment_count: int = 0
    payment_option_id: Optional[str] = None
