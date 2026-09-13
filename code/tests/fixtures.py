"""Synthetic dataset builder for offline tests.

Produces a small but *contract-valid* dataset on disk so tests can mutate one
cell at a time and assert the loader or the audit catches it. Tests that need
the real data read `dataset/` directly; everything else uses this, so a test
failure points at one deliberate defect rather than at 25,342 real rows.
"""
from __future__ import annotations

import base64
import csv
import re
from pathlib import Path

from buy_or_wait.data import EXPECTED_HEADERS

# A real 1x1 PNG, so image-existence checks find a genuine file and M2's vision
# path can be pointed at it without special-casing a placeholder.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

ROWS: dict[str, list[dict[str, str]]] = {
    "financial_profiles.csv": [
        {
            "user_id": "user_01", "home_currency": "ZAR",
            "current_available_balance": "10000.00", "minimum_balance_to_keep": "2000",
            "financial_priorities": "education|emergency_savings",
            "expense_categories_to_protect": "rent|groceries",
            "expense_categories_user_is_willing_to_reduce": "dining",
            "expense_categories_user_is_willing_to_stop": "streaming",
            "payment_methods_user_will_consider": "full_payment|installments",
            "max_installment_months": "6",
        },
        {
            "user_id": "user_02", "home_currency": "EUR",
            "current_available_balance": "5000", "minimum_balance_to_keep": "800",
            "financial_priorities": "travel",
            "expense_categories_to_protect": "rent",
            "expense_categories_user_is_willing_to_reduce": "",
            "expense_categories_user_is_willing_to_stop": "",
            "payment_methods_user_will_consider": "full_payment",
            "max_installment_months": "",
        },
    ],
    "requests.csv": [
        {
            "request_id": "request_01", "user_id": "user_01", "request_date": "2024-03-03",
            "request_type": "purchase", "requested_amount": "2500",
            "desired_completion_date": "2024-03-20", "allows_partial_payment": "true",
            "request_text": "Can I afford this laptop?",
        },
        {
            # A SECOND request for user_01, so scoping can be tested with a
            # same-user/different-request reference. Pointing such a reference at
            # user_02's request instead would be a cross-user defect (A13), not a
            # scoping fixture.
            "request_id": "request_02", "user_id": "user_01", "request_date": "2024-03-05",
            "request_type": "education", "requested_amount": "1000",
            "desired_completion_date": "2024-04-01", "allows_partial_payment": "false",
            "request_text": "Can I afford this course?",
        },
    ],
    "sample_requests.csv": [
        {
            "request_id": "sample_01", "user_id": "user_02", "request_date": "2024-06-01",
            "request_type": "travel", "requested_amount": "900",
            "desired_completion_date": "2024-07-01", "allows_partial_payment": "false",
            "request_text": "Can I afford this trip?",
            "amount_safe_to_pay": "900", "affordability_status": "affordable_now",
            "recommended_payment_method": "full_payment",
            "payment_plan": "2024-06-01:900", "earliest_date_for_full_payment": "2024-06-01",
            "spending_changes_needed": "none",
            "decision_explanation": "Pay EUR 900 today.",
        },
    ],
    "financial_events.csv": [
        {
            "event_id": "event_01", "user_id": "user_01", "event_type": "expense",
            "description": "Apartment rent", "category": "rent", "direction": "debit",
            "amount": "3000", "currency": "ZAR", "event_date": "2024-02-02",
            "settlement_date": "2024-02-02", "status": "settled", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        },
        {
            "event_id": "event_02", "user_id": "user_01", "event_type": "expense",
            "description": "Takeaway", "category": "dining", "direction": "debit",
            "amount": "400.50", "currency": "ZAR", "event_date": "2024-02-10",
            "settlement_date": "2024-02-10", "status": "settled", "linked_event_id": "",
            "flexibility": "reducible", "minimum_allowed_amount": "150",
        },
        {
            "event_id": "event_03", "user_id": "user_01", "event_type": "subscription",
            "description": "Streaming plan", "category": "streaming", "direction": "debit",
            "amount": "99", "currency": "ZAR", "event_date": "2024-02-13",
            "settlement_date": "2024-02-13", "status": "settled", "linked_event_id": "",
            "flexibility": "stoppable", "minimum_allowed_amount": "",
        },
        {
            # Blank amount: UNKNOWN, resolvable only via the linked image.
            "event_id": "event_04", "user_id": "user_01", "event_type": "income",
            "description": "February salary", "category": "salary", "direction": "credit",
            "amount": "", "currency": "ZAR", "event_date": "2024-02-15",
            "settlement_date": "2024-02-15", "status": "settled", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        },
        {
            # Foreign-currency event: needs an exact directed settlement-date rate.
            "event_id": "event_05", "user_id": "user_01", "event_type": "expense",
            "description": "Overseas course", "category": "education", "direction": "debit",
            "amount": "100", "currency": "EUR", "event_date": "2024-02-15",
            "settlement_date": "2024-02-15", "status": "settled", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        },
        {
            "event_id": "event_06", "user_id": "user_02", "event_type": "expense",
            "description": "Rent", "category": "rent", "direction": "debit",
            "amount": "1200", "currency": "EUR", "event_date": "2024-05-02",
            "settlement_date": "2024-05-02", "status": "settled", "linked_event_id": "",
            "flexibility": "fixed", "minimum_allowed_amount": "",
        },
    ],
    "request_payment_options.csv": [
        {
            "payment_option_id": "payment_option_01", "request_id": "request_01",
            "payment_method": "full_payment", "payment_amount": "2500",
            "number_of_payments": "1", "first_payment_date": "2024-03-03",
            "payment_frequency_days": "", "financing_fee": "0",
            "total_payable_amount": "2500",
        },
        {
            "payment_option_id": "payment_option_02", "request_id": "request_01",
            "payment_method": "installments", "payment_amount": "880",
            "number_of_payments": "3", "first_payment_date": "2024-03-06",
            "payment_frequency_days": "30", "financing_fee": "140",
            "total_payable_amount": "2640",
        },
        {
            "payment_option_id": "payment_option_05", "request_id": "request_02",
            "payment_method": "full_payment", "payment_amount": "1000",
            "number_of_payments": "1", "first_payment_date": "2024-03-05",
            "payment_frequency_days": "", "financing_fee": "0",
            "total_payable_amount": "1000",
        },
        {
            "payment_option_id": "payment_option_06", "request_id": "request_02",
            "payment_method": "installments", "payment_amount": "360",
            "number_of_payments": "3", "first_payment_date": "2024-03-08",
            "payment_frequency_days": "30", "financing_fee": "80",
            "total_payable_amount": "1080",
        },
        {
            "payment_option_id": "payment_option_03", "request_id": "sample_01",
            "payment_method": "full_payment", "payment_amount": "900",
            "number_of_payments": "1", "first_payment_date": "2024-06-01",
            "payment_frequency_days": "", "financing_fee": "0",
            "total_payable_amount": "900",
        },
        {
            "payment_option_id": "payment_option_04", "request_id": "sample_01",
            "payment_method": "installments", "payment_amount": "320",
            "number_of_payments": "3", "first_payment_date": "2024-06-05",
            "payment_frequency_days": "30", "financing_fee": "60",
            "total_payable_amount": "960",
        },
    ],
    "messages.csv": [
        {
            "message_id": "message_01", "user_id": "user_01", "request_id": "",
            "related_event_id": "event_04", "sent_at": "2024-02-16T09:30:00Z",
            "source_type": "employer",
            "message_text": "Your February payslip is attached. Ref EMP-0001.",
        },
        {
            # Same user, a DIFFERENT request: must not leak into request_01's scope.
            "message_id": "message_02", "user_id": "user_01", "request_id": "request_02",
            "related_event_id": "", "sent_at": "2024-02-17T09:30:00Z",
            "source_type": "bank",
            "message_text": "Unrelated to request_01.",
        },
    ],
    "images.csv": [
        {
            "image_id": "image_01", "user_id": "user_01", "request_id": "",
            "related_event_id": "event_04",
        },
    ],
    "exchange_rates.csv": [
        {"rate_date": "2024-02-15", "from_currency": "EUR", "to_currency": "ZAR", "rate": "20"},
        {"rate_date": "2024-02-15", "from_currency": "USD", "to_currency": "ZAR", "rate": "18.5"},
    ],
}


