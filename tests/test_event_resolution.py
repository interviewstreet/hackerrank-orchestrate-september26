from datetime import date
from code.src.models import FinancialEvent
from code.src.finance.lifecycle import resolve_event_lifecycle
from code.src.finance.recurrence import generate_missing_recurrences


def test_lifecycle_drops_cancelled_and_failed():
    events = [
        FinancialEvent(
            event_id="e1",
            user_id="u1",
            event_type="expense",
            description="Card authorization",
            category="shopping",
            direction="debit",
            amount=100.0,
            currency="USD",
            event_date=date(2024, 1, 1),
            settlement_date=date(2024, 1, 1),
            status="cancelled",
            flexibility="fixed",
        ),
        FinancialEvent(
            event_id="e2",
            user_id="u1",
            event_type="expense",
            description="Settled purchase",
            category="shopping",
            direction="debit",
            amount=100.0,
            currency="USD",
            event_date=date(2024, 1, 2),
            settlement_date=date(2024, 1, 2),
            status="settled",
            linked_event_id="e1",
            flexibility="fixed",
        ),
    ]
    resolved = resolve_event_lifecycle(events)
    assert len(resolved) == 1
    assert resolved[0].event_id == "e2"


def test_lifecycle_excludes_unrealized_and_pending_credits():
    events = [
        FinancialEvent(
            event_id="e_inv",
            user_id="u1",
            event_type="investment_valuation",
            description="Portfolio valuation",
            category="investment",
            direction="non_cash",
            amount=5000.0,
            currency="USD",
            event_date=date(2024, 1, 1),
            settlement_date=date(2024, 1, 1),
            status="unrealized",
            flexibility="fixed",
        ),
        FinancialEvent(
            event_id="e_ref",
            user_id="u1",
            event_type="refund",
            description="Pending merchant refund",
            category="shopping",
            direction="credit",
            amount=200.0,
            currency="USD",
            event_date=date(2024, 1, 1),
            settlement_date=date(2024, 1, 1),
            status="pending",
            flexibility="fixed",
        ),
    ]
    resolved = resolve_event_lifecycle(events)
    assert len(resolved) == 0


def test_recurrence_prevents_duplicate_future_events():
    # Historical rent
    hist = [
        FinancialEvent(
            event_id="e_h1",
            user_id="u1",
            event_type="expense",
            description="Apartment rent",
            category="rent",
            direction="debit",
            amount=1000.0,
            currency="USD",
            event_date=date(2024, 1, 1),
            settlement_date=date(2024, 1, 1),
            status="settled",
            flexibility="fixed",
        ),
        FinancialEvent(
            event_id="e_h2",
            user_id="u1",
            event_type="expense",
            description="Apartment rent",
            category="rent",
            direction="debit",
            amount=1000.0,
            currency="USD",
            event_date=date(2024, 2, 1),
            settlement_date=date(2024, 2, 1),
            status="settled",
            flexibility="fixed",
        ),
    ]
    # Explicit future rent on March 1
    explicit_future = [
        FinancialEvent(
            event_id="e_fut1",
            user_id="u1",
            event_type="expense",
            description="Apartment rent",
            category="rent",
            direction="debit",
            amount=1000.0,
            currency="USD",
            event_date=date(2024, 3, 1),
            settlement_date=date(2024, 3, 1),
            status="scheduled",
            flexibility="fixed",
        )
    ]

    recs = generate_missing_recurrences(
        historical_events=hist,
        request_date=date(2024, 2, 15),
        horizon_days=60,
        explicit_future_events=explicit_future,
        user_home_currency="USD",
    )

    # Recurrence engine should NOT generate March rent because explicit_future has March rent!
    march_recs = [r for r in recs if r.settlement_date.month == 3]
    assert len(march_recs) == 0
    # April rent should be generated
    april_recs = [r for r in recs if r.settlement_date.month == 4]
    assert len(april_recs) == 1
