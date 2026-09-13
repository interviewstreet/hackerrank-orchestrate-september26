"""Compares test/test_output.csv (produced by run_test.py) against
dataset/sample_requests.csv's known-good answers, field by field.

Usage:
    python test/compare_to_sample.py
"""
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = Path(__file__).resolve().parent

FIELDS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
]


def load(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row["request_id"]: row for row in csv.DictReader(f)}


def main() -> int:
    sample = load(REPO_ROOT / "dataset" / "sample_requests.csv")
    test = load(TEST_DIR / "test_output.csv")

    exact_matches = 0
    per_field_matches = {f: 0 for f in FIELDS}
    mismatches = []

    for rid in sorted(sample, key=lambda x: int(x.split("_")[1])):
        exp = sample[rid]
        got = test.get(rid)
        if got is None:
            mismatches.append((rid, "MISSING from test_output.csv", exp, got))
            continue

        row_ok = True
        diffs = []
        for f in FIELDS:
            exp_v = (exp.get(f) or "").strip()
            got_v = (got.get(f) or "").strip()
            if f == "amount_safe_to_pay":
                try:
                    match = abs(float(exp_v) - float(got_v)) < 0.5
                except ValueError:
                    match = exp_v == got_v
            else:
                match = exp_v == got_v
            if match:
                per_field_matches[f] += 1
            else:
                row_ok = False
                diffs.append(f"{f}: expected={exp_v!r} got={got_v!r}")
        if row_ok:
            exact_matches += 1
        else:
            mismatches.append((rid, "; ".join(diffs), exp, got))

    n = len(sample)
    print(f"Rows compared: {n}")
    print(f"Fully matching rows (all 6 fields): {exact_matches}/{n}")
    print()
    print("Per-field match rate:")
    for f in FIELDS:
        print(f"  {f}: {per_field_matches[f]}/{n}")
    print()
    print(f"Mismatched rows: {len(mismatches)}")
    for rid, diff, exp, got in mismatches:
        print(f"\n--- {rid} ---")
        print(f"  request_text: {exp.get('request_text', '')[:100]}")
        print(f"  {diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
