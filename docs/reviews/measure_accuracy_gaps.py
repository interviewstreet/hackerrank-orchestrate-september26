"""Measure coverage and DEV forecast diagnostics without reading reporting labels."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait import forecast, recurrence, state
from buy_or_wait.data import load_dataset
from buy_or_wait.evidence import available_candidates, retrieve_candidates


def measure():
    data = load_dataset(ROOT / "dataset")
    traces = {row["request_id"]: row for row in [json.loads(line) for line in
        (ROOT / "code/evaluation/final/trace.jsonl").read_text().splitlines()]}
    result = {"evaluation_requests": len(data.requests), "messages_present_but_extraction_skipped": [],
              "excluded_images": [], "unlinked_messages": 0, "credit_categories_projected": Counter(),
              "exact_confirmed_projected_debit_collisions": [], "dev_diagnostics": []}
    for request in data.requests:
        context = data.context_for(request.request_id)
        refs = retrieve_candidates(context, data.events_by_id)
        available = available_candidates(refs)
        messages = [message for message in context.messages if message.message_id in available]
        if messages and traces[request.request_id]["provider_status"] == "skipped: no unresolved amounts":
            result["messages_present_but_extraction_skipped"].append(request.request_id)
        result["unlinked_messages"] += sum(message.related_event_id is None for message in messages)
        for image in context.images:
            ref = next(ref for ref in refs if ref.ref_id == image.image_id)
            if not ref.available:
                event = data.events_by_id[image.related_event_id]
                result["excluded_images"].append({"request": request.request_id, "image": image.image_id,
                    "event": event.event_id, "status": event.status, "direction": event.direction,
                    "unknown_amount": event.amount is None, "reason": ref.unavailable_reason})
        cash = state.reconstruct(context.events, context.profile, request.request_date, data.rates_by_key)
        rec = recurrence.detect(context.events, context.profile, request.request_date, data.rates_by_key)
        timeline = forecast.build(cash, rec, request.request_date)
        for series in rec.fixed:
            if series.direction == "credit":
                result["credit_categories_projected"][series.category] += 1
        confirmed = {(movement.on_date, movement.category, movement.description, movement.amount_home)
                     for movement in timeline.movements if movement.source == "confirmed" and movement.direction == "debit"}
        for movement in timeline.movements:
            if movement.source == "projected" and movement.direction == "debit" and (
                movement.on_date, movement.category, movement.description, movement.amount_home) in confirmed:
                result["exact_confirmed_projected_debit_collisions"].append({"request": request.request_id,
                    "category": movement.category, "date": str(movement.on_date), "amount": str(movement.amount_home)})
    dev = json.loads((ROOT / "code/evaluation/split_manifest.json").read_text())["dev"]
    for request_id in dev:
        context = data.context_for(request_id)
        cash = state.reconstruct(context.events, context.profile, context.request.request_date, data.rates_by_key)
        rec = recurrence.detect(context.events, context.profile, context.request.request_date, data.rates_by_key)
        result["dev_diagnostics"].append({"request": request_id,
            "messages": [{"id": message.message_id, "event_link": message.related_event_id, "text": message.message_text}
                         for message in context.messages],
            "unknown_events": [event.event_id for event in context.events if event.amount is None],
            "income_series": [{"category": series.category, "period_days": series.period_days,
                               "amount": str(series.amount_home), "last_seen": str(series.last_seen)}
                              for series in rec.fixed if series.direction == "credit"],
            "daily_spend": {rate.category: str(rate.daily_amount) for rate in rec.rates}})
    (ROOT / "docs/reviews/ACCURACY_GAP_MEASUREMENTS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: (len(value) if isinstance(value, list) else value) for key, value in result.items()}, indent=2))
    print(json.dumps(result["excluded_images"], indent=2))
    print(json.dumps(result["dev_diagnostics"], indent=2))


if __name__ == "__main__":
    measure()
