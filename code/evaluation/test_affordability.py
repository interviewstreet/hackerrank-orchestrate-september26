"""Tests for deterministic baseline affordability capacity only."""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait.cashflows import CashFlowNormalizer
from buy_or_wait.load import ExchangeRate, LoadedDataset
from buy_or_wait.models import Event, Message, Profile, Request
from buy_or_wait.simulator import BaselineAffordabilityCalculator, BaselineSimulator


DAY = date(2026, 1, 1)


def make_request(amount: str = "50") -> Request:
    return Request("r", "u", DAY, "purchase", Decimal(amount), date(2025, 12, 1), False, "")


def make_event(
    event_id: str, amount: str, direction: str, when: date, *, status: str = "settled",
    currency: str = "USD", description: str = "item", category: str = "utilities",
) -> Event:
    return Event(event_id, "u", "income" if direction == "credit" else "expense", description,
                 category, direction, Decimal(amount), currency, when, when, status, None, "fixed", None)


def make_dataset(
    balance: str, minimum: str, events: tuple[Event, ...] = (), *, amount: str = "50",
    rates: tuple[ExchangeRate, ...] = (), messages: tuple[Message, ...] = (),
) -> LoadedDataset:
    request = make_request(amount)
    profile = Profile("u", "USD", Decimal(balance), Decimal(minimum), (), (), (), (), ("full_payment",), None)
    return LoadedDataset((request,), (), (profile,), events, rates, (), messages, (), ("r",))


def calculate(dataset: LoadedDataset):  # type: ignore[no-untyped-def]
    return BaselineAffordabilityCalculator(BaselineSimulator(CashFlowNormalizer(dataset))).calculate(dataset.requests[0])


class BaselineAffordabilityTests(unittest.TestCase):
    def test_full_request_is_safe_today_and_capped_to_request(self) -> None:
        result = calculate(make_dataset("200", "50", amount="80"))
        self.assertEqual(Decimal("80"), result.amount_safe_to_pay)
        self.assertEqual(DAY, result.earliest_date_for_full_payment)

    def test_nothing_is_safe_when_baseline_is_already_below_minimum(self) -> None:
        result = calculate(make_dataset("50", "50", (make_event("bill", "10", "debit", DAY),)))
        self.assertEqual(Decimal("0"), result.amount_safe_to_pay)
        self.assertIsNone(result.earliest_date_for_full_payment)

    def test_partial_safe_payment_accounts_for_later_expense(self) -> None:
        result = calculate(make_dataset("150", "50", (make_event("bill", "30", "debit", date(2026, 1, 20)),), amount="100"))
        self.assertEqual(Decimal("70"), result.amount_safe_to_pay)
        self.assertIsNone(result.earliest_date_for_full_payment)

    def test_future_confirmed_income_makes_full_payment_safe_later(self) -> None:
        result = calculate(make_dataset("100", "50", (make_event("salary", "100", "credit", date(2026, 1, 10)),), amount="120"))
        self.assertEqual(Decimal("50"), result.amount_safe_to_pay)
        self.assertEqual(date(2026, 1, 10), result.earliest_date_for_full_payment)

    def test_later_payment_is_not_rejected_by_an_earlier_baseline_violation(self) -> None:
        result = calculate(make_dataset("50", "50", (
            make_event("overdue-bill", "10", "debit", DAY),
            make_event("salary", "100", "credit", date(2026, 1, 2)),
        ), amount="50"))
        self.assertEqual(Decimal("0"), result.amount_safe_to_pay)
        self.assertEqual(date(2026, 1, 2), result.earliest_date_for_full_payment)

    def test_same_day_flows_are_posted_before_the_proposed_payment(self) -> None:
        result = calculate(make_dataset("100", "50", (make_event("salary", "30", "credit", DAY),), amount="80"))
        self.assertEqual(Decimal("80"), result.amount_safe_to_pay)
        self.assertEqual(DAY, result.earliest_date_for_full_payment)

    def test_fractional_decimal_capacity_is_exact(self) -> None:
        result = calculate(make_dataset("100.005", "50.001", (make_event("bill", "10.002", "debit", date(2026, 1, 2)),), amount="99.999"))
        self.assertEqual(Decimal("40.002"), result.amount_safe_to_pay)

    def test_foreign_currency_cash_flow_uses_existing_fx_conversion(self) -> None:
        rate_date = date(2026, 1, 2)
        rates = (ExchangeRate(rate_date, "EUR", "USD", Decimal("1.5")),)
        result = calculate(make_dataset("200", "50", (make_event("eur-bill", "40", "debit", rate_date, currency="EUR"),), amount="100", rates=rates))
        self.assertEqual(Decimal("90.0"), result.amount_safe_to_pay)

    def test_evidence_amended_recurring_salary_changes_capacity(self) -> None:
        history = tuple(make_event(f"salary-{month}", "100", "credit", date(2025, month, 1), description="salary", category="salary") for month in (10, 11, 12))
        message = Message("m", "u", None, None, datetime(2026, 1, 2, tzinfo=timezone.utc), "employer", "Your monthly salary has increased to USD 200. The change applies from 2026-01-15.")
        result = calculate(make_dataset("50", "0", history, amount="200", messages=(message,)))
        self.assertEqual(date(2026, 2, 1), result.earliest_date_for_full_payment)

    def test_recurring_expense_can_reduce_safe_today_capacity(self) -> None:
        bills = tuple(make_event(f"bill-{month}", "20", "debit", date(2025, month, 1), description="rent") for month in (10, 11, 12))
        result = calculate(make_dataset("120", "50", bills, amount="60"))
        self.assertEqual(Decimal("10"), result.amount_safe_to_pay)

    def test_desired_completion_date_does_not_change_baseline_capacity(self) -> None:
        data = make_dataset("100", "50", (make_event("salary", "100", "credit", date(2026, 1, 10)),), amount="120")
        changed_request = Request("r", "u", DAY, "purchase", Decimal("120"), DAY, False, "")
        changed = LoadedDataset((changed_request,), (), data.profiles, data.events, data.exchange_rates, (), (), (), ("r",))
        self.assertEqual(calculate(data), calculate(changed))

    def test_suffix_algorithm_matches_explicit_candidate_simulations(self) -> None:
        data = make_dataset("100", "50", (
            make_event("bill", "20", "debit", date(2026, 1, 3)),
            make_event("salary", "100", "credit", date(2026, 1, 8)),
        ), amount="80")
        simulator = BaselineSimulator(CashFlowNormalizer(data))
        result = BaselineAffordabilityCalculator(simulator).calculate(data.requests[0])
        expected = next(
            (candidate for candidate in (DAY + timedelta(days=offset) for offset in range(90))
             if not simulator.simulate(data.requests[0], proposed_payment=Decimal("80"), payment_date=candidate).violates_minimum_balance),
            None,
        )
        self.assertEqual(expected, result.earliest_date_for_full_payment)


if __name__ == "__main__":
    unittest.main()
