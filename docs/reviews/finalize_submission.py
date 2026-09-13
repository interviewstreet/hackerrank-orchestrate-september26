"""Validate and package the recorded submission without regenerating predictions."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait.data import load_dataset
from buy_or_wait.evidence import ExtractedFact, RowTrace, apply_facts_to_events, citation_note
from buy_or_wait.output import to_row
from buy_or_wait.schema import OUTPUT_COLUMNS
from main import decide_one

RUN_ID = "20260913T041036Z"
RUN = ROOT / "code/evaluation/runs" / RUN_ID
FINAL = ROOT / "code/evaluation/final"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_fact(record):
    values = dict(record)
    if values["field"] in ("amount", "amended_amount"):
        values["value"] = Decimal(values["value"])
    elif values["field"] == "cancelled":
        values["value"] = values["value"] == "True"
    values["value_date"] = date.fromisoformat(values["value_date"]) if values["value_date"] else None
    values["source_ids"] = tuple(values["source_ids"])
    return ExtractedFact(**values)


def finalize():
    data = load_dataset(ROOT / "dataset")
    with (ROOT / "output.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames) != OUTPUT_COLUMNS:
            raise ValueError("Output header mismatch")
        rows = list(reader)
    expected_ids = [request.request_id for request in data.requests]
    if [row["request_id"] for row in rows] != expected_ids or len(set(expected_ids)) != len(rows):
        raise ValueError("Output IDs/order/count mismatch")
    traces = [json.loads(line) for line in (RUN / "trace.jsonl").read_text().splitlines()]
    if [trace["request_id"] for trace in traces] != expected_ids:
        raise ValueError("Trace IDs/order mismatch")
    citation_count = 0
    degraded = []
    for row, trace in zip(rows, traces):
        context = data.context_for(row["request_id"])
        sources = {source.message_id: source for source in context.messages}
        sources.update({source.image_id: source for source in context.images})
        sources.update({event.event_id: event for event in context.events})
        accepted = tuple(read_fact(record) for record in trace["accepted"])
        for fact in accepted:
            for source_id in fact.source_ids:
                if source_id not in trace["retrieved"] or source_id not in sources:
                    raise ValueError(f"{row['request_id']}: invalid citation {source_id}")
        cited = set(re.findall(r"(?:message|image)_\d+", row["decision_explanation"]))
        allowed = {source_id for fact in accepted for source_id in fact.source_ids}
        if not cited <= allowed:
            raise ValueError(f"{row['request_id']}: unsupported output citation")
        citation_count += len(cited)
        context = replace(context, events=apply_facts_to_events(context.events, accepted))
        decision, failures = decide_one(context, data.rates_by_key)
        if failures:
            raise ValueError(f"{row['request_id']}: replay gate failures: {failures}")
        reproduced = to_row(decision, context.profile.home_currency,
                            context.request.requested_amount, context.profile.minimum_balance_to_keep)
        note = citation_note(RowTrace(row["request_id"], tuple(trace["retrieved"]), accepted=accepted))
        if note:
            reproduced["decision_explanation"] += " " + note
        if reproduced != row:
            raise ValueError(f"{row['request_id']}: output does not reproduce from recorded facts")
        if decision.degraded:
            degraded.append(row["request_id"])
    usage = json.loads((RUN / "usage.json").read_text())
    for field, value in usage["total"].items():
        if sum(record[field] for record in usage["per_request"].values()) != value:
            raise ValueError(f"Usage totals disagree for {field}")
    FINAL.mkdir(parents=True, exist_ok=True)
    for filename in ("usage.json", "trace.jsonl"):
        (FINAL / filename).write_bytes((RUN / filename).read_bytes())
    total = usage["total"]
    tokens = total["input_tokens"] + total["output_tokens"]
    cost = (Decimal(total["input_tokens"]) * 2 + Decimal(total["output_tokens"]) * 10) / 1_000_000
    summary = {
        "run_id": RUN_ID, "validated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows), "output_sha256": digest(ROOT / "output.csv"),
        "input_csv_sha256": data.manifest, "input_media_sha256": data.media_manifest,
        "trace_sha256": digest(FINAL / "trace.jsonl"), "usage_sha256": digest(FINAL / "usage.json"),
        "code_sha256_at_validation": {str(path.relative_to(ROOT)): digest(path)
            for directory in (ROOT / "code/buy_or_wait", ROOT / "code/prompts")
            for path in directory.rglob("*") if path.is_file() and path.suffix in (".py", ".md")},
        "entry_point_sha256": digest(ROOT / "code/main.py"),
        "split_manifest_sha256": digest(ROOT / "code/evaluation/split_manifest.json"),
        "method_distribution": dict(Counter(row["recommended_payment_method"] for row in rows)),
        "degraded_request_ids": degraded, "cited_source_references": citation_count,
        "accepted_facts": sum(len(trace["accepted"]) for trace in traces),
        "rejected_facts": sum(len(trace["rejected"]) for trace in traces),
        "provider_status_counts": dict(Counter(trace["provider_status"] for trace in traces)),
        "validation_scope": "Exact row reproduction, existing financial replay gate, citation existence/scope; not independent semantic proof of extraction or forecast accuracy",
        "provenance_limit": "Input/code hashes captured at finalization; original run did not record a code revision or returned model identifier"
    }
    (FINAL / "manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = f"""# Final full-dataset usage report

