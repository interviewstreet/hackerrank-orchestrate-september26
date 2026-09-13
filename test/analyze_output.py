"""Validates and analyzes the real submission output.csv (request_26..275)
against dataset/requests.csv and the AGENTS.md §6.2 output contract.

Usage:
    python test/analyze_output.py
"""
import csv
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_STATUS = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
VALID_METHOD = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


def load(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    requests = {r["request_id"]: r for r in load(REPO_ROOT / "dataset" / "requests.csv")}
    output = load(REPO_ROOT / "output.csv")

    errors = []
    status_counts = Counter()
    method_counts = Counter()
    zero_amount_ids = []
    full_amount_ids = []

    output_ids = {r["request_id"] for r in output}
    missing = set(requests) - output_ids
    extra = output_ids - set(requests)
    if missing:
        errors.append(f"{len(missing)} request_id(s) missing from output.csv: {sorted(missing)[:5]}...")
    if extra:
        errors.append(f"{len(extra)} extra request_id(s) in output.csv not in requests.csv: {sorted(extra)[:5]}...")

    for row in output:
        rid = row["request_id"]
        req = requests.get(rid)
        if req is None:
            continue

        status = row["affordability_status"]
        method = row["recommended_payment_method"]
        status_counts[status] += 1
        method_counts[method] += 1

        if status not in VALID_STATUS:
            errors.append(f"{rid}: invalid affordability_status {status!r}")
        if method not in VALID_METHOD:
            errors.append(f"{rid}: invalid recommended_payment_method {method!r}")

        try:
            amt = float(row["amount_safe_to_pay"])
            requested = float(req["requested_amount"])
        except ValueError:
            errors.append(f"{rid}: non-numeric amount_safe_to_pay {row['amount_safe_to_pay']!r}")
            continue

        if not (0 <= amt <= requested + 1e-6):
            errors.append(f"{rid}: amount_safe_to_pay {amt} out of [0, {requested}]")
        if amt == 0:
            zero_amount_ids.append(rid)
        if abs(amt - requested) < 1e-6:
            full_amount_ids.append(rid)

        plan = row["payment_plan"]
        if plan != "none":
            parts = plan.split("|")
            total = 0.0
            for p in parts:
                if ":" not in p:
                    errors.append(f"{rid}: malformed payment_plan entry {p!r}")
                    continue
                d, a = p.rsplit(":", 1)
                try:
                    total += float(a)
                except ValueError:
                    errors.append(f"{rid}: non-numeric payment_plan amount {p!r}")
            if method == "partial_payment" and abs(total - requested) > 0.5:
                errors.append(f"{rid}: partial_payment plan sums to {total}, requested_amount is {requested}")

        if method == "not_recommended" and status != "not_affordable":
            errors.append(f"{rid}: method=not_recommended but status={status} (expected not_affordable)")
        if status == "affordable_now" and method not in ("full_payment",):
            errors.append(f"{rid}: status=affordable_now but method={method}")

    print(f"Total output rows: {len(output)} (requests.csv has {len(requests)})")
    print(f"Validation errors: {len(errors)}")
    for e in errors[:30]:
        print(f"  - {e}")
    if len(errors) > 30:
        print(f"  ... and {len(errors) - 30} more")
    print()

    print("affordability_status distribution:")
    for k, v in status_counts.most_common():
        print(f"  {k:24s} {v:4d}  ({v / len(output) * 100:.1f}%)")
    print()
    print("recommended_payment_method distribution:")
    for k, v in method_counts.most_common():
        print(f"  {k:24s} {v:4d}  ({v / len(output) * 100:.1f}%)")
    print()
    print(f"amount_safe_to_pay == 0:        {len(zero_amount_ids)} rows ({len(zero_amount_ids) / len(output) * 100:.1f}%)")
    print(f"amount_safe_to_pay == full ask: {len(full_amount_ids)} rows ({len(full_amount_ids) / len(output) * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
