import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUESTS_PATH = ROOT / "dataset" / "requests.csv"
OUTPUT_PATH = ROOT / "output.csv"

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
VALID_METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
VALID_STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}


def main() -> None:
    with open(REQUESTS_PATH, newline="", encoding="utf-8") as f:
        request_rows = list(csv.DictReader(f))

    with open(OUTPUT_PATH, newline="", encoding="utf-8") as f:
        output_rows = list(csv.DictReader(f))

    request_ids = {r["request_id"] for r in request_rows}
    out_ids = {r["request_id"] for r in output_rows}
    missing = sorted(request_ids - out_ids)
    extra = sorted(out_ids - request_ids)

    if missing or extra:
        raise ValueError(f"Request ID mismatch: missing={missing[:5]} extra={extra[:5]}")

    if list(output_rows[0].keys()) != REQUIRED_COLUMNS:
        raise ValueError(f"Unexpected output columns: {list(output_rows[0].keys())}")

    for row in output_rows:
        if row["recommended_payment_method"] not in VALID_METHODS:
            raise ValueError(f"Bad payment method: {row['recommended_payment_method']}")
        if row["affordability_status"] not in VALID_STATUSES:
            raise ValueError(f"Bad affordability status: {row['affordability_status']}")

    print(f"Validated {len(output_rows)} rows from {len(request_rows)} requests.")
    print(f"Missing: {missing[:10]}")
    print(f"Extra: {extra[:10]}")


if __name__ == "__main__":
    main()
