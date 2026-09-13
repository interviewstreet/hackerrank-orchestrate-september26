"""Contract probes for Claude's next improvement pass; expected to fail before fixes."""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait import assist, model, recurrence
from buy_or_wait.data import load_dataset
from buy_or_wait.evidence import ProposedFact, available_candidates, parse_fact_amount, resolve_fact, retrieve_candidates
from tests import fixtures
from tests.test_engine import TODAY, event, profile


class EvidenceContractProbes(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = load_dataset(fixtures.build_dataset(Path(directory.name)))
        self.context = self.data.context_for("request_01")
        self.candidates = available_candidates(retrieve_candidates(self.context, self.data.events_by_id))

    def resolve(self, proposed):
        return resolve_fact(proposed, candidates=self.candidates, context=self.context,
                            events_by_id=self.data.events_by_id)

    def test_known_amount_amendment_still_requires_investigation(self):
        context = replace(self.context, events=tuple(
            replace(item, amount=item.amount if item.amount is not None else Decimal("500"))
            for item in self.context.events))
        message = replace(context.messages[0], related_event_id="event_01",
                          message_text="The next rent payment has been amended to EUR 600.")
        context = replace(context, messages=(message,))
        provider = model.FakeProvider()
        trace, facts = assist.extract_facts(context, self.data, assist.AssistConfig(provider=provider))
        self.assertGreater(len(provider.calls), 0, trace.provider_status)

    def test_structured_event_cannot_self_authorize_cancellation(self):
        fact = self.resolve(ProposedFact("cancelled", "event_01", "event", "true",
                                        source_ids=("event_01",)))
        self.assertEqual(fact.status, "rejected", "A settled debit is not proof that it was cancelled")

    def test_wrong_currency_amount_is_not_silently_applied(self):
        target = self.data.events_by_id["event_04"]
        currency = "USD" if target.currency != "USD" else "EUR"
        fact = self.resolve(ProposedFact("amount", target.event_id, "event", "100",
                                        currency=currency, source_ids=("message_01",)))
        self.assertEqual(fact.status, "rejected", "Currency mismatch requires explicit resolution")

    def test_user_level_scope_cannot_smuggle_an_event_target(self):
        fact = self.resolve(ProposedFact("amended_amount", "event_01", "user_level", "0",
                                        source_ids=("message_01",)))
        self.assertEqual(fact.status, "rejected", "user_level must not bypass target relevance checks")

    def test_multiple_numbers_are_not_concatenated_into_money(self):
        self.assertIsNone(parse_fact_amount("2 invoices of INR 500"))


class RecurrenceContractProbes(unittest.TestCase):
    def test_independent_salary_streams_are_not_merged(self):
        events = [event(f"primary_{offset}", direction="credit", category="salary",
                        description="Primary household salary", amount="1000",
                        on=TODAY-timedelta(days=offset)) for offset in (65, 35, 5)]
        events += [event(f"secondary_{offset}", direction="credit", category="salary",
                         description="Second household salary", amount="2000",
                         on=TODAY-timedelta(days=offset)) for offset in (80, 50, 20)]
        detected = recurrence.detect(events, profile(), TODAY, {})
        self.assertEqual(len([series for series in detected.fixed if series.direction == "credit"]), 2)

    def test_calendar_monthly_salary_stays_on_fifteenth(self):
        dates = [date(2023, 11, 15), date(2023, 12, 15), date(2024, 1, 15), date(2024, 2, 15)]
        events = [event(f"salary_{day}", direction="credit", category="salary", amount="4000",
                        description="Monthly payroll", on=day) for day in dates]
        detected = recurrence.detect(events, profile(), TODAY, {})
        predicted = detected.fixed[0].occurrences_between(TODAY, date(2024, 3, 31))
        self.assertEqual(predicted, [date(2024, 3, 15)])

    def test_historical_refunds_do_not_confirm_future_refunds(self):
        events = [event(f"refund_{offset}", direction="credit", category="other",
                        event_type="refund", amount="1000", description="Refund",
                        on=TODAY-timedelta(days=offset)) for offset in (35, 5)]
        detected = recurrence.detect(events, profile(), TODAY, {})
        self.assertEqual([series for series in detected.fixed if series.direction == "credit"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
