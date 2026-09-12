"""
Buy or Wait? — Phase 1 + Phase 2 MVP

Phase 1: load CSVs and inspect the first request.
Phase 2: run a deterministic 90-day cash forecast and a safer amount_safe_to_pay.

Run from the project root:
    python code/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from forecast import (  # noqa: E402
    amount_safe_to_pay,
    forecast_90_days,
    print_forecast_summary,
    run_phase2_tests,
    to_number,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"

REQUESTS_PATH = DATASET_DIR / "requests.csv"
PROFILES_PATH = DATASET_DIR / "financial_profiles.csv"
EVENTS_PATH = DATASET_DIR / "financial_events.csv"
SAMPLE_REQUESTS_PATH = DATASET_DIR / "sample_requests.csv"
EXCHANGE_RATES_PATH = DATASET_DIR / "exchange_rates.csv"


def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV file and fail clearly if it is missing or empty."""
    if not path.exists():
        raise FileNotFoundError(f"Required file is missing: {path}")

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV file is empty: {path}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"CSV file could not be parsed: {path}") from exc

    if df.empty:
        raise ValueError(f"CSV file has no data rows: {path}")

    return df


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def phase1_temporary_safe_amount(request: pd.Series, profile: pd.Series) -> float:
    """Keep the original Phase 1 surplus formula for comparison."""
    requested_amount = to_number(request["requested_amount"], "requested_amount")
    available_balance = to_number(
        profile["current_available_balance"], "current_available_balance"
    )
    minimum_balance_to_keep = to_number(
        profile["minimum_balance_to_keep"], "minimum_balance_to_keep"
    )
    raw_safe_amount = available_balance - minimum_balance_to_keep
    return max(0.0, min(raw_safe_amount, requested_amount))


def decide_from_safe_amount(safe_amount: float, requested_amount: float) -> tuple[str, str]:
    if safe_amount == requested_amount:
        return "affordable_now", "full_payment"
    if safe_amount > 0:
        return "affordable_with_plan", "partial_payment"
    return "not_affordable", "not_recommended"


def main() -> None:
    print("Loading dataset files...")
    requests_df = load_csv(REQUESTS_PATH)
    profiles_df = load_csv(PROFILES_PATH)
    events_df = load_csv(EVENTS_PATH)
    sample_requests_df = load_csv(SAMPLE_REQUESTS_PATH)
    exchange_rates_df = load_csv(EXCHANGE_RATES_PATH) if EXCHANGE_RATES_PATH.exists() else None

    print(f"Loaded requests: {len(requests_df)} rows")
    print(f"Loaded financial profiles: {len(profiles_df)} rows")
    print(f"Loaded financial events: {len(events_df)} rows")
    print(f"Loaded sample requests: {len(sample_requests_df)} rows")
    if exchange_rates_df is not None:
        print(f"Loaded exchange rates: {len(exchange_rates_df)} rows")

    first_request = requests_df.iloc[0]
    user_id = first_request["user_id"]

    print_section("SELECTED REQUEST (first row of requests.csv)")
    print(first_request.to_string())

    matching_profiles = profiles_df[profiles_df["user_id"] == user_id]
    if matching_profiles.empty:
        raise ValueError(f"No financial profile found for user_id: {user_id}")
    profile = matching_profiles.iloc[0]

    print_section(f"MATCHING PROFILE FOR {user_id}")
    print(profile.to_string())

    matching_events = events_df[events_df["user_id"] == user_id]
    if matching_events.empty:
        raise ValueError(f"No financial events found for user_id: {user_id}")

    print_section(f"MATCHING FINANCIAL EVENTS FOR {user_id} ({len(matching_events)} rows)")
    print(matching_events.to_string(index=False))

    requested_amount = to_number(first_request["requested_amount"], "requested_amount")
    available_balance = to_number(
        profile["current_available_balance"], "current_available_balance"
    )
    minimum_balance_to_keep = to_number(
        profile["minimum_balance_to_keep"], "minimum_balance_to_keep"
    )

    phase1_safe = phase1_temporary_safe_amount(first_request, profile)
    phase1_status, phase1_method = decide_from_safe_amount(phase1_safe, requested_amount)

    print_section("PHASE 1 TEMPORARY DECISION (balance minus minimum only)")
    print(f"current_available_balance : {available_balance}")
    print(f"minimum_balance_to_keep   : {minimum_balance_to_keep}")
    print(f"requested_amount          : {requested_amount}")
    print(f"amount_safe_to_pay        : {phase1_safe}")
    print(f"affordability_status      : {phase1_status}")
    print(f"recommended_payment_method: {phase1_method}")

    print_section("PHASE 2 ASSERTIONS")
    run_phase2_tests()

    print_section("PHASE 2 90-DAY FORECAST (no request payment)")
    unpaid = forecast_90_days(
        first_request,
        profile,
        matching_events,
        payment_on_request_date=0.0,
        exchange_rates=exchange_rates_df,
    )
    print_forecast_summary(unpaid)

    print_section("PHASE 2 AMOUNT SAFE TO PAY (includes future expenses)")
    safe_amount, paid_forecast = amount_safe_to_pay(
        first_request,
        profile,
        matching_events,
        exchange_rates=exchange_rates_df,
    )
    status, method = decide_from_safe_amount(safe_amount, requested_amount)
    print(f"amount_safe_to_pay        : {safe_amount}")
    print(f"affordability_status      : {status}")
    print(f"recommended_payment_method: {method}")
    print("Forecast after paying that amount on request_date:")
    print_forecast_summary(paid_forecast)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
    except KeyError as exc:
        print(f"Error: expected column is missing: {exc}")
        raise SystemExit(1) from exc
    except AssertionError as exc:
        print(f"Error: assertion failed: {exc}")
        raise SystemExit(1) from exc
