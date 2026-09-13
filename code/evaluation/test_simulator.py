"""Deterministic baseline simulator tests using only standard-library unittest."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait.cashflows import CashFlowNormalizer, ExchangeRateUnavailableError
from buy_or_wait.load import ExchangeRate, LoadedDataset, DatasetLoader
from buy_or_wait.models import Event, Profile, Request
from buy_or_wait.simulator import BaselineSimulator


DAY = date(2026, 1, 1)


def profile() -> Profile:
    return Profile("user", "USD", Decimal("100"), Decimal("50"), (), (), (), (), ("full_payment",), None)


def request() -> Request:
    return Request("request", "user", DAY, "purchase", Decimal("1"), DAY, False, "test")


def event(event_id: str, amount: str, direction: str, status: str = "settled", when: date = DAY, *, linked: str | None = None, currency: str = "USD", kind: str = "expense", description: str = "item") -> Event:
    return Event(event_id, "user", kind, description, "utilities", direction, Decimal(amount), currency, when, when, status, linked, "fixed", None)


def dataset(events: tuple[Event, ...], rates: tuple[ExchangeRate, ...] = ()) -> LoadedDataset:
    return LoadedDataset((request(),), (), (profile(),), events, rates, (), (), (), ("request",))


class BaselineSimulatorTests(unittest.TestCase):
    def simulate(self, events: tuple[Event, ...], rates: tuple[ExchangeRate, ...] = ()):  # type: ignore[no-untyped-def]
        return BaselineSimulator(CashFlowNormalizer(dataset(events, rates))).simulate(request())

    def test_event_statuses_directions_and_minimum_violation(self) -> None:
        events = (
            event("debit", "60", "debit"), event("credit", "10", "credit"),
            event("failed", "99", "debit", "failed"), event("cancelled", "99", "debit", "cancelled"),
            event("valuation", "99", "non_cash", "unrealized", kind="investment_valuation"),
            event("noncash", "99", "non_cash"), event("pending-credit", "99", "credit", "pending"),
            event("pending-debit", "5", "debit", "pending"),
        )
        result = self.simulate(events)
        self.assertEqual(Decimal("45"), result.daily_balances[0][1])
        self.assertTrue(result.violates_minimum_balance)
        self.assertEqual({"debit", "credit", "pending-debit"}, {flow.source_event_id for flow in result.normalized_cash_flows})

    def test_fx_both_directions_and_missing_rate(self) -> None:
        actual = DatasetLoader(ROOT / "dataset").load()
        normalizer = CashFlowNormalizer(actual)
        self.assertEqual((Decimal("10.90"), Decimal("1.09")), normalizer._convert(Decimal("10"), "EUR", "USD", date(2024, 4, 15), "fx"))
        self.assertEqual((Decimal("9.20"), Decimal("0.92")), normalizer._convert(Decimal("10"), "USD", "EUR", date(2024, 4, 15), "fx"))
        with self.assertRaises(ExchangeRateUnavailableError):
            normalizer._convert(Decimal("1"), "EUR", "USD", DAY, "missing")

    def test_recurring_expansion_is_bounded_and_not_duplicated(self) -> None:
        historical = (
            event("rent-1", "10", "debit", when=date(2025, 10, 1), description="rent"),
            event("rent-2", "10", "debit", when=date(2025, 11, 1), description="rent"),
            event("rent-3", "10", "debit", when=date(2025, 12, 1), description="rent"),
        )
        result = self.simulate(historical)
        self.assertEqual(90, len(result.daily_balances))
        self.assertEqual(date(2026, 3, 31), result.end_date)
        dates = [flow.flow_date for flow in result.normalized_cash_flows]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertTrue(all(flow.is_recurring for flow in result.normalized_cash_flows))

    def test_monthly_recurrence_preserves_calendar_day_across_short_month(self) -> None:
        historical = (
            event("rent-1", "10", "debit", when=date(2025, 10, 31), description="rent"),
            event("rent-2", "10", "debit", when=date(2025, 11, 30), description="rent"),
            event("rent-3", "10", "debit", when=date(2025, 12, 31), description="rent"),
        )
        request_at_new_year = Request("request", "user", date(2026, 1, 1), "purchase", Decimal("1"), date(2026, 1, 1), False, "test")
        result = BaselineSimulator(CashFlowNormalizer(dataset(historical))).simulate(request_at_new_year)
        self.assertEqual(
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)],
            [flow.flow_date for flow in result.normalized_cash_flows],
        )

    def test_same_day_order_is_deterministic_and_exact_linked_duplicate_is_not_counted_twice(self) -> None:
        events = (
            event("old", "10", "debit"), event("new", "10", "debit", linked="old"),
            event("credit", "5", "credit"),
        )
        first = self.simulate(events)
        second = self.simulate(events)
        self.assertEqual(first, second)
        self.assertEqual(Decimal("95"), first.daily_balances[0][1])
        self.assertEqual({"new", "credit"}, {flow.source_event_id for flow in first.normalized_cash_flows})

    def test_image_backed_pending_debit_enters_actual_simulation(self) -> None:
        actual = DatasetLoader(ROOT / "dataset").load()
        request_20 = next(item for item in actual.sample_requests if item.request_id == "request_20")
        result = BaselineSimulator(CashFlowNormalizer(actual)).simulate(request_20)
        linked = next(flow for flow in result.normalized_cash_flows if flow.source_event_id == "event_1786")
        self.assertEqual(Decimal("704.05"), linked.amount)
        self.assertEqual("debit", linked.direction)


if __name__ == "__main__":
    unittest.main()
