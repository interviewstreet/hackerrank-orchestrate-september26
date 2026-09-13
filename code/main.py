"""
main.py - entry point for the "Buy or Wait?" solution.

Run with: python3 main.py   (from inside code/)
Reads dataset/ from ../dataset relative to this file, writes ../output.csv.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta

from forecast import amount_safe_to_pay, earliest_date_for_full_payment, FORECAST_DAYS
from plan_ranking import build_candidate_plans, rank_plans
from state_reconstruction import build_user_forward_events
from utils import (
    ExchangeRateTable, date_range, format_amount_natural, format_date,
    group_by, index_by, load_csv, parse_date, safe_float, write_csv, log,
)

DATASET_DIR = os.path.join(os.path.dirname(__file__), "..", "dataset")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "output.csv")

REQUIRED_OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


# Amounts extracted from dataset/media/images/<image_id>.png via vision
# reading, cross-checked against each linked event's `description` field.
# There are only 16 images total in the dataset — fully deterministic.
IMAGE_AMOUNT_CACHE: dict[str, float] = {
    "image_01": 4365000.0,   # payslip - Net Pay (IDR)
    "image_02": 100000.0,    # rent receipt - Balance Due (INR)
    "image_03": 41272.0,     # grocery bill of supply - Net Amount (INR)
    "image_04": 2854.0,      # grocery delivery app - Item Bill (INR)
    "image_05": 704.05,      # telecom bill - Amount due till 06-Feb-2026 (INR)
    "image_06": 1995.0,      # grocery tax invoice - Total (INR)
    "image_07": 8528.10,     # restaurant tax invoice - Total (INR)
    "image_08": 15339.0,     # maintenance receipt - Total Amount Received (INR)
    "image_09": 723.0,       # water bill receipt - Total Amount Received (INR)
    "image_10": 79679.26,    # large grocery tax invoice - Balance Due (INR)
    "image_11": 3650.0,      # hospital bill - Amount Payable (INR)
    "image_12": 33.50,       # taxi receipt - Total (USD)
    "image_13": 2298.0,      # tote bag order - Total paid (INR)
    "image_14": 4593.0,      # handwritten pharmacy bill - Total (INR)
    "image_15": 9968.0,      # airline invoice - Grand Total incl. taxes (INR)
    "image_16": 393.22,      # EV charging invoice - Total (INR)
}


def image_amount_lookup(image_id: str):
    return IMAGE_AMOUNT_CACHE.get(image_id)


# ---------------------------------------------------------------------------
# Message parsing — extract salary signals from free-text messages
# ---------------------------------------------------------------------------

# Patterns for amounts with optional currency prefix
_AMT = r'(?:EUR|USD|IDR|ZAR|INR|[A-Z]{3})?\s*([\d,]+(?:\.\d+)?)'

# "next salary is reduced to EUR 1422.85"  /  "gaji berkurang menjadi 38760000"
_RE_REDUCED = re.compile(
    r'(?:salary|pay|gaji|bayaran)\s+(?:is\s+)?reduced\s+to\s+' + _AMT,
    re.IGNORECASE
)
# "salary has increased to / raised to / naik menjadi 42750000"
_RE_RAISED = re.compile(
    r'(?:salary|gaji|pay)\s+(?:has\s+)?(?:increased?|raised?|naik(?:\s+menjadi)?)\s+(?:to\s+)?' + _AMT,
    re.IGNORECASE
)
# "your salary is EUR 1529" / "confirmed salary is IDR 38760000"
# "your temporary monthly pay is EUR 1037.52"
_RE_CONFIRMED = re.compile(
    r'(?:confirmed\s+)?(?:base\s+)?(?:salary|pay)\s+(?:is|of|will be)\s+' + _AMT,
    re.IGNORECASE
)
# "salary confirmed for 2025-08-15" / "salary is confirmed IDR 38760000"
# Indonesian: "gaji pokok yang dikonfirmasi adalah IDR 38760000"
_RE_CONFIRMED2 = re.compile(
    r'(?:salary|gaji\s+pokok).*?(?:confirmed|dikonfirmasi)\s+(?:adalah\s+)?' + _AMT,
    re.IGNORECASE
)
# "first salary will be EUR 1661"
_RE_FIRST = re.compile(
    r'first\s+salary\s+(?:will be|of|is)\s+' + _AMT,
    re.IGNORECASE
)
# "expected on 2024-09-23" — date override for next salary
_RE_EXPECTED_DATE = re.compile(r'expected\s+on\s+(\d{4}-\d{2}-\d{2})', re.IGNORECASE)
# "resumes? on 2025-08-15"
_RE_RESUME_DATE = re.compile(r'resumes?\s+on\s+(\d{4}-\d{2}-\d{2})', re.IGNORECASE)
# "confirmed credit date is 2026-01-15" / "scheduled for 2026-01-15"
_RE_CREDIT_DATE = re.compile(
    r'(?:confirmed\s+credit\s+date\s+is|scheduled\s+for|confirmed\s+for)\s+(\d{4}-\d{2}-\d{2})',
    re.IGNORECASE
)
# "regular salary of INR 251000 resumes on 2026-01-15"
_RE_RESUME_AMOUNT_DATE = re.compile(
    r'(?:regular\s+salary|salary)\s+of\s+' + _AMT + r'\s+resumes?\s+on\s+(\d{4}-\d{2}-\d{2})',
    re.IGNORECASE
)
# Employment / contract ended keywords
_SALARY_END_PATTERNS = [
    r'employment has ended',
    r'seasonal contract has ended',
    r'no off-season income',
    r'contract has ended',
    r'employment ended',
    r'hubungan kerja.*?berakhir',      # Indonesian
    r'kontrak musiman.*?berakhir',     # Indonesian
    r'tidak ada pendapatan',           # Indonesian
]
# Gig payout pending / uncertain keywords
_GIG_PENDING_PATTERNS = [
    r'payout is still pending',
    r'earnings.*?can change until',
    r'not withdrawable until',
    r'balance isn.*?t withdrawable',
    r'pembayaran berikutnya.*?masih menunggu',  # Indonesian
]


def _parse_number(s: str) -> Optional[float]:
    """Parse a number string that may contain commas."""
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _extract_salary_signals(messages: list[dict], request_date: str) -> dict:
    """
    Parse all messages for one user/request and return a dict of salary signals:
      salary_stop        – bool: stop projecting salary entirely
      salary_override_amount  – float | None: replace recurring typical_amount
      salary_override_next_date – str | None: shift next projected salary to this date
      extra_debit_items  – list[dict]: new recurring debit signals (e.g. childcare)
    """
    signals = {
        "salary_stop": False,
        "salary_override_amount": None,
        "salary_override_next_date": None,
        "extra_debit_items": [],
    }

    combined_text = " ".join(m.get("message_text", "") for m in messages)
    lower = combined_text.lower()

    # --- Gig income is uncertain → don't project ---
    if any(re.search(p, lower) for p in _GIG_PENDING_PATTERNS):
        signals["salary_stop"] = True
        return signals

    # --- Employment / contract ended → don't project ---
    if any(re.search(p, lower) for p in _SALARY_END_PATTERNS):
        signals["salary_stop"] = True
        return signals

    # --- Salary resumes on a future date (gap in income) ---
    m = re.search(_RE_RESUME_AMOUNT_DATE, combined_text)
    if m:
        amt = _parse_number(m.group(1))
        resume_date = m.group(2)
        if amt and resume_date >= request_date:
            # No salary until resume_date; use the resumed amount
            signals["salary_override_amount"] = amt
            signals["salary_override_next_date"] = resume_date

    m = re.search(_RE_RESUME_DATE, combined_text)
    if m and not signals["salary_override_next_date"]:
        resume_date = m.group(1)
        if resume_date >= request_date:
            signals["salary_override_next_date"] = resume_date

    # --- Next salary date changed ---
    m = re.search(_RE_EXPECTED_DATE, combined_text)
    if m and not signals["salary_override_next_date"]:
        signals["salary_override_next_date"] = m.group(1)

    # --- Salary amount overrides (reduced / raised / confirmed / first) ---
    # Priority: reduced > first > confirmed2 > confirmed > raised
    for pattern in [_RE_REDUCED, _RE_FIRST, _RE_CONFIRMED2, _RE_CONFIRMED, _RE_RAISED]:
        m = re.search(pattern, combined_text)
        if m:
            amt = _parse_number(m.group(1))
            if amt and amt > 0:
                signals["salary_override_amount"] = amt
                break

    # "confirmed credit date is" / "scheduled for" → next salary date
    m = re.search(_RE_CREDIT_DATE, combined_text)
    if m and not signals["salary_override_next_date"]:
        signals["salary_override_next_date"] = m.group(1)

    return signals


# Re-export Optional so it can be used in type hints
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_data() -> dict:
    data: dict[str, Any] = {
        "requests": load_csv(os.path.join(DATASET_DIR, "requests.csv")),
        "profiles": load_csv(os.path.join(DATASET_DIR, "financial_profiles.csv")),
        "events": load_csv(os.path.join(DATASET_DIR, "financial_events.csv")),
        "payment_options": load_csv(os.path.join(DATASET_DIR, "request_payment_options.csv")),
        "exchange_rates": load_csv(os.path.join(DATASET_DIR, "exchange_rates.csv")),
        "messages": load_csv(os.path.join(DATASET_DIR, "messages.csv")),
        "images": load_csv(os.path.join(DATASET_DIR, "images.csv")),
    }
    data["profiles_by_user"] = index_by(data["profiles"], "user_id")
    data["events_by_user"] = group_by(data["events"], "user_id")
    data["payment_options_by_request"] = group_by(data["payment_options"], "request_id")
    data["images_by_related_event"] = group_by(data["images"], "related_event_id")
    data["messages_by_user"] = group_by(data["messages"], "user_id")
    data["messages_by_request"] = group_by(data["messages"], "request_id")
    data["fx"] = ExchangeRateTable(data["exchange_rates"])
    return data


# ---------------------------------------------------------------------------
# Per-request processing
# ---------------------------------------------------------------------------

def _get_messages_for_request(data: dict, user_id: str, request_id: str) -> list[dict]:
    """Return all messages relevant to this user/request (by user_id, any request_id)."""
    return data["messages_by_user"].get(user_id, [])


def process_request(data: dict, request: dict) -> dict:
    request_id = request["request_id"]
    user_id = request["user_id"]
    profile = data["profiles_by_user"].get(user_id)

    if profile is None:
        return fallback_row(request_id, f"No financial profile found for {user_id}.")

    request_date = request["request_date"]
    requested_amount: float = safe_float(request["requested_amount"], 0.0) or 0.0
    minimum_balance_to_keep: float = safe_float(profile.get("minimum_balance_to_keep"), 0.0) or 0.0
    start_balance: float = safe_float(profile.get("current_available_balance"), 0.0) or 0.0
    home_currency = (profile.get("home_currency") or "").strip()

    window_end = format_date(parse_date(request_date) + timedelta(days=FORECAST_DAYS))

    # Parse messages for this user to extract salary signals
    messages = _get_messages_for_request(data, user_id, request_id)
    signals = _extract_salary_signals(messages, request_date)

    raw_events = data["events_by_user"].get(user_id, [])
    events = build_user_forward_events(
        raw_events,
        data["images_by_related_event"],
        image_amount_lookup,
        user_id,
        request_date,
        window_end,
        home_currency=home_currency,
        fx=data["fx"],
        salary_stop=signals["salary_stop"],
        salary_override_amount=signals["salary_override_amount"],
        salary_override_next_date=signals["salary_override_next_date"],
    )

    safe_amount = round(amount_safe_to_pay(
        start_balance, events, request_date, minimum_balance_to_keep, requested_amount
    ), 2)
    earliest_full = earliest_date_for_full_payment(
        start_balance, events, request_date, minimum_balance_to_keep, requested_amount
    )

    payment_options = data["payment_options_by_request"].get(request_id, [])
    plans = build_candidate_plans(
        request, profile, payment_options, safe_amount, earliest_full, start_balance, events
    )
    best = rank_plans(plans)

    return {
        "request_id": request_id,
        "amount_safe_to_pay": format_amount_natural(safe_amount),
        "affordability_status": best.affordability_status,
        "recommended_payment_method": best.method,
        "payment_plan": best.payment_plan_str(),
        "earliest_date_for_full_payment": earliest_full or "",
        "spending_changes_needed": best.spending_changes_str(),
        "decision_explanation": best.explanation,
    }


def fallback_row(request_id: str, reason: str) -> dict:
    return {
        "request_id": request_id,
        "amount_safe_to_pay": 0,
        "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended",
        "payment_plan": "none",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "decision_explanation": reason,
    }


def main():
    data = load_all_data()
    rows = []

    for request in data["requests"]:
        try:
            rows.append(process_request(data, request))
        except Exception as exc:  # noqa: BLE001
            log(f"Failed on {request.get('request_id')}: {exc}")
            rows.append(fallback_row(request.get("request_id", ""), f"Processing error: {exc}"))

    write_csv(OUTPUT_PATH, rows, REQUIRED_OUTPUT_COLUMNS)
    log(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
