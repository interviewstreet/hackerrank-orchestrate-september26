from datetime import date, timedelta
import pandas as pd
import sys

sys.path.insert(0, 'code')
from forecast import (
    detect_recurring_streams,
    forecast_90_days,
    amount_safe_to_pay,
    earliest_full_payment_date,
)

def test_historical_income_not_repeated():
    # User with repeated historical settled salaries
    events = pd.DataFrame([
        {
            "event_id": "sal_1",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 3000.0,
            "currency": "USD",
            "event_date": "2025-10-15",
            "settlement_date": "2025-10-15",
            "status": "settled",
        },
        {
            "event_id": "sal_2",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 3000.0,
            "currency": "USD",
            "event_date": "2025-11-15",
            "settlement_date": "2025-11-15",
            "status": "settled",
        },
        {
            "event_id": "sal_3",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 3000.0,
            "currency": "USD",
            "event_date": "2025-12-15",
            "settlement_date": "2025-12-15",
            "status": "settled",
        },
    ])
    streams = detect_recurring_streams(
        events, request_date=date(2026, 1, 1), home_currency="USD", rate_lookup={}, skipped=[]
    )
    # MUST NOT contain any recurring stream for credit/salary
    for s in streams:
        assert s.direction == "debit", "Recurring streams must never be credit/income"

def test_confirmed_future_salary_inclusion():
    request = pd.Series({"request_id": "r1", "user_id": "u1", "request_date": "2026-01-01", "requested_amount": 500.0})
    profile = pd.Series({
        "user_id": "u1", "home_currency": "USD", "current_available_balance": 1000.0, "minimum_balance_to_keep": 200.0
    })
    events = pd.DataFrame([
        {
            "event_id": "future_sal",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 2500.0,
            "currency": "USD",
            "event_date": "2026-01-15",
            "settlement_date": "2026-01-15",
            "status": "scheduled",
        }
    ])
    res = forecast_90_days(request, profile, events)
    assert res.total_confirmed_income == 2500.0
    # Balance before salary is 1000, balance after Jan 15 should be 3500
    assert res.daily_closing_balances[date(2026, 1, 14)] == 1000.0
    assert res.daily_closing_balances[date(2026, 1, 15)] == 3500.0

def test_90_day_boundaries_and_min_balance():
    start = date(2026, 1, 1)
    request = pd.Series({"request_id": "r1", "user_id": "u1", "request_date": start.isoformat(), "requested_amount": 300.0})
    profile = pd.Series({
        "user_id": "u1", "home_currency": "USD", "current_available_balance": 500.0, "minimum_balance_to_keep": 250.0
    })
    events = pd.DataFrame([])
    res = forecast_90_days(request, profile, events)
    
    # Exactly 91 daily balances (day 0 to day 90 inclusive)
    assert len(res.daily_closing_balances) == 91
    assert min(res.daily_closing_balances.keys()) == start
    assert max(res.daily_closing_balances.keys()) == start + timedelta(days=90)
    
    # Safe amount boundaries
    safe_amt, f_res = amount_safe_to_pay(request, profile, events)
    # Available = 500, min = 250 => safe = 250 (which is <= requested 300)
    assert safe_amt == 250.0
    assert 0.0 <= safe_amt <= 300.0

def test_amount_safe_to_pay_capped_at_requested():
    start = date(2026, 1, 1)
    request = pd.Series({"request_id": "r1", "user_id": "u1", "request_date": start.isoformat(), "requested_amount": 100.0})
    profile = pd.Series({
        "user_id": "u1", "home_currency": "USD", "current_available_balance": 5000.0, "minimum_balance_to_keep": 200.0
    })
    events = pd.DataFrame([])
    safe_amt, f_res = amount_safe_to_pay(request, profile, events)
    # Even though surplus is 4800, safe amount must be capped at requested_amount (100.0)
    assert safe_amt == 100.0
