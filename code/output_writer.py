"""Module 9: output_writer.

Runs Modules 1, 6, 3, 4, 5 for every row in `dataset/requests.csv` and writes
the 8-column `output.csv` the challenge requires (AGENTS.md §6.2). Module 7
(LLM decision_explanation) is not wired in yet, so decision_explanation comes
from plan_selector's deterministic template.

Module 6 (llm_extract) runs once per user, batching every message/image that
user has (PLAN.md's "cắm bước 6 vào làm pre-processing trước bước 3"). It is
always safe to call: with no `ANTHROPIC_API_KEY`/`LLM_API_KEY` set, or a user
with no messages/images, it returns `([], None)` and the pipeline continues
exactly as it did LLM-free.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from event_normalizer import normalize_events
from forecast_engine import build_forecast
from fx import FxConverter
from llm_extract import UsageRecord, extract_facts_for_user
from loaders import load_dataset
from plan_selector import PlanResult, select_plan

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def _fmt_amount(amount: float) -> str:
    rounded = round(amount, 2)
    if rounded == round(rounded):
        return str(int(round(rounded)))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _fallback_result(reason: str) -> PlanResult:
    return PlanResult(
        amount_safe_to_pay=0.0,
        affordability_status="not_affordable",
        recommended_payment_method="not_recommended",
        payment_plan="none",
        earliest_date_for_full_payment=None,
        spending_changes_needed="none",
        decision_explanation=reason,
    )


def build_output_row(request_id: str, result: PlanResult) -> dict[str, str]:
    return {
        "request_id": request_id,
        "amount_safe_to_pay": _fmt_amount(result.amount_safe_to_pay),
        "affordability_status": result.affordability_status,
        "recommended_payment_method": result.recommended_payment_method,
        "payment_plan": result.payment_plan,
        "earliest_date_for_full_payment": (
            result.earliest_date_for_full_payment.isoformat()
            if result.earliest_date_for_full_payment
            else ""
        ),
        "spending_changes_needed": result.spending_changes_needed,
        "decision_explanation": result.decision_explanation,
    }


def run_pipeline(dataset_dir: Path) -> tuple[list[dict[str, str]], list[UsageRecord]]:
    """Module 1 (load) -> 6 (extract) -> 3 (normalize) -> 4 (forecast) -> 5 (select)."""
    ds = load_dataset(dataset_dir)
    fx = FxConverter(ds.rates_by_pair)

    rows: list[dict[str, str]] = []
    usage_records: list[UsageRecord] = []
    for request_id, request in ds.requests_by_id.items():
        profile = ds.profiles_by_user.get(request.user_id)
        if profile is None:
            logger.error(
                "output_writer: no financial profile for user %s (request %s) — "
                "writing a safe not_affordable default",
                request.user_id,
                request_id,
            )
            rows.append(
                build_output_row(
                    request_id,
                    _fallback_result("No financial profile available for this user."),
                )
            )
            continue

        user_events = ds.events_by_user.get(request.user_id, [])
        user_messages = ds.messages_by_user.get(request.user_id, [])
        user_images = ds.images_by_request.get(request_id, [])

        facts, usage = extract_facts_for_user(
            request.user_id, profile.home_currency, user_events, user_messages, user_images, dataset_dir
        )
        if usage is not None:
            usage_records.append(usage)

        clean_timeline = normalize_events(user_events, facts=facts)
        forecast = build_forecast(request.user_id, request.request_date, clean_timeline, profile, fx)
        payment_options = ds.payment_options_by_request.get(request_id, [])
        result = select_plan(request, forecast, profile, payment_options, fx)
        rows.append(build_output_row(request_id, result))
    return rows, usage_records


def write_output_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
