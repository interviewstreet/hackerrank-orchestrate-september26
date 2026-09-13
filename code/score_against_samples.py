"""
score_against_samples.py

Runs dataset/sample_requests.csv's 25 known-correct requests through the
ACTUAL pipeline (main.process_request) and compares the result against the
expected columns already present in that same file, column by column.

NOTE: sample_requests.csv's request_ids (request_01..request_25) are a
disjoint set from dataset/requests.csv's 250 ids (request_26..request_275) -
they are NOT a subset of output.csv, so this must re-run them through the
pipeline directly rather than looking them up in output.csv.

Run from inside code/.
"""
import csv
import os

import main as pipeline

DATASET_DIR = os.path.join(os.path.dirname(__file__), "..", "dataset")

COMPARE_COLUMNS = [
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
]


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row["request_id"]: row for row in csv.DictReader(f)}


def close_enough(a, b, tol=0.5):
    try:
        return abs(float(a) - float(b)) <= tol
    except (ValueError, TypeError):
        return a == b


def main():
    samples = load_csv(os.path.join(DATASET_DIR, "sample_requests.csv"))
    data = pipeline.load_all_data()

    per_col_mismatches = {c: 0 for c in COMPARE_COLUMNS}
    total_rows = 0
    fully_correct = 0

    for request_id, sample_row in samples.items():
        total_rows += 1
        try:
            out_row = pipeline.process_request(data, sample_row)
        except Exception as exc:  # noqa: BLE001
            print(f"{request_id}: EXCEPTION {exc}")
            continue

        row_ok = True
        mismatches = []
        for col in COMPARE_COLUMNS:
            expected = sample_row[col]
            actual = out_row[col]
            if col == "amount_safe_to_pay":
                ok = close_enough(expected, actual)
            else:
                ok = (expected.strip() == actual.strip())
            if not ok:
                row_ok = False
                per_col_mismatches[col] += 1
                mismatches.append(f"{col}: expected={expected!r} actual={actual!r}")

        if row_ok:
            fully_correct += 1
        else:
            print(f"{request_id}: MISMATCH")
            for m in mismatches:
                print(f"    {m}")

    print()
    print(f"Fully correct: {fully_correct}/{total_rows}")
    print("Per-column mismatch counts:")
    for col, count in per_col_mismatches.items():
        print(f"  {col}: {count}/{total_rows}")


if __name__ == "__main__":
    main()