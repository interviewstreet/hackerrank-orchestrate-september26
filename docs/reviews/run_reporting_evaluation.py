"""Run the frozen public reporting comparison with separately persisted usage."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import main as engine
from buy_or_wait import model
from buy_or_wait.assist import AssistConfig
from buy_or_wait.data import file_sha256, load_dataset
from evaluation.labels import load_labels, sample_exposure_note
from evaluation.main import score
from evaluation.splits import ensure_split


def run():
    data = load_dataset(ROOT / "dataset")
    split = ensure_split([request.request_id for request in data.sample_requests],
                         file_sha256(ROOT / "dataset/sample_requests.csv"))
    split.assert_disjoint()
    labels = load_labels(ROOT / "dataset/sample_requests.csv")
    provider = engine._build_provider()
    if provider is None:
        raise RuntimeError("Anthropic provider unavailable; reporting comparison was not run")
    provider._client = provider._client.with_options(max_retries=0, timeout=20.0)

    class LimitedProvider:
        model_id = provider.model_id
        attempts = 0

        def extract(self, request):
            if self.attempts >= 4:
                raise model.BudgetExceeded("Reporting evaluation maximum of four attempts reached")
            self.attempts += 1
            return provider.extract(request)

    limited = LimitedProvider()
    config = AssistConfig(provider=limited,
        caller=model.BoundedCaller(max_attempts_per_row=1, per_row_timeout_seconds=22),
        ledger=model.UsageLedger(full_run_call_budget=5, full_run_token_budget=20000))
    records = []
    import evaluation.main as evaluator
    original = evaluator.predict_one

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        records.append({"mode": kwargs.get("mode"), "row": result["row"],
                        "trace": result["trace"].to_json() if result["trace"] else None,
                        "crashed": result["crashed"]})
        return result

    evaluator.predict_one = record
    destination = ROOT / "code/evaluation/final/reporting"
    destination.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            print(sample_exposure_note())
            print("Frozen reporting subset; max 4 provider attempts, 20,000 returned tokens; SDK retries disabled.")
            score(data, split.report, labels, mode="assisted", assist_config=config, label="ASSISTED")
            score(data, split.report, labels, mode="deterministic", label="BASELINE")
    finally:
        evaluator.predict_one = original
        (destination / "results.txt").write_text(buffer.getvalue(), encoding="utf-8")
        (destination / "predictions.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        (destination / "usage.json").write_text(json.dumps({
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Anthropic", "requested_model": provider.model_id,
            "provider_attempts": limited.attempts, "total": config.ledger.total.as_dict(),
            "per_request": {key: value.as_dict() for key, value in config.ledger.per_request.items()},
            "separate_from_submission_run": True}, indent=2), encoding="utf-8")
    print(buffer.getvalue())
    print("Provider attempts:", limited.attempts)
    print("Recorded usage:", config.ledger.total.as_dict())
    statuses = [row["trace"]["provider_status"] for row in records if row["trace"]]
    print("Evidence statuses:", statuses)


if __name__ == "__main__":
    run()
