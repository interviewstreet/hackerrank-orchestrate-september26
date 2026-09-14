from datetime import date
from pydantic import BaseModel, Field
from code.src.models.events import NormalizedFinancialEvent


class DailyBalanceCheckpoint(BaseModel):
    checkpoint_date: date
    starting_balance: float
    credits: float = 0.0
    debits: float = 0.0
    ending_balance: float
    events: list[str] = Field(default_factory=list)


class Forecast(BaseModel):
    start_date: date
    end_date: date
    starting_balance: float
    lowest_balance: float
    lowest_balance_date: date
    ending_balance: float
    checkpoints: list[DailyBalanceCheckpoint] = Field(default_factory=list)
    safe: bool = True
