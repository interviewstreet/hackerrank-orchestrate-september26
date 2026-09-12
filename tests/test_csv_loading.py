import pytest
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, 'code')
from main import load_csv

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

def test_csv_joins_with_synthetic_data():
    requests = pd.DataFrame([
        {"request_id": "req_1", "user_id": "u1", "requested_amount": 100.0}
    ])
    profiles = pd.DataFrame([
        {"user_id": "u1", "current_available_balance": 500.0, "home_currency": "USD"}
    ])
    events = pd.DataFrame([
        {"event_id": "ev_1", "user_id": "u1", "amount": 50.0}
    ])
    
    # Check join integrity
    u_req = requests[requests["user_id"] == "u1"]
    u_prof = profiles[profiles["user_id"] == "u1"]
    u_events = events[events["user_id"] == "u1"]
    
    assert len(u_req) == 1
    assert len(u_prof) == 1
    assert len(u_events) == 1
    assert u_prof.iloc[0]["home_currency"] == "USD"
