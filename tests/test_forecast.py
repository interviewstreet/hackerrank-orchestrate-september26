"""Comprehensive tests for 90-day cash forecasting, currency conversion, and event filtering."""

from __future__ import annotations

import sys
from datetime import date, timedelta
import pandas as pd
import pytest

sys.path.insert(0, "code")
from forecast import (
    amount_safe_to_pay,
    build_rate_lookup,
    convert_to_home_currency,
    detect_recurring_streams,
    earliest_full_payment_date,
    explicit_cashflows,
    forecast_90_days,
    should_ignore_row,
)


def test_currency_conversion():
    rates_df = pd.DataFrame([
        {"rate_date": "2026-01-01", "from_currency": "EUR", "to_currency": "USD", "rate": 1.10},
        {"rate_date": "2026-01-02", "from_currency": "EUR", "to_currency": "USD", "rate": 1.12},
    ])
    lookup = build_rate_lookup(rates_df)

    val_same = convert_to_home_currency(100.0, "USD", "USD", date(2026, 1, 1), lookup)
    assert val_same == 100.0

    val_conv = convert_to_home_currency(100.0, "EUR", "USD", date(2026, 1, 1), lookup)
    assert round(val_conv, 2) == 110.0

    val_missing = convert_to_home_currency(100.0, "EUR", "USD", date(2026, 1, 3), lookup)
    assert val_missing is None


def test_ignored_event_statuses():
    assert should_ignore_row(pd.Series({"status": "cancelled", "direction": "debit"})) is True
    assert should_ignore_row(pd.Series({"status": "failed", "direction": "debit"})) is True
    assert should_ignore_row(pd.Series({"status": "unrealized", "direction": "non_cash"})) is True
    assert should_ignore_row(pd.Series({"status": "pending", "direction": "credit"})) is True
    assert should_ignore_row(pd.Series({"status": "pending", "direction": "debit"})) is False
    assert should_ignore_row(pd.Series({"status": "settled", "direction": "debit"})) is False


def test_refund_and_linked_events():
    events_df = pd.DataFrame([
        {
            "event_id": "ev_buy",
            "event_type": "expense",
            "category": "shopping",
            "direction": "debit",
            "amount": 100.0,
            "currency": "USD",
            "event_date": "2026-01-01",
            "settlement_date": "2026-01-01",
            "status": "settled",
            "linked_event_id": None,
        },
        {
            "event_id": "ev_refund_pending",
            "event_type": "refund",
            "category": "shopping",
            "direction": "credit",
            "amount": 100.0,
            "currency": "USD",
            "event_date": "2026-01-02",
            "settlement_date": "2026-01-05",
            "status": "pending",
            "linked_event_id": "ev_buy",
        },
        {
            "event_id": "ev_refund_settled_future",
            "event_type": "refund",
            "category": "shopping",
            "direction": "credit",
            "amount": 50.0,
            "currency": "USD",
            "event_date": "2026-01-02",
            "settlement_date": "2026-01-10",
            "status": "settled",
            "linked_event_id": "ev_buy",
        },
    ])
    skipped = []
    flows = explicit_cashflows(
        events_df,
        request_date=date(2026, 1, 2),
        end_date=date(2026, 4, 2),
        home_currency="USD",
        rate_lookup={},
        skipped=skipped,
    )
    all_amounts = [amt for day_items in flows.values() for amt, _, _ in day_items]
    assert 100.0 not in all_amounts
    assert (50.0, "shopping", "ev_refund_settled_future") in flows[date(2026, 1, 10)]


def test_historical_income_not_repeated():
    events = pd.DataFrame([
        {"event_id": f"sal_{i}", "event_type": "income", "category": "salary", "direction": "credit",
         "amount": 3000.0, "currency": "USD", "event_date": f"2025-1{i}-15", "settlement_date": f"2025-1{i}-15", "status": "settled"}
        for i in range(3)
    ])
    streams = detect_recurring_streams(
        events, request_date=date(2026, 1, 1), home_currency="USD", rate_lookup={}, skipped=[]
    )
    for s in streams:
        assert s.direction == "debit", "Recurring streams must never be credit/income"


def test_historical_salary_no_future_cashflow():
    start = date(2026, 1, 1)
    request = pd.Series({"request_id": "r1", "user_id": "u1", "request_date": start.isoformat(), "requested_amount": 500.0})
    profile = pd.Series({
        "user_id": "u1", "home_currency": "USD", "current_available_balance": 1000.0, "minimum_balance_to_keep": 200.0
    })
    events = pd.DataFrame([
        {"event_id": f"past_sal_{i}", "event_type": "income", "category": "salary", "direction": "credit",
         "amount": 3000.0, "currency": "USD", "event_date": f"2025-{10+i}-15", "settlement_date": f"2025-{10+i}-15", "status": "settled"}
        for i in range(3)
    ])
    res = forecast_90_days(request, profile, events)
    assert res.total_confirmed_income == 0.0
    for d, bal in res.daily_closing_balances.items():
        assert bal == 1000.0, f"Balance changed unexpectedly on {d}: {bal}"


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

    assert len(res.daily_closing_balances) == 91
    assert min(res.daily_closing_balances.keys()) == start
    assert max(res.daily_closing_balances.keys()) == start + timedelta(days=90)

    safe_amt, f_res = amount_safe_to_pay(request, profile, events)
    assert safe_amt == 250.0
    assert 0.0 <= safe_amt <= 300.0
