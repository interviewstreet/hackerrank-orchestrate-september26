"""Unit tests for dataset loading, date parsing, numeric conversions, and indexing."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, "code")
from data import index_datasets, load_csv, parse_date, to_number


def test_parse_date():
    assert parse_date("2026-09-12") == date(2026, 9, 12)
    assert parse_date("2025-01-01T09:30:00Z") == date(2025, 1, 1)
    assert parse_date(date(2024, 5, 20)) == date(2024, 5, 20)
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("invalid-date") is None


def test_to_number():
    assert to_number(123) == 123.0
    assert to_number("1,234.56") == 1234.56
    assert to_number("42.0") == 42.0
    with pytest.raises(ValueError):
        to_number(None)
    with pytest.raises(ValueError):
        to_number("not-a-number")


def test_load_csv_valid(tmp_path: Path):
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text("col1,col2\n1,2\n3,4\n")
    df = load_csv(csv_file)
    assert len(df) == 2
    assert list(df.columns) == ["col1", "col2"]


def test_load_csv_missing(tmp_path: Path):
    missing_file = tmp_path / "non_existent.csv"
    with pytest.raises(FileNotFoundError):
        load_csv(missing_file)


def test_load_csv_empty(tmp_path: Path):
    empty_file = tmp_path / "empty.csv"
    empty_file.write_text("")
    with pytest.raises(ValueError):
        load_csv(empty_file)


def test_index_datasets():
    profiles = pd.DataFrame([
        {"user_id": "u1", "home_currency": "USD"},
        {"user_id": "u2", "home_currency": "EUR"},
    ])
    events = pd.DataFrame([
        {"event_id": "e1", "user_id": "u1", "amount": 10},
        {"event_id": "e2", "user_id": "u1", "amount": 20},
        {"event_id": "e3", "user_id": "u2", "amount": 30},
    ])
    options = pd.DataFrame([
        {"request_id": "r1", "payment_option_id": "opt1"},
    ])

    prof_map, events_map, opts_map = index_datasets(profiles, events, options)
    assert len(prof_map) == 2
    assert "u1" in prof_map
    assert len(events_map["u1"]) == 2
    assert len(events_map["u2"]) == 1
    assert len(opts_map["r1"]) == 1
