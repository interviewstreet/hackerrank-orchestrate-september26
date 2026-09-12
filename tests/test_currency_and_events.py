from datetime import date
import pandas as pd
import sys

sys.path.insert(0, 'code')
from forecast import (
    build_rate_lookup,
    convert_to_home_currency,
    should_ignore_row,
    explicit_cashflows,
)

def test_currency_conversion():
    rates_df = pd.DataFrame([
        {"rate_date": "2026-01-01", "from_currency": "EUR", "to_currency": "USD", "rate": 1.10},
        {"rate_date": "2026-01-02", "from_currency": "EUR", "to_currency": "USD", "rate": 1.12},
    ])
    lookup = build_rate_lookup(rates_df)
    
    # Same currency needs no lookup
    val_same = convert_to_home_currency(100.0, "USD", "USD", date(2026, 1, 1), lookup)
    assert val_same == 100.0
    
    # Dated conversion
    val_conv = convert_to_home_currency(100.0, "EUR", "USD", date(2026, 1, 1), lookup)
    assert round(val_conv, 2) == 110.0
    
    # Missing date/rate
    val_missing = convert_to_home_currency(100.0, "EUR", "USD", date(2026, 1, 3), lookup)
    assert val_missing is None

def test_ignored_event_statuses():
    # Cancelled
    row_cancelled = pd.Series({"status": "cancelled", "direction": "debit", "event_type": "expense"})
    assert should_ignore_row(row_cancelled) is True
    
    # Failed
    row_failed = pd.Series({"status": "failed", "direction": "debit", "event_type": "expense"})
    assert should_ignore_row(row_failed) is True
    
    # Unrealized
    row_unrealized = pd.Series({"status": "unrealized", "direction": "non_cash", "event_type": "investment_valuation"})
    assert should_ignore_row(row_unrealized) is True
    
    # Pending credit (must be ignored)
    row_pending_credit = pd.Series({"status": "pending", "direction": "credit", "event_type": "refund"})
    assert should_ignore_row(row_pending_credit) is True
    
    # Pending debit (must NOT be ignored - must be reserved)
    row_pending_debit = pd.Series({"status": "pending", "direction": "debit", "event_type": "expense"})
    assert should_ignore_row(row_pending_debit) is False
    
    # Settled debit (valid)
    row_settled = pd.Series({"status": "settled", "direction": "debit", "event_type": "expense"})
    assert should_ignore_row(row_settled) is False

def test_refund_and_linked_events():
    # Settled refund linked to earlier settled purchase
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
    # Pending refund must NOT appear in cash flows
    all_amounts = [amt for day_items in flows.values() for amt, _, _ in day_items]
    assert 100.0 not in all_amounts
    # Settled future refund MUST appear on its settlement date (positive credit)
    assert (50.0, "shopping", "ev_refund_settled_future") in flows[date(2026, 1, 10)]

def test_duplicate_events_ignored():
    events_df = pd.DataFrame([
        {
            "event_id": "ev_dup_1",
            "event_type": "expense",
            "category": "groceries",
            "direction": "debit",
            "amount": 45.0,
            "currency": "USD",
            "event_date": "2026-01-05",
            "settlement_date": "2026-01-05",
            "status": "settled",
        },
        {
            "event_id": "ev_dup_1",  # duplicate ID
            "event_type": "expense",
            "category": "groceries",
            "direction": "debit",
            "amount": 45.0,
            "currency": "USD",
            "event_date": "2026-01-05",
            "settlement_date": "2026-01-05",
            "status": "settled",
        },
    ])
    flows = explicit_cashflows(
        events_df,
        request_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
        home_currency="USD",
        rate_lookup={},
        skipped=[],
    )
    # Only one debit of -45.0 should be registered on 2026-01-05
    assert len(flows[date(2026, 1, 5)]) == 1
    assert flows[date(2026, 1, 5)][0][0] == -45.0
