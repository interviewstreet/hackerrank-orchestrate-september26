import pytest
from pathlib import Path
from datetime import date
from code.src.data.repository import DataRepository
from code.src.config import DATASET_DIR


@pytest.fixture
def repo():
    return DataRepository(DATASET_DIR)


def test_data_loading_counts(repo):
    assert len(repo.requests) >= 250
    assert len(repo.profiles) == 275
    assert len(repo.events_by_user) == 275
    assert len(repo.options_by_request) >= 250


def test_profile_fields(repo):
    p = repo.get_profile("user_01")
    assert p is not None
    assert p.home_currency == "ZAR"
    assert p.current_available_balance > 0
    assert p.minimum_balance_to_keep == 18000.0
    assert "rent" in p.expense_categories_to_protect
    assert "dining" in p.expense_categories_user_is_willing_to_reduce
    assert "delivery_membership" in p.expense_categories_user_is_willing_to_stop


def test_exchange_rate_lookup(repo):
    # Same currency
    assert repo.get_exchange_rate("ZAR", "ZAR", date(2024, 1, 1)) == 1.0
    # EUR to ZAR rate
    rate = repo.get_exchange_rate("EUR", "ZAR", date(2023, 10, 15))
    assert rate == 20.0
