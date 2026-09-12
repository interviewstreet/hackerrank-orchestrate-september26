import os
import json
from datetime import datetime, date
from typing import Optional, Dict, Any
from functools import lru_cache

import google.generativeai as genai
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# Load environment variables (API key and model name)
load_dotenv()
API_KEY = os.getenv('GEMINI_API_KEY')
MODEL_NAME = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash-001')

if not API_KEY:
    raise RuntimeError('GEMINI_API_KEY not set in environment')

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(MODEL_NAME)


class EvidenceOutput(BaseModel):
    amount: Optional[float] = Field(None, description='Numeric amount extracted, if any')
    currency: Optional[str] = Field(None, description='Currency code, e.g., USD, EUR')
    date: Optional[date] = Field(None, description='Date mentioned in the evidence')
    event_reference: Optional[str] = Field(None, description='Related financial event id, if mentioned')
    cancellation: bool = Field(False, description='True if the message cancels a previous event')
    settlement: bool = Field(False, description='True if the message confirms settlement')
    amendment: bool = Field(False, description='True if the message amends a prior fact')
    delay: bool = Field(False, description='True if the message indicates a delay')
    confirmation: bool = Field(False, description='True if the message confirms a fact')

    @validator('amount')
    def amount_positive(cls, v):
        if v is not None and v < 0:
            raise ValueError('Amount must be non‑negative')
        return v


def _build_prompt(message_text: str) -> str:
    Create
