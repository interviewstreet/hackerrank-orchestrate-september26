"""
Buy or Wait? — Phase 1 MVP

This script loads the dataset CSVs, inspects the first request,
and prints a temporary safe-amount decision.

Run from the project root:
    python code/main.py
"""

from pathlib import Path

import pandas as pd


# Paths work when the command is run from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"

REQUESTS_PATH = DATASET_DIR / "requests.csv"
PROFILES_PATH = DATASET_DIR / "financial_profiles.csv"
EVENTS_PATH = DATASET_DIR / "financial_events.csv"
SAMPLE_REQUESTS_PATH = DATASET_DIR / "sample_requests.csv"


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


def to_number(value, field_name: str) -> float:
    """Convert a CSV value to a number, with a clear error if it is invalid."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {field_name}: {value!r}") from exc

    if pd.isna(number):
        raise ValueError(f"Missing numeric value for {field_name}")

    return number


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def main() -> None:
    print("Loading dataset files...")
    requests_df = load_csv(REQUESTS_PATH)
    profiles_df = load_csv(PROFILES_PATH)
    events_df = load_csv(EVENTS_PATH)
    sample_requests_df = load_csv(SAMPLE_REQUESTS_PATH)

    print(f"Loaded requests: {len(requests_df)} rows")
    print(f"Loaded financial profiles: {len(profiles_df)} rows")
    print(f"Loaded financial events: {len(events_df)} rows")
    print(f"Loaded sample requests: {len(sample_requests_df)} rows")

    # Phase 1 uses only the first evaluation request.
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

    # Temporary Phase 1 formula. Full 90-day forecasting comes later.
    raw_safe_amount = available_balance - minimum_balance_to_keep
    safe_amount = max(0.0, min(raw_safe_amount, requested_amount))

    if safe_amount == requested_amount:
        affordability_status = "affordable_now"
        recommended_payment_method = "full_payment"
    elif safe_amount > 0:
        affordability_status = "affordable_with_plan"
        recommended_payment_method = "partial_payment"
    else:
        affordability_status = "not_affordable"
        recommended_payment_method = "not_recommended"

    print_section("PHASE 1 TEMPORARY DECISION")
    print(f"current_available_balance : {available_balance}")
    print(f"minimum_balance_to_keep   : {minimum_balance_to_keep}")
    print(f"requested_amount          : {requested_amount}")
    print(f"raw surplus               : {raw_safe_amount}")
    print(f"amount_safe_to_pay        : {safe_amount}")
    print(f"affordability_status      : {affordability_status}")
    print(f"recommended_payment_method: {recommended_payment_method}")


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