def build_dataset(root: Path, *, mutate=None) -> Path:
    """Write a valid synthetic dataset under `root/dataset` and return that path.

    `mutate(name, rows) -> rows` lets a test corrupt exactly one file.
    """
    dataset = Path(root) / "dataset"
    (dataset / "media" / "images").mkdir(parents=True, exist_ok=True)

    tables = {name: [dict(r) for r in rows] for name, rows in ROWS.items()}
    tables["output.csv"] = [
        {**{c: "" for c in EXPECTED_HEADERS["output.csv"]}, "request_id": r["request_id"]}
        for r in tables["requests.csv"]
    ]

    for name, rows in tables.items():
        if mutate is not None:
            rows = mutate(name, rows)
        write_table(dataset / name, name, rows)

    # Only materialise files for ids that are safe path components. A test that
    # injects a hostile id wants the *loader* to reject it, so the fixture must
    # not try (and fail) to create the escaping file itself.
    for image in tables.get("images.csv", []):
        image_id = image["image_id"]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", image_id or ""):
            (dataset / "media" / "images" / f"{image_id}.png").write_bytes(PNG_BYTES)

    return dataset


def write_table(path: Path, name: str, rows: list[dict[str, str]], header=None) -> None:
    header = header or EXPECTED_HEADERS[name]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def edit(name: str, index: int, **changes):
    """Return a `mutate` callable that patches one row of one file."""
    def _mutate(table: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        if table == name:
            rows[index] = {**rows[index], **changes}
        return rows
    return _mutate


def append(name: str, row: dict[str, str]):
    def _mutate(table: str, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        if table == name:
            rows = rows + [row]
        return rows
    return _mutate
