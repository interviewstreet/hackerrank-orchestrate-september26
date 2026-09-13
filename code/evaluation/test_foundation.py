"""Lightweight standard-library tests for the typed input foundation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait.images import IMAGE_EVIDENCE_AMOUNTS
from buy_or_wait.load import DatasetLoader


class FoundationTests(unittest.TestCase):
    def test_reviewed_image_mapping_has_16_entries(self) -> None:
        self.assertEqual(16, len(IMAGE_EVIDENCE_AMOUNTS))
        self.assertEqual("704.05", str(IMAGE_EVIDENCE_AMOUNTS["event_1786"][0]))

    def test_actual_dataset_loads_and_resolves_image_amounts(self) -> None:
        dataset = DatasetLoader(ROOT / "dataset").load()
        self.assertEqual(250, len(dataset.requests))
        self.assertEqual(275, len(dataset.profiles))
        self.assertEqual(16, sum(event.amount_from_image_evidence for event in dataset.events))


if __name__ == "__main__":
    unittest.main()
