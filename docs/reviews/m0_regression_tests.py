"""Independent M0 review probes; run explicitly, outside the implementation suite.

Run: py -3.12 -B docs/reviews/m0_regression_tests.py
The assertions express the required behavior and fail on the reviewed M0 build.
All mutations occur in temporary synthetic datasets.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

CODE_DIRECTORY = Path(__file__).resolve().parents[2] / "code"
sys.path.insert(0, str(CODE_DIRECTORY))

from buy_or_wait.audit import audit_dataset, errors
from buy_or_wait.data import DataError, load_dataset, parse_date_value
from tests import fixtures


class M0RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temporary_root = Path(self.temporary_directory.name)
        self.dataset_path = fixtures.build_dataset(self.temporary_root)
        message_rows = [dict(row) for row in fixtures.ROWS["messages.csv"]]
        message_rows[1]["request_id"] = "request_01"
        fixtures.write_table(
            self.dataset_path / "messages.csv", "messages.csv", message_rows
        )
        self.assertEqual(errors(audit_dataset(load_dataset(self.dataset_path))), [])

    def rewrite_csv_rows(self, filename, change):
        csv_path = self.dataset_path / filename
        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        change(rows)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)

    def test_exchange_rate_preserves_source_precision(self):
        rate_rows = [dict(row) for row in fixtures.ROWS["exchange_rates.csv"]]
        rate_rows[0]["rate"] = "20.12345"
        fixtures.write_table(
            self.dataset_path / "exchange_rates.csv", "exchange_rates.csv", rate_rows
        )
        dataset = load_dataset(self.dataset_path)
        loaded_rate = next(
            rate for rate in dataset.exchange_rates if rate.from_currency == "EUR"
        )
        self.assertEqual(loaded_rate.rate, Decimal("20.12345"))

    def test_extra_csv_cell_is_rejected(self):
        self.rewrite_csv_rows(
            "financial_events.csv", lambda rows: rows[1].append("UNEXPECTED_CELL")
        )
        with self.assertRaises(DataError):
            load_dataset(self.dataset_path)

    def test_truncated_message_row_is_rejected(self):
        self.rewrite_csv_rows("messages.csv", lambda rows: rows[1].pop())
        with self.assertRaises(DataError):
            load_dataset(self.dataset_path)

    def test_request_reference_must_belong_to_message_user(self):
        def change_request(rows):
            request_column = rows[0].index("request_id")
            rows[1][request_column] = "sample_01"

        self.rewrite_csv_rows("messages.csv", change_request)
        try:
            dataset = load_dataset(self.dataset_path)
        except DataError:
            return
        self.assertTrue(
            errors(audit_dataset(dataset)),
            "A user_01 message referencing user_02's request must fail validation",
        )

    def test_image_path_cannot_escape_dataset_media_root(self):
        external_image = self.temporary_root / "outside.png"
        external_image.write_bytes(fixtures.PNG_BYTES)
        image_rows = [dict(row) for row in fixtures.ROWS["images.csv"]]
        image_rows[0]["image_id"] = "../../../outside"
        fixtures.write_table(
            self.dataset_path / "images.csv", "images.csv", image_rows
        )
        try:
            dataset = load_dataset(self.dataset_path)
        except DataError:
            return
        self.assertTrue(
            errors(audit_dataset(dataset)),
            "Image references outside the supplied media directory must be rejected",
        )

    def test_media_manifest_changes_when_image_content_changes(self):
        original_manifest = dict(load_dataset(self.dataset_path).media_manifest)
        image_path = self.dataset_path / "media" / "images" / "image_01.png"
        image_path.write_bytes(image_path.read_bytes() + b"changed evidence content")
        changed_manifest = dict(load_dataset(self.dataset_path).media_manifest)
        self.assertNotEqual(original_manifest, changed_manifest)

    def test_date_requires_contract_calendar_format(self):
        with self.assertRaises(DataError):
            parse_date_value("2024-W09-7", where="request_date")


if __name__ == "__main__":
    unittest.main(verbosity=2)
