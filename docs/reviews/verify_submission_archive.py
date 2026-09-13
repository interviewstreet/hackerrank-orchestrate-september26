"""Independently check serialized output and smoke-test a clean extraction."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify():
    output_hash = hashlib.sha256((ROOT / "output.csv").read_bytes()).hexdigest()
    requests = read_rows(ROOT / "dataset/requests.csv")
    profiles = {row["user_id"]: row for row in read_rows(ROOT / "dataset/financial_profiles.csv")}
    options = read_rows(ROOT / "dataset/request_payment_options.csv")
    rows = read_rows(ROOT / "output.csv")
    errors = []
    for row, request in zip(rows, requests):
        request_id = request["request_id"]
        requested = Decimal(request["requested_amount"])
        safe = Decimal(row["amount_safe_to_pay"])
        when = date.fromisoformat(request["request_date"])
        deadline = date.fromisoformat(request["desired_completion_date"])
        method, status = row["recommended_payment_method"], row["affordability_status"]
        payments = [] if row["payment_plan"] == "none" else [
            (date.fromisoformat(item.split(":")[0]), Decimal(item.split(":")[1]))
            for item in row["payment_plan"].split("|")]
        def require(condition, description):
            if not condition:
                errors.append(f"{request_id}: {description}")
        require(safe.is_finite() and 0 <= safe <= requested, "safe amount bounds")
        require(payments == sorted(payments), "chronological plan")
        require(all(when <= day <= deadline and amount > 0 for day, amount in payments), "plan dates/amounts")
        require(bool(row["decision_explanation"].strip()), "explanation missing")
        earliest = date.fromisoformat(row["earliest_date_for_full_payment"]) if row["earliest_date_for_full_payment"] else None
        if earliest:
            require(when <= earliest <= when + timedelta(days=90), "earliest outside forecast")
        if method == "not_recommended":
            require(status == "not_affordable" and not payments, "fallback contract")
        elif method in ("full_payment", "wait", "partial_payment"):
            require(sum((amount for _, amount in payments), Decimal(0)) == requested, "plan total")
            if method == "full_payment":
                require(payments == [(when, requested)], "full payment schedule")
                if row["spending_changes_needed"] == "none":
                    require(status == "affordable_now" and earliest == when and safe == requested, "affordable-now contract")
            elif method == "wait":
                require(status == "affordable_later" and payments == [(earliest, requested)], "wait contract")
            else:
                require(status == "affordable_with_plan" and request["allows_partial_payment"].lower() == "true", "partial eligibility")
                require(0 < safe < requested and payments == [(when, safe), (earliest, requested-safe)], "partial schedule")
        elif method == "installments":
            matching = []
            for option in options:
                if option["request_id"] != request_id or option["payment_method"] != "installments":
                    continue
                expected = [(date.fromisoformat(option["first_payment_date"]) + timedelta(days=int(option["payment_frequency_days"])*index), Decimal(option["payment_amount"])) for index in range(int(option["number_of_payments"]))]
                if expected == payments:
                    matching.append(option)
            require(status == "affordable_with_plan" and bool(matching), "installment offer mismatch")
        else:
            require(False, "invalid method")
        considered = profiles[request["user_id"]]["payment_methods_user_will_consider"]
        if method != "not_recommended":
            require(("full_payment" if method == "wait" else method) in considered, "user preference")
    if errors:
        raise ValueError(errors)
    with zipfile.ZipFile(ROOT / "code.zip") as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failure")
        names = archive.namelist()
        if not archive.read("evaluation/usage_report.md").strip():
            raise ValueError("Empty usage report")
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts or Path(name).name == ".env":
                raise ValueError("Unsafe archive member")
            content = archive.read(name)
            if re.search(rb"sk-ant-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
                raise ValueError(f"Credential-like content in {name}; value suppressed")
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            archive.extractall(extracted / "code")
            shutil.copytree(ROOT / "dataset", extracted / "dataset")
            commands = [
                [sys.executable, "code/main.py", "--mode", "audit", "--quiet"],
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", "code/tests", "-t", "code", "-p", "test_*.py"]]
            transcripts = []
            for command in commands:
                result = subprocess.run(command, cwd=extracted, capture_output=True, text=True, timeout=120)
                transcripts.append(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(transcripts[-1])
    if hashlib.sha256((ROOT / "output.csv").read_bytes()).hexdigest() != output_hash:
        raise ValueError("Original output changed")
    report = {"serialized_contract_errors": errors, "rows": len(rows), "archive_files": len(names),
              "archive_sha256": hashlib.sha256((ROOT / "code.zip").read_bytes()).hexdigest(),
              "output_sha256": output_hash, "clean_extraction_audit_and_tests": transcripts}
    (ROOT / "docs/reviews/FINAL_ARCHIVE_VERIFICATION.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "clean_extraction_audit_and_tests"}))
    print(transcripts[-1][-300:])


if __name__ == "__main__":
    verify()
