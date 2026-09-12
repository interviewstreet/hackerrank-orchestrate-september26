"""Validation and evaluation suite for Buy or Wait? challenge submission."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

_parent = Path(__file__).resolve().parent
if (_parent / "code").exists():
    CODE_DIR = _parent / "code"
elif (_parent.parent / "code").exists():
    CODE_DIR = _parent.parent / "code"
else:
    CODE_DIR = _parent.parent

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from config import DATASET_DIR, OUTPUT_PATH
from data import load_dataset_files, parse_date
from evidence import build_evidence_lookups
from plans import make_decision

REQUESTS_CSV = DATASET_DIR / "requests.csv"
SAMPLE_REQUESTS_CSV = DATASET_DIR / "sample_requests.csv"

REQUIRED_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

VALID_STATUSES = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

VALID_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}


def validate_output_csv(output_path: Path = OUTPUT_PATH) -> list[str]:
    """Validate dataset/output.csv against strict contract rules."""
    errors: list[str] = []

    if not output_path.exists():
        return [f"Output file does not exist: {output_path}"]

    try:
        output_df = pd.read_csv(output_path, dtype=str).fillna("")
    except Exception as exc:
        return [f"Could not read output CSV: {exc}"]

    # Check columns and order
    actual_columns = list(output_df.columns)
    if actual_columns != REQUIRED_COLUMNS:
        errors.append(f"Columns mismatch! Expected: {REQUIRED_COLUMNS}, got: {actual_columns}")

    # Check requests row count
    if REQUESTS_CSV.exists():
        requests_df = pd.read_csv(REQUESTS_CSV)
        if len(output_df) != len(requests_df):
            errors.append(f"Row count mismatch! Expected {len(requests_df)} rows, got {len(output_df)}")

        expected_ids = list(requests_df["request_id"].astype(str))
        actual_ids = list(output_df["request_id"].astype(str))
        if expected_ids != actual_ids:
            errors.append("request_id sequence does not exactly match requests.csv!")
        req_map = {str(r["request_id"]): r for r in requests_df.to_dict(orient="records")}
    else:
        req_map = {}

    # Validate each row
    for idx, row in output_df.iterrows():
        req_id = row.get("request_id", f"row_{idx}")
        req_data = req_map.get(req_id, {})
        req_amt = float(req_data.get("requested_amount", 0.0)) if req_data else None
        req_date = parse_date(req_data.get("request_date")) if req_data else None

        # amount_safe_to_pay
        raw_safe = row.get("amount_safe_to_pay", "")
        try:
            safe_amt = float(raw_safe)
            if safe_amt < -0.01:
                errors.append(f"[{req_id}] amount_safe_to_pay cannot be negative: {safe_amt}")
            if req_amt is not None and safe_amt > req_amt + 0.01:
                errors.append(f"[{req_id}] amount_safe_to_pay ({safe_amt}) exceeds requested_amount ({req_amt})")
        except ValueError:
            errors.append(f"[{req_id}] Invalid numeric amount_safe_to_pay: {raw_safe!r}")

        # affordability_status
        status = row.get("affordability_status", "")
        if status not in VALID_STATUSES:
            errors.append(f"[{req_id}] Invalid affordability_status: {status!r}")

        # recommended_payment_method
        method = row.get("recommended_payment_method", "")
        if method not in VALID_METHODS:
            errors.append(f"[{req_id}] Invalid recommended_payment_method: {method!r}")

        # payment_plan
        plan = row.get("payment_plan", "")
        if method == "not_recommended":
            if plan != "none":
                errors.append(f"[{req_id}] payment_plan must be 'none' when method is not_recommended: {plan!r}")
        else:
            if not plan or plan == "none":
                errors.append(f"[{req_id}] payment_plan cannot be 'none' for method {method}")
            else:
                entries = plan.split("|")
                prev_date = None
                total_plan_amt = 0.0
                for entry in entries:
                    if ":" not in entry:
                        errors.append(f"[{req_id}] Invalid plan entry format: {entry!r}")
                        continue
                    dt_part, amt_part = entry.split(":", 1)
                    entry_date = parse_date(dt_part)
                    if not entry_date:
                        errors.append(f"[{req_id}] Invalid date in plan entry: {dt_part!r}")
                    elif prev_date and entry_date < prev_date:
                        errors.append(f"[{req_id}] Plan entries must be chronological: {plan}")
                    prev_date = entry_date

                    try:
                        total_plan_amt += float(amt_part)
                    except ValueError:
                        errors.append(f"[{req_id}] Invalid amount in plan entry: {amt_part!r}")

                if method == "partial_payment":
                    if len(entries) != 2:
                        errors.append(f"[{req_id}] partial_payment plan must have exactly 2 payments: got {len(entries)}")
                    if req_amt is not None and abs(total_plan_amt - req_amt) > 0.05:
                        errors.append(f"[{req_id}] partial_payment plan sum ({total_plan_amt}) != requested_amount ({req_amt})")

        # earliest_date_for_full_payment
        earliest = row.get("earliest_date_for_full_payment", "").strip()
        if status == "affordable_now":
            if req_date and earliest != req_date.isoformat():
                errors.append(f"[{req_id}] earliest_date_for_full_payment must equal request_date ({req_date}) for affordable_now: got {earliest}")
        elif status == "not_affordable":
            if earliest:
                errors.append(f"[{req_id}] earliest_date_for_full_payment must be empty for not_affordable: got {earliest}")
        elif earliest:
            if not parse_date(earliest):
                errors.append(f"[{req_id}] Invalid date for earliest_date_for_full_payment: {earliest}")

        # spending_changes_needed
        changes = row.get("spending_changes_needed", "").strip()
        if not changes:
            errors.append(f"[{req_id}] spending_changes_needed cannot be empty (must be 'none' or changes)")
        elif changes != "none":
            ch_items = changes.split("|")
            if len(ch_items) > 3:
                errors.append(f"[{req_id}] At most 3 spending changes allowed: got {len(ch_items)}")
            for ch in ch_items:
                parts = ch.split(":")
                if parts[0] not in {"stop", "reduce_to"}:
                    errors.append(f"[{req_id}] Invalid spending change action: {parts[0]}")
                if parts[0] == "reduce_to" and len(parts) != 3:
                    errors.append(f"[{req_id}] reduce_to must be reduce_to:<event_id>:<new_amount>")

        # decision_explanation
        explanation = row.get("decision_explanation", "").strip()
        if not explanation:
            errors.append(f"[{req_id}] decision_explanation cannot be empty")

    return errors


def evaluate_sample_requests(sample_path: Path = SAMPLE_REQUESTS_CSV) -> dict[str, Any]:
    """Compare predictions on sample requests against ground truth labels."""
    if not sample_path.exists():
        return {"error": f"Sample requests file not found: {sample_path}"}

    sample_df = pd.read_csv(sample_path)
    _, profiles_df, events_df, opts_df, rates_df = load_dataset_files(DATASET_DIR)
    blank_amounts, confirmed_incomes, cancelled_events, amended_events = build_evidence_lookups()

    total = len(sample_df)
    status_matches = 0
    method_matches = 0
    plan_matches = 0
    earliest_matches = 0
    spending_matches = 0
    full_exact_matches = 0

    detailed_results = []

    for _, expected in sample_df.iterrows():
        req_id = str(expected["request_id"])
        user_id = str(expected["user_id"])

        user_profile = profiles_df[profiles_df["user_id"] == user_id].iloc[0]
        user_events = events_df[events_df["user_id"] == user_id]
        user_opts = opts_df[opts_df["request_id"] == req_id] if not opts_df.empty else pd.DataFrame()
        user_inc = confirmed_incomes.get(user_id, [])

        pred = make_decision(
            expected,
            user_profile,
            user_events,
            user_opts,
            exchange_rates=rates_df,
            blank_amounts=blank_amounts,
            confirmed_incomes=user_inc,
            cancelled_events=cancelled_events,
            amended_events=amended_events,
        )

        s_match = pred.affordability_status == str(expected["affordability_status"]).strip()
        m_match = pred.recommended_payment_method == str(expected["recommended_payment_method"]).strip()

        exp_plan = str(expected["payment_plan"]).strip()
        p_match = pred.payment_plan == exp_plan

        exp_earliest = (
            str(expected["earliest_date_for_full_payment"]).strip()
            if pd.notna(expected["earliest_date_for_full_payment"])
            else ""
        )
        e_match = pred.earliest_date_for_full_payment == exp_earliest

        exp_spending = str(expected["spending_changes_needed"]).strip()
        sp_match = pred.spending_changes_needed == exp_spending

        if s_match:
            status_matches += 1
        if m_match:
            method_matches += 1
        if p_match:
            plan_matches += 1
        if e_match:
            earliest_matches += 1
        if sp_match:
            spending_matches += 1

        exact = s_match and m_match and p_match and e_match and sp_match
        if exact:
            full_exact_matches += 1

        detailed_results.append({
            "request_id": req_id,
            "status_match": s_match,
            "method_match": m_match,
            "plan_match": p_match,
            "earliest_match": e_match,
            "spending_match": sp_match,
            "exact": exact,
        })

    return {
        "total_samples": total,
        "status_accuracy": status_matches / total,
        "method_accuracy": method_matches / total,
        "plan_accuracy": plan_matches / total,
        "earliest_accuracy": earliest_matches / total,
        "spending_accuracy": spending_matches / total,
        "exact_match_accuracy": full_exact_matches / total,
        "details": detailed_results,
    }


def main() -> None:
    print("=" * 70)
    print("RUNNING SUBMISSION VALIDATOR")
    print("=" * 70)
    errors = validate_output_csv()
    if errors:
        print(f"FAILED: Found {len(errors)} validation errors in dataset/output.csv:")
        for err in errors[:15]:
            print(f"  * {err}")
        if len(errors) > 15:
            print(f"  ... and {len(errors) - 15} more errors.")
        sys.exit(1)
    else:
        print("PASSED: dataset/output.csv is 100% compliant with submission contract!")

    print("\n" + "=" * 70)
    print("EVALUATING AGAINST SAMPLE REQUESTS (GROUND TRUTH)")
    print("=" * 70)
    eval_res = evaluate_sample_requests()
    if "error" in eval_res:
        print(f"Error: {eval_res['error']}")
        return

    print(f"Total Sample Requests: {eval_res['total_samples']}")
    print(f"Affordability Status Accuracy: {eval_res['status_accuracy']:.1%}")
    print(f"Payment Method Accuracy:       {eval_res['method_accuracy']:.1%}")
    print(f"Payment Plan Accuracy:         {eval_res['plan_accuracy']:.1%}")
    print(f"Earliest Date Accuracy:        {eval_res['earliest_accuracy']:.1%}")
    print(f"Spending Changes Accuracy:     {eval_res['spending_accuracy']:.1%}")
    print(f"Full Exact Match Accuracy:     {eval_res['exact_match_accuracy']:.1%}")


if __name__ == "__main__":
    main()
