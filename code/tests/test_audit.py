"""Cross-row dataset audit: clean fixtures pass, seeded defects are caught,
and the real shipped dataset is clean."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.audit import ERROR, audit_dataset, errors  # noqa: E402
from buy_or_wait.data import load_dataset  # noqa: E402
from tests import fixtures  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATASET = REPO_ROOT / "dataset"


class AuditTestCase(unittest.TestCase):
    def audit(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = fixtures.build_dataset(Path(tmp.name), **kwargs)
        return path, audit_dataset(load_dataset(path))

    def codes(self, findings, severity=ERROR) -> set[str]:
        return {f.code for f in findings if f.severity == severity}


class CleanFixtureTests(AuditTestCase):
    def test_clean_fixture_has_no_errors(self):
        _, findings = self.audit()
        self.assertEqual(errors(findings), [], "\n".join(str(f) for f in findings))


class SeededDefectTests(AuditTestCase):
    def test_a04_cross_user_link_is_caught(self):
        _, findings = self.audit(
            mutate=fixtures.edit("financial_events.csv", 5, linked_event_id="event_01"))
        self.assertIn("A04", self.codes(findings))

    def test_a04_dangling_link_is_caught(self):
        _, findings = self.audit(
            mutate=fixtures.edit("financial_events.csv", 0, linked_event_id="event_999"))
        self.assertIn("A04", self.codes(findings))

    def test_a04_self_link_is_caught(self):
        _, findings = self.audit(
            mutate=fixtures.edit("financial_events.csv", 0, linked_event_id="event_01"))
        self.assertIn("A04", self.codes(findings))

    def test_a04_link_cycle_terminates_and_is_caught(self):
        def cycle(name, rows):
            if name == "financial_events.csv":
                rows[0] = {**rows[0], "linked_event_id": "event_02"}
                rows[1] = {**rows[1], "linked_event_id": "event_01"}
            return rows

        _, findings = self.audit(mutate=cycle)   # must not hang
        self.assertIn("A04", self.codes(findings))

    def test_a05_too_few_payment_options(self):
        def drop(name, rows):
            if name == "request_payment_options.csv":
                return [r for r in rows if r["payment_option_id"] != "payment_option_02"]
            return rows

        _, findings = self.audit(mutate=drop)
        self.assertIn("A05", self.codes(findings))

    def test_a06_offer_arithmetic_is_not_silently_repaired(self):
        _, findings = self.audit(
            mutate=fixtures.edit("request_payment_options.csv", 1, total_payable_amount="9999"))
        self.assertIn("A06", self.codes(findings))

    def test_a07_unknown_amount_without_an_image_is_an_error(self):
        # The whole point: an unresolvable unknown debit must be visible, never
        # silently treated as zero.
        def drop_image(name, rows):
            return [] if name == "images.csv" else rows

        _, findings = self.audit(mutate=drop_image)
        self.assertIn("A07", self.codes(findings))

    def test_a08_missing_image_file_is_caught(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = fixtures.build_dataset(Path(tmp.name))
        (path / "media" / "images" / "image_01.png").unlink()
        findings = audit_dataset(load_dataset(path))
        self.assertIn("A08", self.codes(findings))

    def test_a09_message_referencing_another_users_event(self):
        _, findings = self.audit(
            mutate=fixtures.edit("messages.csv", 0, related_event_id="event_06"))
        self.assertIn("A09", self.codes(findings))

    def test_a10_missing_exact_fx_rate_is_an_error_not_a_fallback(self):
        # An earlier-dated rate must NOT satisfy a later settlement date.
        _, findings = self.audit(
            mutate=fixtures.edit("exchange_rates.csv", 0, rate_date="2024-01-15"))
        self.assertIn("A10", self.codes(findings))

    def test_a11_template_mismatch_is_caught(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = fixtures.build_dataset(Path(tmp.name))
        fixtures.write_table(path / "output.csv", "output.csv",
                             [{"request_id": "request_77", "amount_safe_to_pay": "",
                               "affordability_status": "", "recommended_payment_method": "",
                               "payment_plan": "", "earliest_date_for_full_payment": "",
                               "spending_changes_needed": "", "decision_explanation": ""}])
        findings = audit_dataset(load_dataset(path))
        self.assertIn("A11", self.codes(findings))


@unittest.skipUnless(REAL_DATASET.is_dir(), "shipped dataset not present")
class RealDatasetTests(unittest.TestCase):
    """The audit is only credible if it runs against the data we ship."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_dataset(REAL_DATASET)
        cls.findings = audit_dataset(cls.data)

    def test_no_errors(self):
        failures = errors(self.findings)
        self.assertEqual(failures, [], "\n".join(str(f) for f in failures))

    def test_expected_shape(self):
        self.assertEqual(len(self.data.requests), 250)
        self.assertEqual(len(self.data.sample_requests), 25)
        self.assertEqual(len(self.data.profiles), 275)
        self.assertEqual(len(self.data.events), 25342)
        self.assertEqual(len(self.data.payment_options), 790)
        self.assertEqual(len(self.data.messages), 215)
        self.assertEqual(len(self.data.images), 16)

    def test_sixteen_unknown_amounts_fifteen_of_them_debits(self):
        unknown = [e for e in self.data.events if e.amount_is_unknown]
        self.assertEqual(len(unknown), 16)
        self.assertEqual(sum(1 for e in unknown if e.direction == "debit"), 15)
        self.assertEqual(sum(1 for e in unknown if e.direction == "credit"), 1)

    def test_every_unknown_amount_has_a_linked_image(self):
        for event in self.data.events:
            if event.amount_is_unknown:
                self.assertIn(event.event_id, self.data.images_by_event, event.event_id)

    def test_every_foreign_event_resolves_on_an_exact_dated_rate(self):
        # This is what makes "exact settlement-date lookup, no fallback" a safe
        # rule rather than an aspiration.
        checked = 0
        for event in self.data.events:
            profile = self.data.profiles_by_user[event.user_id]
            if event.currency == profile.home_currency:
                continue
            checked += 1
            self.assertIn((event.cash_date, event.currency, profile.home_currency),
                          self.data.rates_by_key, event.event_id)
        self.assertEqual(checked, 140)

    def test_samples_and_evaluation_share_no_user(self):
        self.assertEqual(
            {r.user_id for r in self.data.requests} & {r.user_id for r in self.data.sample_requests},
            set(),
        )


if __name__ == "__main__":
    unittest.main()
