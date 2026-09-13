"""Offline reproductions of ADE findings; does not alter submission artifacts."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait import assist, evidence, forecast, model, recurrence, validation
from buy_or_wait.data import load_dataset
from buy_or_wait.planner import Payment
from evaluation.splits import SplitError, ensure_split
from tests.test_engine import TODAY, build, event, option, profile, request


def digest(content):
    return hashlib.sha256(content).hexdigest()


def measure():
    result = {}
    data = load_dataset(ROOT / "dataset")
    manifest = json.loads((ROOT / "code/evaluation/final/manifest.json").read_text())
    output = (ROOT / "output.csv").read_bytes()
    sample = (ROOT / "dataset/sample_requests.csv").read_bytes()
    result["artifacts"] = {
        "output_hash": digest(output),
        "output_matches_manifest": digest(output) == manifest["output_sha256"],
        "output_lf_hash": digest(output.replace(b"\r\n", b"\n")),
        "archive_exists": (ROOT / "code.zip").exists(),
        "sample_hash": digest(sample),
        "sample_lf_hash": digest(sample.replace(b"\r\n", b"\n")),
    }
    for name in ("trace.jsonl", "usage.json"):
        key = "trace_sha256" if name == "trace.jsonl" else "usage_sha256"
        result["artifacts"][name + "_matches_manifest"] = (
            digest((ROOT / "code/evaluation/final" / name).read_bytes()) == manifest[key])
    try:
        ensure_split([item.request_id for item in data.sample_requests],
                     digest(sample.replace(b"\r\n", b"\n")), allow_create=False)
        result["lf_split_rejected"] = False
    except SplitError:
        result["lf_split_rejected"] = True

    context = data.context_for("request_12")
    trace, _ = assist.extract_facts(context, data, assist.AssistConfig(provider=model.FakeProvider()))
    _, detected, _ = build(context.events, context.profile, data.rates_by_key, context.request.request_date)
    result["seasonal_example"] = {
        "provider_status": trace.provider_status,
        "projected_credit_series": [item.description for item in detected.fixed if item.direction == "credit"],
    }

    amendment = evidence.ExtractedFact("amended_amount", "event_01", "event", Decimal("100"),
                                       "ZAR", None, (), "accepted")
    cancellation = replace(amendment, field="cancelled", value=True)
    targets = {"event_01": event("event_01")}
    result["conflict_winners"] = [
        evidence._pick_winner(group, targets, {}).field
        for group in ((amendment, cancellation), (cancellation, amendment))]
    rate = recurrence._category_rates([(event("tiny", amount="0.50"), Decimal("0.50"))], 120)[0]
    result["tiny_daily_rate"] = str(rate.daily_amount)

    with tempfile.TemporaryDirectory() as directory:
        cache_path = Path(directory) / "cache.json"
        cache_path.write_text("{", encoding="utf-8")
        try:
            model.ExtractionCache(path=cache_path).load()
            result["corrupt_cache_exception"] = None
        except Exception as exc:
            result["corrupt_cache_exception"] = type(exc).__name__

    prof = profile(balance="2100", minimum="2000")
    req = request("1000")
    _, _, projected = build([], prof)
    decision = replace(validation.conservative_fallback(req, "probe"),
                       amount_safe_to_pay=Decimal("1000"), affordability_status="affordable_now",
                       recommended_payment_method="full_payment", payments=(Payment(TODAY, Decimal("1000")),),
                       earliest_date_for_full_payment=TODAY, degraded=False)
    result["unsafe_plan_gate_before_fault"] = [item.rule for item in validation.check(decision, req, prof, projected)]
    with patch.object(forecast.Forecast, "is_safe", return_value=True):
        result["unsafe_plan_gate_with_fault"] = [item.rule for item in validation.check(decision, req, prof, projected)]

    req = request("1000", deadline_days=120)
    prof = profile(balance="10000", methods=("installments",))
    _, _, projected = build([], prof)
    offer = option("late", amount="500", n=2, first=TODAY+timedelta(days=95), freq=10)
    decision = replace(validation.conservative_fallback(req, "probe"),
                       amount_safe_to_pay=Decimal("1000"), affordability_status="affordable_with_plan",
                       recommended_payment_method="installments", degraded=False,
                       chosen_payment_option_id="late",
                       payments=(Payment(offer.first_payment_date, Decimal("500")),
                                 Payment(offer.first_payment_date+timedelta(days=10), Decimal("500"))))
    result["outside_horizon_gate_failures"] = [item.rule for item in validation.check(decision, req, prof, projected, (offer,))]

    prof = profile(balance="3000")
    req = request("1000")
    _, _, projected = build([], prof)
    movement = forecast.CashMovement("projected:stream", TODAY+timedelta(days=1), Decimal("500"),
                                     "debit", "streaming", "Stream", "projected", "probe")
    projected = replace(projected, movements=(movement,))
    unrelated = replace(event("unrelated", category="streaming", description="Stream", flexibility="stoppable"),
                        user_id="another_user")
    decision = replace(validation.conservative_fallback(req, "probe"),
                       amount_safe_to_pay=Decimal("500"), affordability_status="affordable_with_plan",
                       recommended_payment_method="full_payment", payments=(Payment(TODAY, Decimal("1000")),),
                       spending_changes=("stop:unrelated",), degraded=False)
    result["unrelated_spending_event_gate_failures"] = [
        item.rule for item in validation.check(decision, req, prof, projected, events=(unrelated,))]
    return result


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
