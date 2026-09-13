"""Loader strictness, request scoping, and label isolation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.data import DataError, load_dataset  # noqa: E402
from buy_or_wait.schema import RequestInput, SAMPLE_LABEL_COLUMNS  # noqa: E402
from evaluation.labels import find_leaked_columns, load_labels  # noqa: E402
from tests import fixtures  # noqa: E402


class LoaderTestCase(unittest.TestCase):
    def build(self, **kwargs) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return fixtures.build_dataset(Path(tmp.name), **kwargs)

    def load(self, **kwargs):
        return load_dataset(self.build(**kwargs))

    def assertRejects(self, fragment: str, **kwargs):
        with self.assertRaises(DataError) as ctx:
            self.load(**kwargs)
        self.assertIn(fragment, str(ctx.exception))


class HappyPathTests(LoaderTestCase):
    def test_loads_and_indexes(self):
        data = self.load()
        self.assertEqual(len(data.requests), 2)
        self.assertEqual(len(data.sample_requests), 1)
        self.assertEqual(set(data.requests_by_id), {"request_01", "request_02", "sample_01"})
        self.assertEqual(len(data.events), 6)
        self.assertEqual(data.profiles_by_user["user_01"].home_currency, "ZAR")
        self.assertEqual(data.events_by_id["event_02"].minimum_allowed_amount, Decimal("150"))

    def test_types_are_parsed_not_strings(self):
        request = self.load().requests[0]
        self.assertIsInstance(request.request_date, date)
        self.assertIsInstance(request.requested_amount, Decimal)
        self.assertIs(request.allows_partial_payment, True)

    def test_blank_amount_is_none_not_zero(self):
        event = self.load().events_by_id["event_04"]
        self.assertIsNone(event.amount)
        self.assertTrue(event.amount_is_unknown)

    def test_blank_optional_columns_become_none(self):
        data = self.load()
        self.assertIsNone(data.events_by_id["event_01"].linked_event_id)
        self.assertIsNone(data.profiles_by_user["user_02"].max_installment_months)
        self.assertEqual(data.profiles_by_user["user_02"].expense_categories_user_is_willing_to_stop, frozenset())

    def test_cash_date_prefers_settlement(self):
        data = self.load(mutate=fixtures.edit("financial_events.csv", 0, settlement_date="2024-02-05"))
        self.assertEqual(data.events_by_id["event_01"].cash_date, date(2024, 2, 5))

    def test_manifest_hashes_every_input(self):
        manifest = self.load().manifest
        self.assertIn("financial_events.csv", manifest)
        self.assertTrue(all(len(h) == 64 for h in manifest.values()))

    def test_row_order_does_not_change_parsed_records(self):
        def reverse(name, rows):
            return list(reversed(rows)) if name == "financial_events.csv" else rows

        normal = {e.event_id: e for e in self.load().events}
        shuffled = {e.event_id: e for e in self.load(mutate=reverse).events}
        self.assertEqual(normal, shuffled)


class StrictnessTests(LoaderTestCase):
    def test_rejects_unexpected_header(self):
        path = self.build()
        fixtures.write_table(
            path / "requests.csv", "requests.csv",
            [{"request_id": "request_01"}],
            header=("request_id",),
        )
        with self.assertRaises(DataError) as ctx:
            load_dataset(path)
        self.assertIn("unexpected header", str(ctx.exception))

    def test_rejects_duplicate_request_id(self):
        self.assertRejects("duplicate request_id", mutate=fixtures.append("requests.csv", dict(
            fixtures.ROWS["requests.csv"][0])))

    def test_rejects_duplicate_event_id(self):
        self.assertRejects("duplicate event_id", mutate=fixtures.append("financial_events.csv", dict(
            fixtures.ROWS["financial_events.csv"][0])))

    def test_rejects_missing_required_file(self):
        path = self.build()
        (path / "exchange_rates.csv").unlink()
        with self.assertRaises(DataError) as ctx:
            load_dataset(path)
        self.assertIn("missing required dataset file", str(ctx.exception))

    def test_rejects_invalid_decimal(self):
        self.assertRejects("not a valid decimal",
                           mutate=fixtures.edit("financial_events.csv", 0, amount="1,000"))

    def test_rejects_nan_amount(self):
        self.assertRejects("not finite",
                           mutate=fixtures.edit("financial_events.csv", 0, amount="NaN"))

    def test_rejects_invalid_date(self):
        self.assertRejects("is not a YYYY-MM-DD date",
                           mutate=fixtures.edit("requests.csv", 0, request_date="03/03/2024"))

    def test_rejects_unknown_enum(self):
        self.assertRejects("is not one of",
                           mutate=fixtures.edit("financial_events.csv", 0, category="crypto"))

    def test_rejects_non_literal_boolean(self):
        # A truthiness coercion here would silently flip partial-payment
        # eligibility on the 80 requests that permit it.
        for bad in ("1", "0", "yes", "y", "no", "", "null"):
            with self.subTest(bad=bad):
                self.assertRejects("is not 'true' or 'false'",
                                   mutate=fixtures.edit("requests.csv", 0, allows_partial_payment=bad))

    def test_boolean_case_is_a_formatting_difference_not_a_guess(self):
        # Case is normalized; anything else is a semantic guess and is rejected.
        for good, expected in (("TRUE", True), ("True", True), ("FALSE", False)):
            with self.subTest(good=good):
                data = self.load(mutate=fixtures.edit("requests.csv", 0,
                                                      allows_partial_payment=good))
                self.assertIs(data.requests[0].allows_partial_payment, expected)

    def test_rejects_completion_before_request_date(self):
        self.assertRejects("precedes request_date",
                           mutate=fixtures.edit("requests.csv", 0, desired_completion_date="2024-03-01"))

    def test_rejects_settlement_before_event_date(self):
        self.assertRejects("precedes event_date",
                           mutate=fixtures.edit("financial_events.csv", 0, settlement_date="2024-02-01"))

    def test_priorities_are_not_validated_against_event_categories(self):
        # `travel` is a real priority and not an event category. Cross-validating
        # the two vocabularies would reject 278 legitimate profile tokens.
        data = self.load()
        self.assertIn("travel", data.profiles_by_user["user_02"].financial_priorities)

    def test_unknown_priority_loads_because_priorities_authorize_nothing(self):
        # Contrast with test_rejects_unknown_changeable_category below: a
        # priority cannot unlock a payment method or permit a spending change,
        # so an unknown one is reported by the audit, not fatal at load.
        data = self.load(mutate=fixtures.edit("financial_profiles.csv", 0,
                                              financial_priorities="world_domination"))
        self.assertEqual(data.profiles_by_user["user_01"].financial_priorities,
                         ("world_domination",))

    def test_rejects_unknown_changeable_category(self):
        # This one DOES authorize an intervention, so it fails closed.
        self.assertRejects("is not one of",
                           mutate=fixtures.edit("financial_profiles.csv", 0,
                                                expense_categories_user_is_willing_to_stop="crypto"))

    def test_rejects_unknown_protected_category(self):
        self.assertRejects("is not one of",
                           mutate=fixtures.edit("financial_profiles.csv", 0,
                                                expense_categories_to_protect="crypto"))

    def test_rejects_sample_reusing_evaluation_request_id(self):
        self.assertRejects("reuses evaluation request_id",
                           mutate=fixtures.edit("sample_requests.csv", 0, request_id="request_01"))

    def test_rejects_multi_payment_offer_without_frequency(self):
        self.assertRejects("no payment_frequency_days",
                           mutate=fixtures.edit("request_payment_options.csv", 1,
                                                payment_frequency_days=""))


class ScopingTests(LoaderTestCase):
    def test_context_excludes_another_requests_message(self):
        data = self.load()
        context = data.request_context(data.requests[0])
        ids = {m.message_id for m in context.messages}
        # message_01 is user-level (blank request_id) -> included.
        # message_02 belongs to sample_01 -> must not leak into request_01.
        self.assertEqual(ids, {"message_01"})

    def test_context_carries_only_this_users_events(self):
        data = self.load()
        context = data.request_context(data.requests[0])
        self.assertTrue(all(e.user_id == "user_01" for e in context.events))
        self.assertNotIn("event_06", context.event_ids())

    def test_context_options_are_request_scoped(self):
        data = self.load()
        context = data.request_context(data.requests[0])
        self.assertEqual({o.payment_option_id for o in context.payment_options},
                         {"payment_option_01", "payment_option_02"})

    def test_missing_profile_is_an_error(self):
        data = self.load()
        orphan = RequestInput(
            request_id="request_99", user_id="user_99", request_date=date(2024, 3, 3),
            request_type="purchase", requested_amount=Decimal("1"),
            desired_completion_date=date(2024, 3, 4), allows_partial_payment=False,
            request_text="",
        )
        with self.assertRaises(DataError):
            data.request_context(orphan)


class LabelIsolationTests(LoaderTestCase):
    def test_request_input_has_no_label_field(self):
        # Structural half of the guarantee: there is nowhere to put a label.
        self.assertEqual(find_leaked_columns(RequestInput), [])
        self.assertEqual(
            set(RequestInput.__dataclass_fields__) & set(SAMPLE_LABEL_COLUMNS), set()
        )

    def test_loaded_sample_requests_carry_no_labels(self):
        sample = self.load().sample_requests[0]
        self.assertEqual(find_leaked_columns(sample), [])

    def test_request_context_exposes_no_labels(self):
        data = self.load()
        context = data.request_context(data.sample_requests[0])
        self.assertEqual(find_leaked_columns(context), [])

    def test_labels_are_reachable_only_through_the_evaluator(self):
        dataset = self.build()
        labels = load_labels(dataset / "sample_requests.csv")
        self.assertEqual(labels["sample_01"].affordability_status, "affordable_now")

    def test_engine_package_does_not_import_the_evaluator(self):
        engine = Path(__file__).resolve().parents[1] / "buy_or_wait"
        for module in sorted(engine.glob("*.py")):
            with self.subTest(module=module.name):
                text = module.read_text(encoding="utf-8")
                self.assertNotIn("import evaluation", text)
                self.assertNotIn("from evaluation", text)


if __name__ == "__main__":
    unittest.main()
