from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"
OUTPUT_PATH = ROOT / "output.csv"


def to_decimal(value: str | float | Decimal | None) -> Decimal:
    if value in (None, "", " "):
        return Decimal("0")
    return Decimal(str(value))


def fmt_money(value: Decimal | float | str) -> str:
    d = Decimal(str(value))
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def add_days(d: Optional[date], days: int) -> Optional[date]:
    if d is None:
        return None
    return d + timedelta(days=days)


@dataclass
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: List[str]
    expense_categories_to_protect: List[str]
    expense_categories_user_is_willing_to_reduce: List[str]
    expense_categories_user_is_willing_to_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[int]


@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Decimal
    currency: str
    event_date: Optional[date]
    settlement_date: Optional[date]
    status: str
    linked_event_id: str
    flexibility: str
    minimum_allowed_amount: Decimal


@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: Optional[date]
    payment_frequency_days: int
    financing_fee: Decimal
    total_payable_amount: Decimal


def read_profiles() -> Dict[str, Profile]:
    out: Dict[str, Profile] = {}
    with open(DATASET_DIR / "financial_profiles.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            user_id = row["user_id"]
            out[user_id] = Profile(
                user_id=user_id,
                home_currency=row.get("home_currency", ""),
                current_available_balance=to_decimal(row.get("current_available_balance")),
                minimum_balance_to_keep=to_decimal(row.get("minimum_balance_to_keep")),
                financial_priorities=(row.get("financial_priorities") or "").split("|") if row.get("financial_priorities") else [],
                expense_categories_to_protect=(row.get("expense_categories_to_protect") or "").split("|") if row.get("expense_categories_to_protect") else [],
                expense_categories_user_is_willing_to_reduce=(row.get("expense_categories_user_is_willing_to_reduce") or "").split("|") if row.get("expense_categories_user_is_willing_to_reduce") else [],
                expense_categories_user_is_willing_to_stop=(row.get("expense_categories_user_is_willing_to_stop") or "").split("|") if row.get("expense_categories_user_is_willing_to_stop") else [],
                payment_methods_user_will_consider=(row.get("payment_methods_user_will_consider") or "").split("|") if row.get("payment_methods_user_will_consider") else [],
                max_installment_months=int(row["max_installment_months"]) if row.get("max_installment_months") else None,
            )
    return out


def read_requests() -> List[Request]:
    rows: List[Request] = []
    with open(DATASET_DIR / "requests.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                Request(
                    request_id=row["request_id"],
                    user_id=row["user_id"],
                    request_date=parse_date(row["request_date"]) or date.today(),
                    request_type=row["request_type"],
                    requested_amount=to_decimal(row["requested_amount"]),
                    desired_completion_date=parse_date(row["desired_completion_date"]) or date.today(),
                    allows_partial_payment=str(row.get("allows_partial_payment", "false")).lower() == "true",
                    request_text=row.get("request_text", ""),
                )
            )
    return rows


