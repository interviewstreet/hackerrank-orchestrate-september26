"""Decimal money: parsing, rejection, and the dataset's rendering convention."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.money import (  # noqa: E402
    MoneyError,
    decimal_places,
    format_amount,
    parse_decimal,
    quantize,
)


class ParseDecimalTests(unittest.TestCase):
    def test_parses_exactly_without_float_error(self):
        self.assertEqual(parse_decimal("1302.40", field="x"), Decimal("1302.40"))
        # The classic binary-float failure: 0.1 + 0.2 != 0.3.
        total = parse_decimal("0.10", field="a") + parse_decimal("0.20", field="b")
        self.assertEqual(total, parse_decimal("0.30", field="c"))

    def test_blank_is_unknown_not_zero(self):
        self.assertIsNone(parse_decimal("", field="amount", allow_blank=True))
        self.assertIsNone(parse_decimal("   ", field="amount", allow_blank=True))
        self.assertNotEqual(parse_decimal("", field="amount", allow_blank=True), Decimal("0"))

    def test_blank_rejected_where_required(self):
        with self.assertRaises(MoneyError):
            parse_decimal("", field="requested_amount")

    def test_rejects_nan_inf_and_garbage(self):
        for bad in ("NaN", "nan", "Infinity", "-Infinity", "inf", "abc", "1,000", "1.2.3", "--5"):
            with self.subTest(bad=bad), self.assertRaises(MoneyError):
                parse_decimal(bad, field="amount")

    def test_rejects_negative_because_sign_lives_in_direction(self):
        with self.assertRaises(MoneyError):
            parse_decimal("-10.00", field="amount")


class PrecisionPolicyTests(unittest.TestCase):
    """Parsing preserves; only the output policy rounds (review R-M0-04)."""

    def test_parsing_never_rounds(self):
        self.assertEqual(parse_decimal("1.005", field="x"), Decimal("1.005"))
        self.assertEqual(parse_decimal("20.12345", field="rate"), Decimal("20.12345"))

    def test_quantize_is_separate_and_rounds_half_up(self):
        self.assertEqual(quantize(Decimal("1.005")), Decimal("1.01"))
        self.assertEqual(quantize(Decimal("2.344")), Decimal("2.34"))

    def test_decimal_places_reports_as_written(self):
        self.assertEqual(decimal_places(Decimal("1.50")), 2)
        self.assertEqual(decimal_places(Decimal("20.12345")), 5)
        self.assertEqual(decimal_places(Decimal("25256")), 0)


class FormatAmountTests(unittest.TestCase):
    def test_strips_trailing_zeros_like_the_dataset(self):
        # Measured from dataset/sample_requests.csv gold values.
        self.assertEqual(format_amount(Decimal("603.30")), "603.3")
        self.assertEqual(format_amount(Decimal("25256.00")), "25256")
        self.assertEqual(format_amount(Decimal("17229139.20")), "17229139.2")
        self.assertEqual(format_amount(Decimal("166.61")), "166.61")

    def test_never_uses_scientific_notation(self):
        # Decimal.normalize() would render this as 1.5656E+7 and corrupt IDR.
        rendered = format_amount(Decimal("15656000"))
        self.assertEqual(rendered, "15656000")
        self.assertNotIn("E", rendered.upper())

    def test_zero_renders_as_zero(self):
        self.assertEqual(format_amount(Decimal("0")), "0")
        self.assertEqual(format_amount(Decimal("0.00")), "0")

    def test_round_trip_through_parse(self):
        for text in ("603.3", "25256", "17229139.2", "166.61", "0"):
            with self.subTest(text=text):
                self.assertEqual(format_amount(parse_decimal(text, field="x")), text)


if __name__ == "__main__":
    unittest.main()
