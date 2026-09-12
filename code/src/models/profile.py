from pydantic import BaseModel, Field


class UserFinancialProfile(BaseModel):
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