def read_events() -> Dict[str, List[Event]]:
    events_by_user: Dict[str, List[Event]] = defaultdict(list)
    with open(DATASET_DIR / "financial_events.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            user_id = row["user_id"]
            amount = to_decimal(row.get("amount"))
            if row.get("amount") in (None, ""):
                amount = Decimal("0")
            e = Event(
                event_id=row["event_id"],
                user_id=user_id,
                event_type=row.get("event_type", ""),
                description=row.get("description", ""),
                category=row.get("category", ""),
                direction=row.get("direction", ""),
                amount=amount,
                currency=row.get("currency", ""),
                event_date=parse_date(row.get("event_date")),
                settlement_date=parse_date(row.get("settlement_date")),
                status=row.get("status", ""),
                linked_event_id=row.get("linked_event_id", ""),
                flexibility=row.get("flexibility", ""),
                minimum_allowed_amount=to_decimal(row.get("minimum_allowed_amount")),
            )
            events_by_user[user_id].append(e)
    for user_id in events_by_user:
        events_by_user[user_id].sort(key=lambda e: (e.settlement_date or e.event_date or date.min, e.event_id))
    return events_by_user


def read_payment_options() -> Dict[str, List[PaymentOption]]:
    out: Dict[str, List[PaymentOption]] = defaultdict(list)
    with open(DATASET_DIR / "request_payment_options.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            opt = PaymentOption(
                payment_option_id=row["payment_option_id"],
                request_id=row["request_id"],
                payment_method=row.get("payment_method", ""),
                payment_amount=to_decimal(row.get("payment_amount")),
                number_of_payments=int(row.get("number_of_payments") or 0),
                first_payment_date=parse_date(row.get("first_payment_date")),
                payment_frequency_days=int(row.get("payment_frequency_days") or 0),
                financing_fee=to_decimal(row.get("financing_fee")),
                total_payable_amount=to_decimal(row.get("total_payable_amount")),
            )
            out[row["request_id"]].append(opt)
    for request_id in out:
        out[request_id].sort(key=lambda o: (o.payment_option_id, o.first_payment_date or date.min))
    return out


def date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def profile_allows_stop(profile: Profile, category: str) -> bool:
    return category in profile.expense_categories_user_is_willing_to_stop


def profile_allows_reduce(profile: Profile, category: str) -> bool:
    return category in profile.expense_categories_user_is_willing_to_reduce


def event_updates_for_date(events: List[Event], day: date, actions: Dict[str, Tuple[str, Decimal]]) -> Tuple[Decimal, Decimal]:
    credits = Decimal("0")
    debits = Decimal("0")
    for e in events:
        if (e.settlement_date or e.event_date) != day:
            continue
        if e.status not in {"settled", "pending", "scheduled"}:
            continue
        if e.direction == "credit" and e.status == "settled":
            credits += e.amount
            continue
        if e.direction == "debit":
            amount = e.amount
            action = actions.get(e.event_id)
            if action:
                kind, value = action
                if kind == "stop":
                    amount = Decimal("0")
                elif kind == "reduce":
                    amount = value
            debits += amount
    return credits, debits


def simulate_plan(
    profile: Profile,
    user_events: List[Event],
    request_date: date,
    amount_to_pay_on_request: Decimal,
    request_amount: Decimal,
    spending_actions: Optional[List[Tuple[str, str, Decimal]]] = None,
    later_plan: Optional[List[Tuple[date, Decimal]]] = None,
    day_window: int = 90,
) -> Tuple[bool, Decimal, Decimal]:
    end = request_date + timedelta(days=day_window)
    actions_map: Dict[str, Tuple[str, Decimal]] = {}
    if spending_actions:
        for kind, event_id, value in spending_actions:
            actions_map[event_id] = (kind, value)

    balance = profile.current_available_balance
    minimum_seen = balance
    for day in date_range(request_date, end):
        day_events = [e for e in user_events if (e.settlement_date or e.event_date) == day and e.status not in {"cancelled", "failed", "unrealized"}]
        credits, debits = event_updates_for_date(day_events, day, actions_map)
        balance += credits
        balance -= debits
        for payment_date, payment_amount in later_plan or []:
            if payment_date == day and payment_amount > 0:
                balance -= payment_amount
        if day == request_date:
            balance -= amount_to_pay_on_request
        minimum_seen = min(minimum_seen, balance)
        if balance < profile.minimum_balance_to_keep:
            return False, minimum_seen, balance
    return True, minimum_seen, balance


def generate_installment_schedule(option: PaymentOption) -> List[Tuple[date, Decimal]]:
    if option.number_of_payments <= 0 or option.first_payment_date is None:
        return []
    schedule: List[Tuple[date, Decimal]] = []
    for idx in range(option.number_of_payments):
        payment_date = option.first_payment_date + timedelta(days=idx * max(option.payment_frequency_days, 1))
        schedule.append((payment_date, option.payment_amount))
    return schedule


def safe_for_amount(profile: Profile, user_events: List[Event], request: Request, amount: Decimal, actions=None) -> bool:
    return simulate_plan(profile, user_events, request.request_date, amount, request.requested_amount, spending_actions=actions or [], later_plan=[])[0]


def find_earliest_full_payment_date(profile: Profile, user_events: List[Event], request: Request) -> Optional[date]:
    for day in date_range(request.request_date, request.request_date + timedelta(days=90)):
        ok, _, _ = simulate_plan(profile, user_events, day, request.requested_amount, request.requested_amount, later_plan=[])
        if ok:
            return day
    return None


def compute_amount_safe_today(profile: Profile, user_events: List[Event], request: Request) -> Decimal:
    high = int((request.requested_amount * Decimal("100")).to_integral_value(ROUND_HALF_UP))
    low = 0
    best = 0
    while low <= high:
        mid = (low + high) // 2
        amount = Decimal(mid) / Decimal("100")
        if safe_for_amount(profile, user_events, request, amount):
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return Decimal(best) / Decimal("100")


def discover_spending_changes(profile: Profile, user_events: List[Event], request: Request) -> List[Tuple[str, str, Decimal]]:
    window_end = request.request_date + timedelta(days=90)
    candidate_events: List[Event] = []
    for e in user_events:
        if e.direction != "debit":
            continue
        if e.status not in {"settled", "pending", "scheduled"}:
            continue
        day = e.settlement_date or e.event_date
        if day is None or not (request.request_date <= day <= window_end):
            continue
        if not e.category or e.flexibility in {"fixed", ""}:
            continue
        if e.category in profile.expense_categories_to_protect:
            continue
        candidate_events.append(e)

    actions: List[Tuple[str, str, Decimal]] = []
    for e in candidate_events:
        if e.category and profile_allows_stop(profile, e.category):
            actions.append(("stop", e.event_id, Decimal("0")))
        if e.category and profile_allows_reduce(profile, e.category):
            target = e.minimum_allowed_amount if e.minimum_allowed_amount > 0 else (e.amount * Decimal("0.5"))
            if target < e.amount:
                actions.append(("reduce", e.event_id, target))

    # Do not combine stop and reduce on the same event; keep to valid combinations only.
    seen = set()
    deduped: List[Tuple[str, str, Decimal]] = []
    for action in actions:
        if action[1] not in seen:
            deduped.append(action)
            seen.add(action[1])

    for size in range(1, min(4, len(deduped) + 1)):
        for combo in combinations(deduped, size):
            used = set()
            valid = True
            for kind, event_id, value in combo:
                if event_id in used:
                    valid = False
                    break
                used.add(event_id)
            if not valid:
                continue
            if safe_for_amount(profile, user_events, request, request.requested_amount, list(combo)):
                return list(combo)
    return []


def form_plan_string(plan: List[Tuple[date, Decimal]]) -> str:
    return "|".join(f"{d.isoformat()}:{fmt_money(amount)}" for d, amount in plan)


def evaluate_request(profile: Profile, user_events: List[Event], request: Request, payment_options: List[PaymentOption]) -> Dict[str, str]:
    amount_safe = compute_amount_safe_today(profile, user_events, request)
    earliest_full = find_earliest_full_payment_date(profile, user_events, request)
    earliest_iso = earliest_full.isoformat() if earliest_full else ""
    methods = set(profile.payment_methods_user_will_consider)
    candidates: List[Dict[str, object]] = []

    if "full_payment" in methods and safe_for_amount(profile, user_events, request, request.requested_amount):
        candidates.append({
            "method": "full_payment",
            "status": "affordable_now",
            "plan": f"{request.request_date.isoformat()}:{fmt_money(request.requested_amount)}",
            "first_payment_date": request.request_date,
            "payments": 1,
            "cost": request.requested_amount,
            "changes": [],
            "deadline_ok": request.request_date <= request.desired_completion_date,
            "option_id": "full_payment",
        })

    spending_changes = discover_spending_changes(profile, user_events, request)
    if "full_payment" in methods and spending_changes and safe_for_amount(profile, user_events, request, request.requested_amount, spending_changes):
        candidates.append({
            "method": "full_payment",
            "status": "affordable_with_plan",
            "plan": f"{request.request_date.isoformat()}:{fmt_money(request.requested_amount)}",
            "first_payment_date": request.request_date,
            "payments": 1,
            "cost": request.requested_amount,
            "changes": spending_changes,
            "deadline_ok": request.request_date <= request.desired_completion_date,
            "option_id": "full_payment",
        })

    if request.allows_partial_payment and "partial_payment" in methods and amount_safe > 0 and amount_safe < request.requested_amount and earliest_full is not None and earliest_full <= request.desired_completion_date:
        second = request.requested_amount - amount_safe
        candidates.append({
            "method": "partial_payment",
            "status": "affordable_with_plan",
            "plan": f"{request.request_date.isoformat()}:{fmt_money(amount_safe)}|{earliest_full.isoformat()}:{fmt_money(second)}",
            "first_payment_date": request.request_date,
            "payments": 2,
            "cost": request.requested_amount,
            "changes": [],
            "deadline_ok": earliest_full <= request.desired_completion_date,
            "option_id": "partial_payment",
        })

    for option in payment_options:
        if option.payment_method != "installments":
            continue
        if "installments" not in methods:
            continue
        if profile.max_installment_months is not None and option.number_of_payments > profile.max_installment_months:
            continue
        schedule = generate_installment_schedule(option)
        if not schedule:
            continue
        if option.first_payment_date is None:
            continue
        # Check the schedule is feasible without violating the minimum balance.
        ok = True
        balance = profile.current_available_balance
        for day in date_range(request.request_date, request.request_date + timedelta(days=90)):
            for e in user_events:
                if (e.settlement_date or e.event_date) != day:
                    continue
                if e.status in {"cancelled", "failed", "unrealized"}:
                    continue
                if e.direction == "credit" and e.status == "settled":
                    balance += e.amount
                elif e.direction == "debit" and e.status in {"settled", "pending", "scheduled"}:
                    balance -= e.amount
            for payment_date, payment_amount in schedule:
                if payment_date == day:
                    balance -= payment_amount
            if balance < profile.minimum_balance_to_keep:
                ok = False
                break
            if not ok:
                break
        if not ok:
            continue
        candidates.append({
            "method": "installments",
            "status": "affordable_with_plan",
            "plan": form_plan_string(schedule),
            "first_payment_date": schedule[0][0],
            "payments": len(schedule),
            "cost": option.total_payable_amount,
            "changes": [],
            "deadline_ok": schedule[-1][0] <= request.desired_completion_date,
            "option_id": option.payment_option_id,
        })

    if "full_payment" in methods and earliest_full is not None and earliest_full > request.request_date and earliest_full <= request.desired_completion_date:
        candidates.append({
            "method": "wait",
            "status": "affordable_later",
            "plan": f"{earliest_full.isoformat()}:{fmt_money(request.requested_amount)}",
            "first_payment_date": earliest_full,
            "payments": 1,
            "cost": request.requested_amount,
            "changes": [],
            "deadline_ok": earliest_full <= request.desired_completion_date,
            "option_id": "wait",
        })

    def sort_key(candidate: Dict[str, object]) -> Tuple[int, int, Decimal, date, int, str]:
        deadline_ok = 0 if bool(candidate["deadline_ok"]) else 1
        no_change = 0 if not bool(candidate["changes"]) else 1
        cost = Decimal(str(candidate["cost"]))
        first_date = candidate["first_payment_date"]
        payment_count = int(candidate["payments"])
        option_id = str(candidate["option_id"])
        return (deadline_ok, no_change, cost, first_date, payment_count, option_id)

    if not candidates:
        return {
            "request_id": request.request_id,
            "amount_safe_to_pay": fmt_money(amount_safe),
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "payment_plan": "none",
            "earliest_date_for_full_payment": earliest_iso,
            "spending_changes_needed": "none",
            "decision_explanation": f"Do not proceed. None of the available options keeps the {fmt_money(profile.minimum_balance_to_keep)} minimum protected.",
        }

    selected = sorted(candidates, key=sort_key)[0]
    method = str(selected["method"])
    status = str(selected["status"])
    plan_text = str(selected["plan"])
    changes_text = "none"
    if selected.get("changes"):
        pieces = []
        for kind, event_id, value in selected["changes"]:
            if kind == "stop":
                pieces.append(f"stop:{event_id}")
            elif kind == "reduce":
                pieces.append(f"reduce_to:{event_id}:{fmt_money(value)}")
        changes_text = "|".join(pieces)

    if method == "full_payment":
        if earliest_full is not None and earliest_full == request.request_date:
            status = "affordable_now"
        else:
            status = "affordable_with_plan"
    elif method in {"installments", "partial_payment"}:
        status = "affordable_with_plan"
    elif method == "wait":
        status = "affordable_later"

    if method == "full_payment":
        if selected.get("changes"):
            explanation = f"Apply the recommended spending change(s), then pay {fmt_money(request.requested_amount)} today. This keeps at least {fmt_money(profile.minimum_balance_to_keep)} available."
        else:
            explanation = f"Pay {fmt_money(request.requested_amount)} today. This leaves at least {fmt_money(profile.minimum_balance_to_keep)} available over the next 90 days."
    elif method == "partial_payment":
        second = request.requested_amount - amount_safe
        explanation = f"Pay {fmt_money(amount_safe)} today and the remaining {fmt_money(second)} on {earliest_full.isoformat()} to complete the request while preserving the {fmt_money(profile.minimum_balance_to_keep)} minimum balance."
    elif method == "installments":
        if selected.get("plan"):
            parts = str(selected["plan"]).split("|")
            if parts:
                first_amount = parts[0].split(":", 1)[1]
                explanation = f"Use installments of {fmt_money(first_amount)} starting {parts[0].split(':',1)[0]}. This keeps the {fmt_money(profile.minimum_balance_to_keep)} minimum protected."
            else:
                explanation = f"Use installments. This keeps the {fmt_money(profile.minimum_balance_to_keep)} minimum protected."
    elif method == "wait":
        explanation = f"Wait until {earliest_full.isoformat()} to pay the full amount. Paying earlier would take the balance below the {fmt_money(profile.minimum_balance_to_keep)} minimum."
    else:
        explanation = f"Do not proceed. None of the available options keeps the {fmt_money(profile.minimum_balance_to_keep)} minimum protected."

    return {
        "request_id": request.request_id,
        "amount_safe_to_pay": fmt_money(amount_safe),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_text,
        "earliest_date_for_full_payment": earliest_iso,
        "spending_changes_needed": changes_text,
        "decision_explanation": explanation,
    }


def validate_output(rows: List[Dict[str, str]]) -> None:
    required = [
        "request_id",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ]
    if not rows:
        raise ValueError("No output rows generated.")
    if list(rows[0].keys()) != required:
        raise ValueError(f"Output metadata mismatch: {list(rows[0].keys())} vs {required}")
    seen = set()
    for row in rows:
        rid = row["request_id"]
        if rid in seen:
            raise ValueError(f"Duplicate request_id: {rid}")
        seen.add(rid)
        amount = to_decimal(row["amount_safe_to_pay"])
        if amount < 0:
            raise ValueError(f"Negative amount_safe_to_pay for {rid}")
        if row["recommended_payment_method"] not in {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}:
            raise ValueError(f"Bad payment method: {row['recommended_payment_method']}")
        if row["affordability_status"] not in {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}:
            raise ValueError(f"Bad affordability status: {row['affordability_status']}")


def write_output(rows: List[Dict[str, str]]) -> None:
    fieldnames = [
        "request_id",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    profiles = read_profiles()
    events_by_user = read_events()
    payment_options = read_payment_options()
    requests = read_requests()
    output_rows: List[Dict[str, str]] = []

    for request in requests:
        profile = profiles.get(request.user_id)
        if profile is None:
            output_rows.append({
                "request_id": request.request_id,
                "amount_safe_to_pay": "0",
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": "No user profile found.",
            })
            continue
        row = evaluate_request(profile, events_by_user.get(request.user_id, []), request, payment_options.get(request.request_id, []))
        output_rows.append(row)

    validate_output(output_rows)
    write_output(output_rows)
    print(f"Wrote {len(output_rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
