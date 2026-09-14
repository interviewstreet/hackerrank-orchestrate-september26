import csv
import sys
from pathlib import Path
from decimal import Decimal

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from code.src.pipeline import FinancialAgentPipeline


def normalize_amount(val_str: str | float | None) -> float | None:
    if not val_str or str(val_str).strip() == "":
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def amounts_close(a: float | None, b: float | None, tol: float = 0.5) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol or abs(a - b) / max(abs(a), abs(b), 1.0) < 0.001


def normalize_plan(plan_str: str) -> list[tuple[str, float]]:
    if not plan_str or plan_str.strip() == "none" or plan_str.strip() == "":
        return []
    items = []
    for part in plan_str.split("|"):
        if ":" in part:
            d_str, amt_str = part.strip().split(":", 1)
            try:
                items.append((d_str.strip(), float(amt_str)))
            except ValueError:
                items.append((d_str.strip(), amt_str.strip()))
    return items


def plans_match(plan_actual: str, plan_expected: str) -> bool:
    actual_items = normalize_plan(plan_actual)
    expected_items = normalize_plan(plan_expected)
    if len(actual_items) != len(expected_items):
        return False
    for (d1, a1), (d2, a2) in zip(actual_items, expected_items):
        if d1 != d2:
            return False
        if isinstance(a1, float) and isinstance(a2, float):
            if not amounts_close(a1, a2):
                return False
        elif a1 != a2:
            return False
    return True


def normalize_changes(changes_str: str) -> set[str]:
    if not changes_str or changes_str.strip() == "" or changes_str.strip().lower() == "none":
        return set()
    return {c.strip() for c in changes_str.split("|")}


def changes_match(act: str, exp: str) -> bool:
    return normalize_changes(act) == normalize_changes(exp)


def main():
    sample_csv_path = root_dir / "dataset" / "sample_requests.csv"
    if not sample_csv_path.exists():
        print(f"File not found: {sample_csv_path}")
        sys.exit(1)

    with open(sample_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        samples = list(reader)

    print(f"Loaded {len(samples)} ground-truth sample requests from {sample_csv_path}", flush=True)
    pipeline = FinancialAgentPipeline()

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        actual_rows = list(executor.map(lambda r: pipeline.process_request(r["request_id"].strip()), samples))
    actual_rows_by_id = {row.request_id: row for row in actual_rows}

    matches = {
        "amount_safe_to_pay": 0,
        "affordability_status": 0,
        "recommended_payment_method": 0,
        "payment_plan": 0,
        "earliest_date_for_full_payment": 0,
        "spending_changes_needed": 0,
        "overall_all_fields_exact": 0,
    }

    results = []
    print("\n" + "=" * 100, flush=True)
    print(f"{'Req ID':<12} | {'Status':<16} | {'Method':<14} | {'Plan':<8} | {'Safe Amt':<10} | {'Earliest Dt':<12} | {'Changes':<10}", flush=True)
    print("=" * 100, flush=True)

    for row in samples:
        req_id = row["request_id"].strip()
        expected = row
        actual_row = actual_rows_by_id[req_id]
        actual = actual_row.to_csv_dict()

        # Comparisons
        act_safe = normalize_amount(actual.get("amount_safe_to_pay"))
        exp_safe = normalize_amount(expected.get("amount_safe_to_pay"))
        safe_match = amounts_close(act_safe, exp_safe)

        status_match = actual.get("affordability_status") == expected.get("affordability_status")
        method_match = actual.get("recommended_payment_method") == expected.get("recommended_payment_method")
        plan_match = plans_match(actual.get("payment_plan", ""), expected.get("payment_plan", ""))

        act_earliest = (actual.get("earliest_date_for_full_payment") or "").strip()
        exp_earliest = (expected.get("earliest_date_for_full_payment") or "").strip()
        earliest_match = act_earliest == exp_earliest

        change_match = changes_match(actual.get("spending_changes_needed", ""), expected.get("spending_changes_needed", ""))

        all_match = safe_match and status_match and method_match and plan_match and earliest_match and change_match

        if safe_match:
            matches["amount_safe_to_pay"] += 1
        if status_match:
            matches["affordability_status"] += 1
        if method_match:
            matches["recommended_payment_method"] += 1
        if plan_match:
            matches["payment_plan"] += 1
        if earliest_match:
            matches["earliest_date_for_full_payment"] += 1
        if change_match:
            matches["spending_changes_needed"] += 1
        if all_match:
            matches["overall_all_fields_exact"] += 1

        status_flag = "✓" if status_match else f"✗ ({actual.get('affordability_status')} vs {expected.get('affordability_status')})"
        method_flag = "✓" if method_match else f"✗ ({actual.get('recommended_payment_method')} vs {expected.get('recommended_payment_method')})"
        plan_flag = "✓" if plan_match else "✗"
        safe_flag = "✓" if safe_match else f"✗ ({act_safe} vs {exp_safe})"
        earliest_flag = "✓" if earliest_match else f"✗ ({act_earliest} vs {exp_earliest})"
        change_flag = "✓" if change_match else f"✗ ({actual.get('spending_changes_needed')} vs {expected.get('spending_changes_needed')})"

        print(f"{req_id:<12} | {status_flag:<16} | {method_flag:<14} | {plan_flag:<8} | {safe_flag:<10} | {earliest_flag:<12} | {change_flag:<10}")

        results.append({
            "req_id": req_id,
            "actual": actual,
            "expected": expected,
            "safe_match": safe_match,
            "status_match": status_match,
            "method_match": method_match,
            "plan_match": plan_match,
            "earliest_match": earliest_match,
            "change_match": change_match,
            "all_match": all_match,
        })

    print("=" * 100)
    print("\nSummary of Matches (out of 25):")
    total = len(samples)
    for field, count in matches.items():
        pct = (count / total) * 100
        print(f"  - {field:<30}: {count}/{total} ({pct:.1f}%)")

    # If any discrepancies exist, print details
    mismatches = [r for r in results if not r["all_match"]]
    if mismatches:
        print(f"\nDiscrepancy Details ({len(mismatches)} requests):")
        for m in mismatches:
            print(f"\n--- {m['req_id']} ---")
            for field in ["amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]:
                act_v = m["actual"].get(field)
                exp_v = m["expected"].get(field)
                if act_v != exp_v:
                    print(f"  Field: {field}")
                    print(f"    Expected: {exp_v}")
                    print(f"    Actual:   {act_v}")
    else:
        print("\nPERFECT MATCH: All 25 sample requests match the ground truth on all decision and financial fields!")


if __name__ == "__main__":
    main()
