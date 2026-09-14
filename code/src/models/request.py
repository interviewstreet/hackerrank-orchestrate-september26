from datetime import date
from pydantic import BaseModel, Field


class RequestContext(BaseModel):
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
