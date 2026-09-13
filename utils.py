"""
utils.py - shared helpers: CSV I/O, currency conversion, date math, logging.

REAL DATASET SCHEMA (confirmed from the repo, Sept 2026 edition):

  requests.csv:
    request_id, user_id, request_date, request_type, requested_amount,
    desired_completion_date, allows_partial_payment, request_text

  financial_profiles.csv:
    user_id, home_currency, current_available_balance, minimum_balance_to_keep,
    financial_priorities, expense_categories_to_protect,
    expense_categories_user_is_willing_to_reduce,
    expense_categories_user_is_willing_to_stop,
    payment_methods_user_will_consider, max_installment_months

  financial_events.csv:
    event_id, user_id, event_type, description, category, direction, amount,
    currency, event_date, settlement_date, status, linked_event_id,
    flexibility, minimum_allowed_amount
      direction    : debit | credit
      status       : settled | pending | scheduled | cancelled | failed
      flexibility  : fixed | stoppable | reducible | reducible_or_stoppable

  request_payment_options.csv:
    payment_option_id, request_id, payment_method, payment_amount,
    number_of_payments, first_payment_date, payment_frequency_days,
    financing_fee, total_payable_amount

  messages.csv:
    message_id, user_id, request_id, related_event_id, sent_at, source_type,
    message_text

  images.csv:
    image_id, user_id, request_id, related_event_id

  exchange_rates.csv:
    rate_date, from_currency, to_currency, rate
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from typing import Optional

DATE_FMT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_csv(path: str) -> list[dict]:
    """Read a CSV file into a list of dict rows. Returns [] if missing."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: str, rows: list[dict], columns: list[str]) -> None:
    """Write rows to CSV with an exact, ordered column list."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    """Group a list of dict rows by a given key's value."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def index_by(rows: list[dict], key: str) -> dict[str, dict]:
    """Index rows by a key assumed unique (e.g. user_id -> profile row)."""
    return {row[key]: row for row in rows if row.get(key)}


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str.strip(), DATE_FMT)


def format_date(dt: datetime) -> str:
    return dt.strftime(DATE_FMT)


def date_range(start: str, days: int) -> list[str]:
    """Inclusive list of date strings from start through start+days."""
    start_dt = parse_date(start)
    return [format_date(start_dt + timedelta(days=i)) for i in range(days + 1)]


def days_between(d1: str, d2: str) -> int:
    return (parse_date(d2) - parse_date(d1)).days


def format_amount(amount: float) -> str:
    """
    Format a currency amount for the `payment_plan` column specifically:
    whole numbers print with no decimal ('25256'), fractional amounts always
    print with exactly 2 decimals, trailing zero included ('620.40',
    '3246.10'). Confirmed against dataset/sample_requests.csv - every
    payment_plan entry in the real ground truth follows this whole-or-2dp
    convention, distinct from amount_safe_to_pay's natural formatting below.
    """
    rounded = round(amount, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"


def format_amount_natural(amount: float) -> str:
    """
    Format a currency amount for the standalone `amount_safe_to_pay` column:
    whole numbers print with no decimal ('25256'), fractional amounts print
    with their natural (unpadded) precision after rounding to 2dp ('603.3',
    '17229139.2', '284.57') rather than always forcing 2 decimals. Confirmed
    against dataset/sample_requests.csv - amount_safe_to_pay does NOT follow
    payment_plan's whole-or-2dp convention; it's just round(x, 2) printed
    without Python's trailing '.0' on whole floats.
    """
    rounded = round(amount, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def safe_float(value, default: Optional[float] = None) -> Optional[float]:
    """Parse a possibly-blank numeric CSV cell."""
    if value is None:
        return default
    value = str(value).strip()
    if value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Currency conversion
# ---------------------------------------------------------------------------

class ExchangeRateTable:
    """Fixed, dated FX rates. Exact (date, from, to) lookup with a documented
    fallback to the nearest earlier date if an exact match is missing."""

    def __init__(self, rows: list[dict]):
        # key: (from_currency, to_currency) -> sorted [(rate_date, rate), ...]
        self._by_pair: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for r in rows:
            pair = (r["from_currency"], r["to_currency"])
            self._by_pair.setdefault(pair, []).append((r["rate_date"], safe_float(r["rate"], 1.0)))
        for pair in self._by_pair:
            self._by_pair[pair].sort(key=lambda x: x[0])

    def get_rate(self, date: str, from_ccy: str, to_ccy: str) -> float:
        if from_ccy == to_ccy:
            return 1.0
        pair = (from_ccy, to_ccy)
        entries = self._by_pair.get(pair)
        if not entries:
            raise ValueError(f"No exchange rate series for {from_ccy}->{to_ccy}")

        # exact match first
        for d, rate in entries:
            if d == date:
                return rate

        # fallback: latest rate on or before the requested date
        candidates = [(d, r) for d, r in entries if d <= date]
        if candidates:
            return candidates[-1][1]

        # last resort: earliest available rate (documented assumption)
        return entries[0][1]

    def convert(self, amount: float, date: str, from_ccy: str, to_ccy: str) -> float:
        return amount * self.get_rate(date, from_ccy, to_ccy)


# ---------------------------------------------------------------------------
# Logging (simple, deterministic - avoid depending on external libs)
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    print(f"[{datetime.utcnow().isoformat(timespec='seconds')}Z] {message}")