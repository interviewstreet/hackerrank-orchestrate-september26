from typing import Literal
from pydantic import BaseModel


class Decision(BaseModel):
    request_id: str
    amount_safe_to_pay: float
    affordability_status: Literal["affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"]
    recommended_payment_method: Literal["full_payment", "partial_payment", "installments", "wait", "not_recommended"]
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str


class OutputRow(BaseModel):
    request_id: str
    amount_safe_to_pay: float
    affordability_status: Literal["affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"]
    recommended_payment_method: Literal["full_payment", "partial_payment", "installments", "wait", "not_recommended"]
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str

    def to_csv_dict(self) -> dict[str, str]:
        # Format amount_safe_to_pay as integer if whole number, else decimal
        if self.amount_safe_to_pay == int(self.amount_safe_to_pay):
            safe_str = str(int(self.amount_safe_to_pay))
        else:
            safe_str = f"{self.amount_safe_to_pay:.2f}".rstrip("0").rstrip(".")
            if not safe_str:
                safe_str = "0"
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": safe_str,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }
