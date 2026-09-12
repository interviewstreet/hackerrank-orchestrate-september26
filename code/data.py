"""Data loading, pre-indexing, and type conversion helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATASET_DIR, EXCHANGE_RATES_PATH, MEDIA_DIR


def parse_date(date_val: Any) -> date | None:
    """Parse a date string or object into a datetime.date."""
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return None
    if isinstance(date_val, date):
        return date_val
    text = str(date_val).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def to_number(val: Any, name: str = "value") -> float:
    """Safely convert a number, string, or series item to a float."""
    if val is None:
        raise ValueError(f"{name} is missing")
    if isinstance(val, (int, float)):
        if pd.isna(val):
            raise ValueError(f"{name} is NaN")
        return float(val)
    text = str(val).strip().replace(",", "")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Cannot convert {name}={val!r} to float") from exc


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


def load_dataset_files(dataset_dir: Path = DATASET_DIR) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame | None,
]:
    """Load all challenge dataset CSVs."""
    requests_path = dataset_dir / "requests.csv"
    profiles_path = dataset_dir / "financial_profiles.csv"
    events_path = dataset_dir / "financial_events.csv"
    options_path = dataset_dir / "request_payment_options.csv"
    rates_path = dataset_dir / "exchange_rates.csv"

    requests_df = load_csv(requests_path)
    profiles_df = load_csv(profiles_path)
    events_df = load_csv(events_path)
    options_df = load_csv(options_path) if options_path.exists() else pd.DataFrame()
    rates_df = load_csv(rates_path) if rates_path.exists() else None

    return requests_df, profiles_df, events_df, options_df, rates_df


def index_datasets(
    profiles_df: pd.DataFrame,
    events_df: pd.DataFrame,
    options_df: pd.DataFrame,
) -> tuple[
    dict[str, pd.Series],
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
]:
    """Pre-index profiles, events, and options by user/request key for fast lookup."""
    profiles_by_user = {
        str(row["user_id"]): row for _, row in profiles_df.iterrows()
    }
    events_by_user = {
        str(uid): group for uid, group in events_df.groupby("user_id")
    }
    options_by_req = {
        str(rid): group for rid, group in options_df.groupby("request_id")
    } if not options_df.empty else {}

    return profiles_by_user, events_by_user, options_by_req
