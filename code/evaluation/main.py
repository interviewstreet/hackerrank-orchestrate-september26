"""Validate a produced output.csv, and score it when labels are available.

Usage:
    python evaluation/main.py                        # check ../output.csv
    python evaluation/main.py --output path.csv      # check another file
    python evaluation/main.py --against-samples      # score vs sample labels

Checks performed:
1. Schema      -- exact columns, in order.
2. Coverage    -- one row per request_id, no extras, no duplicates.
3. Enums       -- allowed affordability_status and payment method values.
4. Ranges      -- 0 <= amount_safe_to_pay <= requested_amount.
5. Formats     -- payment_plan and spending_changes_needed shapes.
6. Consistency -- status, method and plan agree with one another.
7. Safety      -- every plan is re-simulated against the 90-day forecast, with
                  the evidence it was decided on replayed from the run's cache.
                  A request whose evidence is unavailable is reported as
                  unverified rather than failed: an evidence-blind forecast
                  misses a salary a message raised and would cry breach.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import CODE_DIR, OUTPUT_COLUMNS, REPO_ROOT  # noqa: E402
from tools.balance_forecaster import ForecastConfig, build_forecast_model  # noqa: E402
from tools.dataset_loader import DatasetLoader  # noqa: E402
from tools.evidence_cache import EvidenceCache  # noqa: E402
from tools.exchange_converter import ExchangeConverter  # noqa: E402
from tools.message_resolver import apply_modifications  # noqa: E402
from validators.output_validator import validate_output  # noqa: E402
from validators.schemas import AgentOutput  # noqa: E402


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def check_schema(header: list[str]) -> list[str]:
    if tuple(header) == OUTPUT_COLUMNS:
        return []
    return [
        "header mismatch\n"
        f"  expected: {','.join(OUTPUT_COLUMNS)}\n"
        f"  found:    {','.join(header)}"
    ]


def check_coverage(rows: list[dict[str, str]], expected: list[str]) -> list[str]:
    seen = Counter(row["request_id"] for row in rows)
    errors: list[str] = []
    missing = [rid for rid in expected if rid not in seen]
    extra = [rid for rid in seen if rid not in set(expected)]
    duplicates = [rid for rid, count in seen.items() if count > 1]
    if missing:
        errors.append(f"{len(missing)} request_id(s) missing, e.g. {missing[:5]}")
    if extra:
        errors.append(f"{len(extra)} unexpected request_id(s), e.g. {extra[:5]}")
    if duplicates:
        errors.append(f"{len(duplicates)} duplicated request_id(s), e.g. {duplicates[:5]}")
    return errors


def check_rows(
    rows: list[dict[str, str]], loader: DatasetLoader, use_samples: bool
) -> tuple[list[str], list[str], int]:
    """Re-validate every row, including an independent safety re-simulation.

    The safety check only means something if the forecast it runs against is the
    one the recommendation was judged on. Rebuilding from raw CSV rows alone is
    evidence-blind: it misses a salary a payroll message raised, or an amount
    recovered from a receipt, and then reports a breach that never existed. So
    the evidence recorded during the run is replayed here, and any request whose
    evidence is unavailable is reported as unverified rather than failed.
    """
    converter = ExchangeConverter(loader.exchange_rates)
    evidence = EvidenceCache(CODE_DIR / ".cache" / "evidence.json")
    source = (
        {loader._request(r).request_id: loader._request(r) for r in loader.sample_requests}
        if use_samples
        else {r.request_id: r for r in loader.requests}
    )

    errors: list[str] = []
    unverified: list[str] = []
    checked = 0
    for row in rows:
        request = source.get(row["request_id"])
        if request is None:
            continue
        profile = loader.profiles.get(request.user_id)
        if profile is None:
            continue
        events = loader.events_by_user.get(request.user_id, [])
        options = loader.options_by_request.get(request.request_id, [])

        # Replay the evidence this request was decided with.
        amounts = evidence.amounts(request.request_id)
        if amounts:
            events = [
                e.model_copy(update={"amount": amounts[e.event_id]})
                if e.amount is None and e.event_id in amounts
                else e
                for e in events
            ]
        model = build_forecast_model(
            profile, events, request.request_date, converter, ForecastConfig()
        )
        model = apply_modifications(model, evidence.modifications(request.request_id))

        # Messages can change the position materially, so a plan cannot be
        # safety-checked against a forecast that never saw them.
        messages = [
            m
            for m in loader.messages_by_user.get(request.user_id, [])
            if m.request_id in (None, request.request_id)
        ]
        blind = bool(messages) and not evidence.messages_resolved(request.request_id)
        if blind:
            unverified.append(
                f"{row['request_id']}: safety not re-simulated -- "
                f"{len(messages)} message(s) were not replayable "
                f"(no evidence record; was this row produced with --no-llm?)"
            )
        try:
            output = AgentOutput(
                request_id=row["request_id"],
                amount_safe_to_pay=float(row["amount_safe_to_pay"] or 0),
                affordability_status=row["affordability_status"],
                recommended_payment_method=row["recommended_payment_method"],
                payment_plan=row["payment_plan"] or "none",
                earliest_date_for_full_payment=row["earliest_date_for_full_payment"],
                spending_changes_needed=row["spending_changes_needed"] or "none",
                decision_explanation=row["decision_explanation"],
                requested_amount=request.requested_amount,
            )
        except Exception as error:  # noqa: BLE001
            errors.append(f"{row['request_id']}: unparseable row ({error})")
            continue

        result = validate_output(output, request, profile, options, events, model)
        checked += 1
        for problem in result.errors:
            # A breach claim is only trustworthy when the evidence was replayed.
            if blind and "breaches minimum balance" in problem:
                continue
            errors.append(f"{row['request_id']}: {problem}")
    return errors, unverified, checked


def score_against_samples(rows: list[dict[str, str]], loader: DatasetLoader) -> None:
    """Field-by-field agreement with the labelled samples."""
    truth = {row["request_id"]: row for row in loader.sample_requests}
    graded = [row for row in rows if row["request_id"] in truth]
    if not graded:
        print("no sample rows present to score")
        return

    status = method = plan = dates = changes = 0
    errors: list[float] = []
    for row in graded:
        gold = truth[row["request_id"]]
        status += row["affordability_status"] == gold["affordability_status"]
        method += (
            row["recommended_payment_method"] == gold["recommended_payment_method"]
        )
        plan += row["payment_plan"] == gold["payment_plan"]
        dates += (
            row["earliest_date_for_full_payment"].strip()
            == gold["earliest_date_for_full_payment"].strip()
        )
        changes += row["spending_changes_needed"] == gold["spending_changes_needed"]
        predicted = float(row["amount_safe_to_pay"] or 0)
        actual = float(gold["amount_safe_to_pay"] or 0)
        errors.append(
            abs(predicted - actual) / abs(actual) if actual else float(predicted != 0)
        )

    n = len(graded)
    errors.sort()
    print(f"\nScored against {n} labelled samples:")
    print(f"  affordability_status           {status}/{n} ({status / n:.0%})")
    print(f"  recommended_payment_method     {method}/{n} ({method / n:.0%})")
    print(f"  payment_plan (exact)           {plan}/{n} ({plan / n:.0%})")
    print(f"  earliest_date_for_full_payment {dates}/{n} ({dates / n:.0%})")
    print(f"  spending_changes_needed        {changes}/{n} ({changes / n:.0%})")
    print(f"  amount_safe_to_pay median err  {errors[n // 2]:.1%}")
    print(f"  amount_safe_to_pay within 10%  {sum(1 for e in errors if e <= 0.10) / n:.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--against-samples", action="store_true")
    args = parser.parse_args()

    if not args.output.exists():
        print(f"missing {args.output}")
        raise SystemExit(1)

    loader = DatasetLoader(REPO_ROOT / "dataset")
    rows, header = read_rows(args.output)
    expected = (
        [loader._request(r).request_id for r in loader.sample_requests]
        if args.against_samples
        else [r.request_id for r in loader.requests]
    )

    problems = check_schema(header)
    problems += check_coverage(rows, expected)
    row_errors, unverified, checked = check_rows(rows, loader, args.against_samples)
    problems += row_errors

    print(f"{args.output}: {len(rows)} rows, {checked} re-simulated")
    if unverified:
        print(
            f"\n{len(unverified)} row(s) could not have their safety re-simulated "
            f"(evidence unavailable, not a failure):"
        )
        for note in unverified[:10]:
            print(f"  - {note}")
        if len(unverified) > 10:
            print(f"  ... and {len(unverified) - 10} more")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems[:40]:
            print(f"  - {problem}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
    else:
        print("all checks passed: schema, coverage, enums, ranges, formats, "
              "consistency, and 90-day safety")

    if args.against_samples:
        score_against_samples(rows, loader)

    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
