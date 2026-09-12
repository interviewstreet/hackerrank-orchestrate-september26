"""Tests verifying that dataset/output.csv exists and satisfies all competition contract rules."""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, "code")
from config import OUTPUT_PATH, DATASET_DIR
from evaluation.main import REQUIRED_COLUMNS, VALID_METHODS, VALID_STATUSES, validate_output_csv


def test_output_csv_existence():
    assert OUTPUT_PATH.exists(), f"output.csv not found at {OUTPUT_PATH}"
    df = pd.read_csv(OUTPUT_PATH)
    assert not df.empty, "output.csv is empty"


def test_output_csv_schema_and_columns():
    df = pd.read_csv(OUTPUT_PATH)
    assert list(df.columns) == REQUIRED_COLUMNS


def test_output_csv_row_count():
    requests_path = DATASET_DIR / "requests.csv"
    req_df = pd.read_csv(requests_path)
    out_df = pd.read_csv(OUTPUT_PATH)
    assert len(out_df) == len(req_df), f"Expected {len(req_df)} rows, got {len(out_df)}"


def test_output_csv_validation():
    errors = validate_output_csv(OUTPUT_PATH)
    assert not errors, f"output.csv validation errors: {errors}"
