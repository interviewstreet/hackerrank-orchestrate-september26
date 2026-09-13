#!/usr/bin/env python3
"""Generic validation and public-sample comparison for the submission agent."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def validate(predictions: list[dict[str, str]], requests: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not predictions:
        return ["prediction file has no data rows"]
    if list(predictions[0]) != REQUIRED:
        errors.append("output columns do not match the required order")
    if len(predictions) != len(requests):
        errors.append(f"expected {len(requests)} predictions, found {len(predictions)}")
    request_by_id = {row["request_id"]: row for row in requests}
    allowed_statuses = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
    allowed_methods = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
    for prediction in predictions:
        request = request_by_id.get(prediction["request_id"])
        if not request:
            errors.append(f"unknown request id: {prediction['request_id']}")
            continue
        try:
            amount = float(prediction["amount_safe_to_pay"])
            if not 0 <= amount <= float(request["requested_amount"]) + 0.01:
                errors.append(f"invalid safe amount for {prediction['request_id']}")
        except ValueError:
            errors.append(f"non-numeric safe amount for {prediction['request_id']}")
        if prediction["affordability_status"] not in allowed_statuses:
            errors.append(f"invalid status for {prediction['request_id']}")
        if prediction["recommended_payment_method"] not in allowed_methods:
            errors.append(f"invalid method for {prediction['request_id']}")
    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=root / "dataset")
    parser.add_argument("--output", type=Path, default=root / "output.csv")
    parser.add_argument("--samples", action="store_true", help="Run the agent against public solved samples and print field agreement.")
    args = parser.parse_args()
    if args.samples:
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "samples.csv"
            subprocess.run([sys.executable, str(root / "code" / "main.py"), "--dataset", str(args.dataset), "--requests", str(args.dataset / "sample_requests.csv"), "--output", str(generated)], check=True)
            expected = {row["request_id"]: row for row in rows(args.dataset / "sample_requests.csv")}
            actual = rows(generated)
            tested = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]
            matches = sum(actual_row[field] == expected[actual_row["request_id"]][field] for actual_row in actual for field in tested)
            print(f"Public-sample exact field agreement: {matches}/{len(actual) * len(tested)}")
    errors = validate(rows(args.output), rows(args.dataset / "requests.csv"))
    if errors:
        raise SystemExit("Validation failed:\n- " + "\n- ".join(errors))
    print(f"Validated {len(rows(args.output))} predictions with the required schema.")


if __name__ == "__main__":
    main()
