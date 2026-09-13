"""Input-boundary regressions for the M0 code review (R-M0-01 .. R-M0-07).

Every test here is a negative fixture: it constructs the specific malformed or
hostile input the review reproduced and asserts the loader or audit rejects it.
They are deliberately kept as independent probes -- if a future change makes one
pass for the wrong reason, the assertion text names the defect it guards.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.audit import ERROR, audit_dataset  # noqa: E402
from buy_or_wait.data import DataError, load_dataset, safe_media_path  # noqa: E402
from buy_or_wait.money import decimal_places, parse_decimal, quantize  # noqa: E402
from buy_or_wait.schema import RequestInput  # noqa: E402
from tests import fixtures  # noqa: E402


class BoundaryTestCase(unittest.TestCase):
    def build(self, **kwargs) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return fixtures.build_dataset(Path(tmp.name), **kwargs)

    def error_codes(self, dataset: Path) -> set[str]:
        return {f.code for f in audit_dataset(load_dataset(dataset)) if f.severity == ERROR}


class RowWidthTests(BoundaryTestCase):
    """R-M0-01: csv.DictReader tolerates malformed rows; we must not."""

    def _corrupt(self, filename: str, transform) -> Path:
        dataset = self.build()
        path = dataset / filename
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = transform(lines[1])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return dataset

    def test_surplus_cell_is_rejected(self):
        dataset = self._corrupt("financial_events.csv", lambda line: line + ",UNEXPECTED_CELL")
        with self.assertRaises(DataError) as ctx:
            load_dataset(dataset)
        self.assertIn("surplus", str(ctx.exception))

    def test_truncated_row_is_rejected(self):
        # A shifted/short row would otherwise back-fill a real obligation with a
        # blank, which the engine reads as "unknown" and the audit as resolvable.
        dataset = self._corrupt("financial_events.csv",
                                lambda line: ",".join(line.split(",")[:-2]))
        with self.assertRaises(DataError) as ctx:
            load_dataset(dataset)
        self.assertIn("truncated", str(ctx.exception))

    def test_truncated_message_text_is_rejected(self):
        dataset = self._corrupt("messages.csv", lambda line: ",".join(line.split(",")[:-1]))
        with self.assertRaises(DataError) as ctx:
            load_dataset(dataset)
        self.assertIn("truncated", str(ctx.exception))

    def test_error_names_the_file_and_row(self):
        dataset = self._corrupt("requests.csv", lambda line: line + ",X")
        with self.assertRaises(DataError) as ctx:
            load_dataset(dataset)
        self.assertIn("requests.csv:1", str(ctx.exception))


class MediaPathTests(BoundaryTestCase):
    """R-M0-02: an image id becomes a filesystem read; it must stay contained."""

    def test_traversal_id_is_rejected_at_load(self):
        for hostile in ("../../../outside", "..", "a/b", "a\\b", "/etc/passwd", "C:file", ""):
            with self.subTest(hostile=hostile):
                with self.assertRaises(DataError):
                    load_dataset(self.build(
                        mutate=fixtures.edit("images.csv", 0, image_id=hostile)))

    def test_safe_media_path_contains_the_resolved_path(self):
        dataset = self.build()
        media = dataset / "media" / "images"
        self.assertEqual(safe_media_path(media, "image_01").parent, media.resolve())
        for hostile in ("../../../outside", "sub/dir", ".."):
            with self.subTest(hostile=hostile), self.assertRaises(DataError):
                safe_media_path(media, hostile)

    def test_dataset_media_path_helper_is_contained(self):
        data = load_dataset(self.build())
        path = data.media_path(data.images[0])
        self.assertEqual(path.parent, data.media_dir.resolve())
        self.assertTrue(path.exists())


class CrossUserReferenceTests(BoundaryTestCase):
    """R-M0-03: existence of a request id is not proof of ownership."""

    def test_message_referencing_another_users_request_is_an_error(self):
        # message_01 belongs to user_01; sample_01 belongs to user_02.
        dataset = self.build(mutate=fixtures.edit("messages.csv", 0, request_id="sample_01"))
        self.assertIn("A13", self.error_codes(dataset))

    def test_image_referencing_another_users_request_is_an_error(self):
        dataset = self.build(mutate=fixtures.edit("images.csv", 0, request_id="sample_01"))
        self.assertIn("A13", self.error_codes(dataset))

    def test_same_user_request_reference_is_accepted(self):
        dataset = self.build(mutate=fixtures.edit("messages.csv", 0, request_id="request_01"))
        self.assertNotIn("A13", self.error_codes(dataset))

    def test_scoping_excludes_a_cross_user_reference(self):
        data = load_dataset(self.build(
            mutate=fixtures.edit("messages.csv", 0, request_id="sample_01")))
        context = data.context_for("sample_01")
        self.assertEqual([m.message_id for m in context.messages], [])


class RatePrecisionTests(BoundaryTestCase):
    """R-M0-04: supplied values must not be rounded at load time."""

    def test_high_precision_rate_is_preserved(self):
        data = load_dataset(self.build(
            mutate=fixtures.edit("exchange_rates.csv", 0, rate="20.12345")))
        rate = data.rates_by_key[(date(2024, 2, 15), "EUR", "ZAR")].rate
        self.assertEqual(rate, Decimal("20.12345"))
        self.assertNotEqual(rate, Decimal("20.12"))

    def test_high_precision_amount_is_preserved(self):
        data = load_dataset(self.build(
            mutate=fixtures.edit("financial_events.csv", 0, amount="1234.5678")))
        self.assertEqual(data.events_by_id["event_01"].amount, Decimal("1234.5678"))

    def test_parse_decimal_never_rounds(self):
        self.assertEqual(parse_decimal("1.005", field="x"), Decimal("1.005"))
        self.assertEqual(decimal_places(parse_decimal("20.12345", field="x")), 5)

    def test_quantize_is_the_separate_output_policy(self):
        self.assertEqual(quantize(Decimal("1.005")), Decimal("1.01"))

    def test_excess_source_precision_is_reported_not_silently_rounded(self):
        dataset = self.build(
            mutate=fixtures.edit("financial_events.csv", 0, amount="1234.5678"))
        findings = audit_dataset(load_dataset(dataset))
        self.assertIn("A14", {f.code for f in findings})
        self.assertNotIn("A14", self.error_codes(dataset))  # warning, not error


class MediaManifestTests(BoundaryTestCase):
    """R-M0-05: changed evidence bytes must change the manifest."""

    def test_media_bytes_are_hashed(self):
        data = load_dataset(self.build())
        self.assertIn("media/images/image_01.png", data.media_manifest)

    def test_changing_image_bytes_changes_the_manifest(self):
        dataset = self.build()
        before = load_dataset(dataset).media_manifest
        (dataset / "media" / "images" / "image_01.png").write_bytes(
            fixtures.PNG_BYTES + b"\n<!-- altered -->")
        after = load_dataset(dataset).media_manifest
        self.assertNotEqual(before, after)

    def test_csv_manifest_and_media_manifest_stay_distinct(self):
        data = load_dataset(self.build())
        self.assertEqual(set(data.manifest) & set(data.media_manifest), set())


class StrictDateTests(BoundaryTestCase):
    """R-M0-06: `date.fromisoformat` is strict on 3.10 but lenient on 3.11+.

    Validating the shape ourselves removes that interpreter dependence, so the
    loader rejects the same inputs everywhere.
    """

    def test_rejects_compact_and_week_dates(self):
        for bad in ("20240303", "2024-W09-7", "2024-063", "2024-3-3", "2024-03-03T00:00:00"):
            with self.subTest(bad=bad):
                with self.assertRaises(DataError) as ctx:
                    load_dataset(self.build(
                        mutate=fixtures.edit("requests.csv", 0, request_date=bad)))
                self.assertIn("is not a YYYY-MM-DD date", str(ctx.exception))

    def test_rejects_impossible_calendar_date(self):
        with self.assertRaises(DataError) as ctx:
            load_dataset(self.build(
                mutate=fixtures.edit("requests.csv", 0, request_date="2024-02-31")))
        self.assertIn("not a valid calendar date", str(ctx.exception))

    def test_accepts_the_contract_shape(self):
        data = load_dataset(self.build())
        self.assertEqual(data.requests[0].request_date, date(2024, 3, 3))


class ForgedRequestTests(BoundaryTestCase):
    """R-M0-07: request_context must not trust a caller-built request object."""

    def test_forged_user_pair_is_rejected(self):
        data = load_dataset(self.build())
        real = data.requests[0]
        forged = RequestInput(
            request_id=real.request_id, user_id="user_02", request_date=real.request_date,
            request_type=real.request_type, requested_amount=real.requested_amount,
            desired_completion_date=real.desired_completion_date,
            allows_partial_payment=real.allows_partial_payment, request_text=real.request_text,
        )
        with self.assertRaises(DataError) as ctx:
            data.request_context(forged)
        self.assertIn("does not match the loaded record", str(ctx.exception))

    def test_unknown_request_is_rejected(self):
        data = load_dataset(self.build())
        ghost = RequestInput(
            request_id="request_999", user_id="user_01", request_date=date(2024, 3, 3),
            request_type="purchase", requested_amount=Decimal("1"),
            desired_completion_date=date(2024, 3, 4), allows_partial_payment=False,
            request_text="",
        )
        with self.assertRaises(DataError):
            data.request_context(ghost)
        with self.assertRaises(DataError):
            data.context_for("request_999")

    def test_context_for_is_the_safe_entry_point(self):
        data = load_dataset(self.build())
        context = data.context_for("request_01")
        self.assertEqual(context.request.user_id, "user_01")
        self.assertEqual(context.profile.user_id, "user_01")
        self.assertTrue(all(o.request_id == "request_01" for o in context.payment_options))

    def test_request_owner_index(self):
        data = load_dataset(self.build())
        self.assertEqual(data.request_owner("request_01"), "user_01")
        self.assertEqual(data.request_owner("sample_01"), "user_02")
        self.assertIsNone(data.request_owner("request_999"))


class RealDatasetStillCleanTests(unittest.TestCase):
    """The hardened loader must not have broken the shipped dataset."""

    def test_real_dataset_loads_and_audits_clean(self):
        repo = Path(__file__).resolve().parents[2]
        if not (repo / "dataset").is_dir():
            self.skipTest("shipped dataset not present")
        data = load_dataset(repo / "dataset")
        failures = [f for f in audit_dataset(data) if f.severity == ERROR]
        self.assertEqual(failures, [], "\n".join(str(f) for f in failures))
        self.assertEqual(len(data.media_manifest), 16)


if __name__ == "__main__":
    unittest.main()