Run: `{RUN_ID}` (2026-09-13 04:10:36 UTC); 250 evaluation requests.
Provider: Anthropic Claude API. Requested model: `claude-sonnet-5`.
The original ledger does not record the response model ID; the requested ID
is corroborated by the extraction cache and provider configuration.

| Metric | Final run |
|---|---:|
| Recorded successful model calls | {total['calls']} |
| Input tokens | {total['input_tokens']} |
| Output tokens | {total['output_tokens']} |
| Total tokens | {tokens} |
| Average input tokens / request | {total['input_tokens'] / len(rows):.3f} |
| Average output tokens / request | {total['output_tokens'] / len(rows):.3f} |
| Average total tokens / request | {tokens / len(rows):.3f} |
| Cache read / write tokens | {total['cache_read_tokens']} / {total['cache_write_tokens']} |
| Estimated total cost (USD) | {cost:.6f} |
| Estimated cost / request (USD) | {cost / len(rows):.9f} |

Estimate: input tokens x $2/million + output tokens x $10/million, using
[Anthropic's published pricing](https://platform.claude.com/docs/en/about-claude/pricing)
verified 2026-09-13. The pricing page explicitly states the earlier planned
September increase did not occur. Taxes/account discounts are excluded;
this is a list-price estimate, not an invoice.

Configured run limits: {usage['full_run_call_budget']} calls / {usage['full_run_token_budget']} tokens.
The legacy ledger counts returned usage, not every transport attempt; SDK retries
and usage of interrupted attempts are not independently accounted. The token
limit is checked after responses and is not a guaranteed dollar spending cap.
No extraction-cache hits appear in this run's traces.

{summary['accepted_facts']} accepted facts; {summary['rejected_facts']} rejected facts;
{len(degraded)} degraded rows: {', '.join(degraded)}. All 250 rows reproduce from
their recorded accepted facts and pass the existing planner gate. This does not
prove all extracted facts or forecasts are semantically correct. Extraction is
currently triggered only for unknown amounts; message-only amendments on other
rows are not investigated by this version.

Output SHA-256: `{summary['output_sha256']}`.
Run trace, original usage, and finalization-time input/code hashes are preserved
under `evaluation/final/`. Public-sample evaluation usage is reported separately
and excluded from the above final full-dataset totals. Public samples have prior
development exposure and are not an unseen holdout.
"""
    (ROOT / "code/evaluation/usage_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("rows", "output_sha256", "degraded_request_ids", "accepted_facts", "rejected_facts")}))


if __name__ == "__main__":
    finalize()
