"""Deadline-handoff Block 1 item 3: an unhandled programming error must never
overwrite a previously published `output.csv`.

`predict_one` already degrades *expected* unavailable evidence (unfunded
obligations, missing rates, etc.) to the conservative fallback without
raising. A genuine unhandled exception is a different class of failure: it
means the row could not be trusted to represent the engine's actual output,
so publishing over a good prior file would silently discard a working
submission artifact. `run_predictions` must instead leave the destination
untouched and report failure.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as main_module  # noqa: E402
from tests import fixtures  # noqa: E402

SENTINEL = "request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation\nprevious_run,1,affordable_now,full_payment,none,2024-01-01,none,previous good run\n"


class UnhandledErrorPreservesPriorOutputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dataset_dir = fixtures.build_dataset(Path(tmp.name) / "dataset")
        self.out_path = Path(tmp.name) / "output.csv"
        self.out_path.write_text(SENTINEL, encoding="utf-8")

        self.original_decide_one = main_module.decide_one

        def faulty_decide_one(context, rates):
            if context.request.request_id == "request_02":
                raise RuntimeError("simulated programming error")
            return self.original_decide_one(context, rates)

        main_module.decide_one = faulty_decide_one
        self.addCleanup(setattr, main_module, "decide_one", self.original_decide_one)

    def test_crashed_row_blocks_publication_and_preserves_prior_file(self):
        exit_code = main_module.run_predictions(
            self.dataset_dir, self.out_path, mode="deterministic",
            limit=None, quiet=True,
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.out_path.read_text(encoding="utf-8"), SENTINEL)

    def test_clean_run_still_publishes(self):
        main_module.decide_one = self.original_decide_one
        exit_code = main_module.run_predictions(
            self.dataset_dir, self.out_path, mode="deterministic",
            limit=None, quiet=True,
        )
        self.assertEqual(exit_code, 0)
        self.assertNotEqual(self.out_path.read_text(encoding="utf-8"), SENTINEL)


if __name__ == "__main__":
    unittest.main()
