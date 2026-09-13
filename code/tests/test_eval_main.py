"""M4: evaluation-harness scoring for both deterministic and assisted modes.

`code/evaluation/main.py` must score exactly the row a submission would
publish -- it calls `main.predict_one`, the same per-row path `main.py`
publishes from -- and `--compare-baseline` must score the no-model baseline
on the identical request set, not a separately-computed one.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait.data import load_dataset  # noqa: E402
from evaluation import main as eval_main  # noqa: E402
from evaluation.labels import load_labels  # noqa: E402
from tests import fixtures  # noqa: E402


class ScoreDeterministicTests(unittest.TestCase):
    """`score()` against the fixture's one gold sample (`sample_01`)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dataset_dir = fixtures.build_dataset(Path(tmp.name))
        self.data = load_dataset(dataset_dir)
        self.labels = load_labels(dataset_dir / "sample_requests.csv")

    def test_scores_the_published_row_not_a_second_copy(self):
        from main import predict_one

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = eval_main.score(self.data, ["sample_01"], self.labels,
                                        mode="deterministic")
        self.assertEqual(exit_code, 0)

        expected = predict_one(self.data, "sample_01", mode="deterministic")["row"]
        gold = self.labels["sample_01"]
        expected_correct = 1 if expected["recommended_payment_method"] == \
            gold.recommended_payment_method else 0
        output = buf.getvalue()
        self.assertIn(f"recommended_payment_method: {expected_correct}/1", output)

    def test_assisted_mode_without_provider_matches_deterministic_score(self):
        buf_det, buf_assisted = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_det):
            eval_main.score(self.data, ["sample_01"], self.labels, mode="deterministic")
        with redirect_stdout(buf_assisted):
            eval_main.score(self.data, ["sample_01"], self.labels, mode="assisted",
                            assist_config=None)
        # Compare the numeric result lines directly rather than the header
        # label, since `score()`'s `label=` argument is cosmetic.
        det_lines = [l for l in buf_det.getvalue().splitlines() if ":" in l]
        assisted_lines = [l for l in buf_assisted.getvalue().splitlines() if ":" in l]
        self.assertEqual(det_lines, assisted_lines)


class CompareBaselineCliTests(unittest.TestCase):
    """CLI-level: `--mode assisted --compare-baseline` prints both sections.

    Uses the real `dataset/` and its already-frozen split manifest (the
    synthetic fixture has too few samples to form a dev/report split, and
    the manifest is only ever verified, never regenerated for a test)."""

    REAL_DATASET = Path(__file__).resolve().parents[2] / "dataset"

    def setUp(self):
        # This test asserts the no-provider fallback path. It must not rely
        # on the ambient environment happening to lack a real credential --
        # a developer's local .env (loaded automatically by evaluation/main.py
        # and main.py) could otherwise make this test reach the real
        # Anthropic API. Force the unconfigured state explicitly.
        self._old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        self.addCleanup(self._restore_key)

    def _restore_key(self):
        if self._old_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._old_key

    def test_compare_baseline_prints_assisted_and_baseline_sections(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = eval_main.main([
                "--dataset", str(self.REAL_DATASET),
                "--split", "dev",
                "--mode", "assisted",
                "--compare-baseline",
            ])
        output = buf.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("assisted mode provider status: unavailable", output)
        self.assertIn("------------------ ASSISTED ------------------", output)
        self.assertIn("BASELINE (deterministic, no model calls) FOR COMPARISON", output)
        self.assertIn("------------------ BASELINE ------------------", output)


if __name__ == "__main__":
    unittest.main()
