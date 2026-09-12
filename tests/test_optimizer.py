from datetime import date
from code.src.models import (
    UserFinancialProfile,
    NormalizedFinancialEvent,
    SpendingChange,
)
from code.src.finance.optimizer import is_legal_spending_change


def test_cannot_modify_protected_category():
    prof = UserFinancialProfile(
        user_id="u1",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=1000.0,
        expense_categories_to_protect=["rent", "education"],
        expense_categories_user_is_willing_to_stop=["rent"],  # Conflict: rent is protected
    )
    ev = NormalizedFinancialEvent(
        event_id="e1",
        user_id="u1",
        event_type="expense",
        description="Rent",
        category="rent",
        direction="debit",
        amount=1000.0,
        currency="USD",
        converted_amount=1000.0,
        event_date=date(2024, 1, 1),
        settlement_date=date(2024, 1, 1),
        status="settled",
        flexibility="stoppable",
        is_recurring=True,
    )
    assert is_legal_spending_change(ev, prof, "stop") is False


def test_cannot_modify_fixed_expense():
    prof = UserFinancialProfile(
        user_id="u1",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=1000.0,
        expense_categories_user_is_willing_to_stop=["streaming"],
    )
    ev = NormalizedFinancialEvent(
        event_id="e1",
        user_id="u1",
        event_type="subscription",
        description="Streaming",
        category="streaming",
        direction="debit",
        amount=20.0,
        currency="USD",
        converted_amount=20.0,
        event_date=date(2024, 1, 1),
        settlement_date=date(2024, 1, 1),
        status="settled",
        flexibility="fixed",  # Event flexibility is fixed
        is_recurring=True,
    )
    assert is_legal_spending_change(ev, prof, "stop") is False


def test_cannot_reduce_below_minimum_allowed_amount():
    prof = UserFinancialProfile(
        user_id="u1",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=1000.0,
        expense_categories_user_is_willing_to_reduce=["dining"],
    )
    ev = NormalizedFinancialEvent(
        event_id="e1",
        user_id="u1",
        event_type="expense",
        description="Dining",
        category="dining",
        direction="debit",
        amount=100.0,
        currency="USD",
        converted_amount=100.0,
        event_date=date(2024, 1, 1),
        settlement_date=date(2024, 1, 1),
        status="settled",
        flexibility="reducible",
        minimum_allowed_amount=50.0,
        is_recurring=True,
    )
    # Trying to reduce to 30.0 (< 50.0)
    assert is_legal_spending_change(ev, prof, "reduce", new_amount=30.0) is False
    # Reducing to 60.0 (>= 50.0)
    assert is_legal_spending_change(ev, prof, "reduce", new_amount=60.0) is True
