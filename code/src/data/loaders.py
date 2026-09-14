import csv
from datetime import date
from pathlib import Path
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    FinancialEvent,
    PaymentOption,
)


def parse_date(val: str) -> date:
    return date.fromisoformat(val.strip())


def parse_opt_date(val: str | None) -> date | None:
    if not val or not val.strip():
        return None
    return date.fromisoformat(val.strip())


def parse_pipe_list(val: str | None) -> list[str]:
    if not val or not val.strip():
        return []
    return [item.strip() for item in val.strip().split("|") if item.strip()]


def load_requests(csv_path: Path) -> dict[str, RequestContext]:
    requests = {}
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            req = RequestContext(
                request_id=row["request_id"].strip(),
                user_id=row["user_id"].strip(),
                request_date=parse_date(row["request_date"]),
                request_type=row["request_type"].strip(),
                requested_amount=float(row["requested_amount"]),
                desired_completion_date=parse_date(row["desired_completion_date"]),
                allows_partial_payment=row["allows_partial_payment"].strip().lower() == "true",
                request_text=row["request_text"].strip(),
            )
            requests[req.request_id] = req
    return requests


def load_profiles(csv_path: Path) -> dict[str, UserFinancialProfile]:
    profiles = {}
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            max_inst = row.get("max_installment_months", "").strip()
            prof = UserFinancialProfile(
                user_id=row["user_id"].strip(),
                home_currency=row["home_currency"].strip(),
                current_available_balance=float(row["current_available_balance"]),
                minimum_balance_to_keep=float(row["minimum_balance_to_keep"]),
                financial_priorities=parse_pipe_list(row.get("financial_priorities")),
                expense_categories_to_protect=parse_pipe_list(row.get("expense_categories_to_protect")),
                expense_categories_user_is_willing_to_reduce=parse_pipe_list(row.get("expense_categories_user_is_willing_to_reduce")),
                expense_categories_user_is_willing_to_stop=parse_pipe_list(row.get("expense_categories_user_is_willing_to_stop")),
                payment_methods_user_will_consider=parse_pipe_list(row.get("payment_methods_user_will_consider")),
                max_installment_months=int(max_inst) if max_inst else None,
            )
            profiles[prof.user_id] = prof
    return profiles


def load_events(csv_path: Path) -> list[FinancialEvent]:
    events = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amt_str = row.get("amount", "").strip()
            min_amt_str = row.get("minimum_allowed_amount", "").strip()
            linked_id = row.get("linked_event_id", "").strip() or None
            
            ev = FinancialEvent(
                event_id=row["event_id"].strip(),
                user_id=row["user_id"].strip(),
                event_type=row["event_type"].strip(),
                description=row["description"].strip(),
                category=row["category"].strip(),
                direction=row["direction"].strip(),
                amount=float(amt_str) if amt_str else None,
                currency=row["currency"].strip(),
                event_date=parse_date(row["event_date"]),
                settlement_date=parse_date(row["settlement_date"]) if row.get("settlement_date") else parse_date(row["event_date"]),
                status=row["status"].strip(),
                linked_event_id=linked_id,
                flexibility=row["flexibility"].strip(),
                minimum_allowed_amount=float(min_amt_str) if min_amt_str else None,
            )
            events.append(ev)
    return events


def load_payment_options(csv_path: Path) -> list[PaymentOption]:
    options = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            freq_str = row.get("payment_frequency_days", "").strip()
            opt = PaymentOption(
                payment_option_id=row["payment_option_id"].strip(),
                request_id=row["request_id"].strip(),
                payment_method=row["payment_method"].strip(),
                payment_amount=float(row["payment_amount"]),
                number_of_payments=int(row["number_of_payments"]),
                first_payment_date=parse_date(row["first_payment_date"]),
                payment_frequency_days=int(freq_str) if freq_str else None,
                financing_fee=float(row.get("financing_fee", 0.0)),
                total_payable_amount=float(row["total_payable_amount"]),
            )
            options.append(opt)
    return options
