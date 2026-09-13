"""Builds test/test_requests.csv: the input columns only (no output/label
columns) from dataset/sample_requests.csv's 25 solved examples (request_01..
request_25). Run once to (re)create the fixture; run_test.py then runs the
real pipeline against it and compare_to_sample.py checks the result against
the known-good answers still in dataset/sample_requests.csv.
"""
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = Path(__file__).resolve().parent

COLUMNS = [
    "request_id", "user_id", "request_date", "request_type", "requested_amount",
    "desired_completion_date", "allows_partial_payment", "request_text",
]


def main() -> int:
    with (REPO_ROOT / "dataset" / "sample_requests.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [{k: row[k] for k in COLUMNS} for row in reader]

    out_path = TEST_DIR / "test_requests.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} rows written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
