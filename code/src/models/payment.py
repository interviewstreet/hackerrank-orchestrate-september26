from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class PaymentOption(BaseModel):
    payment_option_id: str
    request_id: str
    payment_method: Literal["full_payment", "installments"]
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None = None
    financing_fee: float
    total_payable_amount: float


class PaymentItem(BaseModel):
    payment_date: date
    amount: float


class PaymentPlan(BaseModel):
    plan_id: str
    method: Literal["full_payment", "partial_payment", "installments", "wait", "not_recommended"]
    payments: list[PaymentItem] = Field(default_factory=list)
    total_amount: float
    financing_fee: float = 0.0
    completion_date: date | None = None
    payment_option_id: str | None = None


class PlanEvaluation(BaseModel):
    plan_id: str
    plan: PaymentPlan

    financially_safe: bool
    deadline_ok: bool
    method_allowed: bool
    request_satisfied: bool
    eligible: bool

    lowest_balance: float
    lowest_balance_date: date | None = None
    ending_balance: float

    violation_codes: list[str] = Field(default_factory=list)
    violation_date: date | None = None

    timeline: list[dict] = Field(default_factory=list)
