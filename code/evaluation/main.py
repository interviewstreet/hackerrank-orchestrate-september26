from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
OUTPUT = ROOT / "output.csv"

OUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

ZERO = Decimal("0")
ONE = Decimal("1")


def read_csv(name: str) -> list[dict[str, str]]:
    path = DATASET / name
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def first(row: dict, *names: str, default=""):
    lowered = {str(k).strip().lower(): v for k, v in row.items()}

    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip() != "":
            return value

    for key, value in lowered.items():
        for name in names:
            if name.lower() in key and str(value).strip() != "":
                return value

    return default


def decimal(value, default=ZERO) -> Decimal:
    if value is None:
        return default

    text = str(value).strip().replace(",", "")
    if not text:
        return default

    text = re.sub(r"[^\d.\-]", "", text)

    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def money(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value == value.to_integral():
        return str(int(value))
    return format(value, "f")


def parse_date(value) -> date | None:
    if not value:
        return None

    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def parse_bool(value) -> bool:
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
        "accepted",
        "allow",
    }


def normalize_currency(value: str) -> str:
    return str(value or "").strip().upper()


def clean_status(row: dict) -> str:
    return str(
        first(
            row,
            "status",
            "event_status",
            "transaction_status",
            "state",
            default="",
        )
    ).strip().lower()


def is_ignored_event(row: dict) -> bool:
    status = clean_status(row)

    ignored = {
        "failed",
        "cancelled",
        "canceled",
        "rejected",
        "declined",
        "duplicate",
        "unrealized",
    }

    if status in ignored:
        return True

    event_type = str(
        first(row, "event_type", "transaction_type", "type", default="")
    ).lower()

    return "unrealized" in event_type or "failed" in event_type


def event_date(row: dict) -> date | None:
    return parse_date(
        first(
            row,
            "event_date",
            "transaction_date",
            "date",
            "scheduled_date",
            "settlement_date",
            "due_date",
        )
    )


def event_amount(row: dict) -> Decimal:
    return decimal(
        first(
            row,
            "amount",
            "event_amount",
            "transaction_amount",
            "value",
            default="",
        )
    )


def event_currency(row: dict) -> str:
    return normalize_currency(
        first(row, "currency", "event_currency", "transaction_currency")
    )


def is_income(row: dict) -> bool:
    text = " ".join(
        str(first(row, key, default="")).lower()
        for key in ("event_type", "transaction_type", "type", "category", "description")
    )

    return any(
        token in text
        for token in (
            "income",
            "salary",
            "payroll",
            "credit",
            "refund",
            "deposit",
        )
    )


def is_recurring(row: dict) -> bool:
    value = first(
        row,
        "is_recurring",
        "recurring",
        "recurrence",
        "frequency",
        default="",
    )

    if parse_bool(value):
        return True

    text = str(value).lower()
    return any(token in text for token in ("monthly", "weekly", "recurring"))


def recurrence_days(row: dict) -> int:
    value = decimal(
        first(
            row,
            "recurrence_days",
            "interval_days",
            "days_between",
            "frequency_days",
            default="",
        )
    )

    if value > 0:
        return max(1, int(value))

    text = str(
        first(row, "frequency", "recurrence", "period", default="")
    ).lower()

    if "weekly" in text:
        return 7
    if "biweekly" in text or "fortnight" in text:
        return 14
    if "monthly" in text:
        return 30

    return 30


def is_flexible(row: dict) -> bool:
    return parse_bool(
        first(
            row,
            "is_flexible",
            "flexible",
            "can_adjust",
            "adjustable",
            default="false",
        )
    )


def build_rates(rows: list[dict]) -> dict[tuple[str, str, date], Decimal]:
    rates = {}

    for row in rows:
        row_date = parse_date(first(row, "rate_date", "date", "effective_date"))
        base = normalize_currency(
            first(row, "base_currency", "from_currency", "source_currency")
        )
        quote = normalize_currency(
            first(row, "quote_currency", "to_currency", "target_currency")
        )
        rate = decimal(first(row, "rate", "exchange_rate", "value"))

        if row_date and base and quote and rate > ZERO:
            rates[(base, quote, row_date)] = rate

    return rates


def convert(
    amount: Decimal,
    currency: str,
    home_currency: str,
    row_date: date,
    rates: dict[tuple[str, str, date], Decimal],
) -> Decimal:
    currency = normalize_currency(currency)
    home_currency = normalize_currency(home_currency)

    if not currency or currency == home_currency:
        return amount

    direct = rates.get((currency, home_currency, row_date))
    if direct:
        return amount * direct

    inverse = rates.get((home_currency, currency, row_date))
    if inverse:
        return amount / inverse

    # Try nearest supplied date only if the exact date is unavailable.
    candidates = [
        (d, r)
        for (base, quote, d), r in rates.items()
        if base == currency and quote == home_currency
    ]

    if candidates:
        _, nearest = min(
            candidates,
            key=lambda item: abs((item[0] - row_date).days),
        )
        return amount * nearest

    inverse_candidates = [
        (d, r)
        for (base, quote, d), r in rates.items()
        if base == home_currency and quote == currency
    ]

    if inverse_candidates:
        _, nearest = min(
            inverse_candidates,
            key=lambda item: abs((item[0] - row_date).days),
        )
        return amount / nearest

    # Safer fallback: do not invent a conversion.
    return ZERO


def profile_balance(profile: dict) -> Decimal:
    return decimal(
        first(
            profile,
            "available_balance",
            "current_balance",
            "balance",
            "cash_balance",
            "opening_balance",
        )
    )


def profile_floor(profile: dict) -> Decimal:
    return decimal(
        first(
            profile,
            "minimum_balance_to_keep",
            "minimum_balance",
            "preferred_minimum_balance",
            "min_balance",
            default="0",
        )
    )


def accepted_methods(profile: dict) -> set[str]:
    raw = first(
        profile,
        "payment_methods_user_will_consider",
        "payment_methods",
        "accepted_payment_methods",
        default="full_payment",
    )

    values = re.split(r"[,|;/]+", str(raw).lower())

    result = set()

    for value in values:
        value = value.strip().replace(" ", "_")

        if "full" in value:
            result.add("full_payment")
        elif "partial" in value:
            result.add("partial_payment")
        elif "install" in value:
            result.add("installments")
        elif value:
            result.add(value)

    return result or {"full_payment"}


def extract_message_facts(messages: list[dict]) -> dict[str, dict]:
    """
    Conservative message interpretation.

    Messages are never allowed to create unsupported events. This function
    only records textual references for explanations and future extraction.
    """
    facts = {}

    for row in messages:
        related = first(row, "related_event_id", "event_id", default="")
        if related:
            facts[related] = row

    return facts


def build_event_index(
    events: list[dict],
    home_currency: str,
    request_date: date,
    rates: dict[tuple[str, str, date], Decimal],
) -> list[dict]:
    normalized = []
    seen = set()

    for row in events:
        if is_ignored_event(row):
            continue

        event_id = first(row, "event_id", "id", default="")
        row_date = event_date(row)

        if not row_date or row_date < request_date:
            continue

        amount = event_amount(row)
        currency = event_currency(row)

        if currency != home_currency:
            amount = convert(
                amount,
                currency,
                home_currency,
                row_date,
                rates,
            )

        if amount == ZERO:
            continue

        identity = (
            event_id,
            row_date,
            amount,
            is_income(row),
        )

        if identity in seen:
            continue

        seen.add(identity)

        normalized.append(
            {
                "event_id": event_id,
                "date": row_date,
                "amount": amount,
                "income": is_income(row),
                "recurring": is_recurring(row),
                "flexible": is_flexible(row),
                "interval": recurrence_days(row),
            }
        )

    return normalized


def forecast(
    start: date,
    events: list[dict],
    extra_payments: list[tuple[date, Decimal]],
    initial_balance: Decimal,
    floor: Decimal,
    horizon: int = 90,
) -> tuple[bool, Decimal, date | None]:
    by_day: dict[date, list[Decimal]] = defaultdict(list)

    for payment_date, amount in extra_payments:
        by_day[payment_date].append(-amount)

    for event in events:
        current = event["date"]

        while current <= start + timedelta(days=horizon):
            by_day[current].append(
                event["amount"] if event["income"] else -event["amount"]
            )

            if not event["recurring"]:
                break

            current += timedelta(days=event["interval"])

    balance = initial_balance
    minimum_seen = balance
    first_safe_date = None

    for offset in range(horizon + 1):
        current = start + timedelta(days=offset)

        for delta in by_day.get(current, []):
            balance += delta
            minimum_seen = min(minimum_seen, balance)

        if balance < floor:
            return False, minimum_seen, None

        if first_safe_date is None:
            first_safe_date = current

    return True, minimum_seen, first_safe_date


def safe_amount_today(
    request_date: date,
    requested: Decimal,
    initial_balance: Decimal,
    floor: Decimal,
    events: list[dict],
) -> Decimal:
    """
    Calculates safe immediate capacity before optional spending changes.

    Binary search works because increasing today's payment can only reduce
    every subsequent forecast balance.
    """

    low = ZERO
    high = requested

    for _ in range(80):
        mid = (low + high) / Decimal("2")

        safe, _, _ = forecast(
            request_date,
            events,
            [(request_date, mid)],
            initial_balance,
            floor,
        )

        if safe:
            low = mid
        else:
            high = mid

    return low.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def full_payment_date(
    request_date: date,
    requested: Decimal,
    initial_balance: Decimal,
    floor: Decimal,
    events: list[dict],
    horizon: int = 90,
) -> date | None:
    for offset in range(horizon + 1):
        candidate = request_date + timedelta(days=offset)

        safe, _, _ = forecast(
            request_date,
            events,
            [(candidate, requested)],
            initial_balance,
            floor,
            horizon,
        )

        if safe:
            return candidate

    return None


def explanation(
    status: str,
    method: str,
    safe_today: Decimal,
    requested: Decimal,
    full_date: date | None,
    floor: Decimal,
) -> str:
    if status == "affordable_now":
        return (
            f"Full payment of {money(requested)} is safe today while "
            f"maintaining the minimum balance of {money(floor)}."
        )

    if status == "affordable_with_plan":
        return (
            f"{money(safe_today)} is safe today. The request can be completed "
            f"using the selected {method} plan while maintaining the minimum "
            f"balance of {money(floor)}."
        )

    if status == "affordable_later" and full_date:
        return (
            f"The full amount is not safe today. The earliest forecast date "
            f"for a safe full payment is {full_date.isoformat()}."
        )

    return (
        f"The requested amount of {money(requested)} cannot be completed safely "
        f"within the forecast while maintaining the minimum balance of "
        f"{money(floor)}."
    )


def process_request(
    request: dict,
    profile: dict,
    events: list[dict],
    rates: dict[tuple[str, str, date], Decimal],
    messages: list[dict],
) -> dict:
    request_id = first(request, "request_id", "id")
    request_date = parse_date(first(request, "request_date", "date"))
    completion_date = parse_date(
        first(request, "desired_completion_date", "completion_date", "deadline")
    )

    requested = decimal(first(request, "requested_amount", "amount"))
    home_currency = normalize_currency(
        first(profile, "home_currency", "currency")
    )

    initial_balance = profile_balance(profile)
    floor = profile_floor(profile)
    methods = accepted_methods(profile)

    user_events = build_event_index(
        events,
        home_currency,
        request_date,
        rates,
    )

    safe_today = safe_amount_today(
        request_date,
        requested,
        initial_balance,
        floor,
        user_events,
    )

    full_date = full_payment_date(
        request_date,
        requested,
        initial_balance,
        floor,
        user_events,
    )

    accepts_full = "full_payment" in methods
    accepts_partial = "partial_payment" in methods
    accepts_installments = "installments" in methods

    if safe_today >= requested and accepts_full:
        status = "affordable_now"
        method = "full_payment"
        plan = f"{request_date.isoformat()}:{money(requested)}"

    elif (
        safe_today > ZERO
        and safe_today < requested
        and parse_bool(first(request, "allows_partial_payment"))
        and accepts_partial
        and full_date
        and completion_date
        and full_date <= completion_date
    ):
        status = "affordable_with_plan"
        method = "partial_payment"
        remaining = requested - safe_today
        plan = (
            f"{request_date.isoformat()}:{money(safe_today)}|"
            f"{full_date.isoformat()}:{money(remaining)}"
        )

    elif full_date and full_date > request_date and accepts_full:
        status = "affordable_later"
        method = "wait"
        plan = "none"

    elif full_date and full_date <= request_date and accepts_full:
        status = "affordable_now"
        method = "full_payment"
        plan = f"{request_date.isoformat()}:{money(requested)}"

    else:
        status = "not_affordable"
        method = "not_recommended"
        plan = "none"

    return {
        "request_id": request_id,
        "amount_safe_to_pay": money(min(safe_today, requested)),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan,
        "earliest_date_for_full_payment": (
            full_date.isoformat() if full_date else ""
        ),
        "spending_changes_needed": "none",
        "decision_explanation": explanation(
            status,
            method,
            safe_today,
            requested,
            full_date,
            floor,
        ),
    }


def validate_output(rows: list[dict], requests: list[dict]) -> None:
    expected_ids = {
        first(row, "request_id", "id")
        for row in requests
    }

    actual_ids = {row["request_id"] for row in rows}

    if expected_ids != actual_ids:
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        raise ValueError(f"Request mismatch. Missing={missing}, extra={extra}")

    allowed_status = {
        "affordable_now",
        "affordable_with_plan",
        "affordable_later",
        "not_affordable",
    }

    allowed_methods = {
        "full_payment",
        "partial_payment",
        "installments",
        "wait",
        "not_recommended",
    }

    requests_by_id = {
        first(row, "request_id", "id"): row
        for row in requests
    }

    for row in rows:
        if row["affordability_status"] not in allowed_status:
            raise ValueError(f"Invalid status: {row}")

        if row["recommended_payment_method"] not in allowed_methods:
            raise ValueError(f"Invalid payment method: {row}")

        request = requests_by_id[row["request_id"]]
        requested = decimal(first(request, "requested_amount", "amount"))
        safe = decimal(row["amount_safe_to_pay"])

        if safe < ZERO or safe > requested:
            raise ValueError(f"Invalid safe amount: {row}")

        if row["affordability_status"] == "affordable_now":
            if row["earliest_date_for_full_payment"] != first(
                request,
                "request_date",
                "date",
            ):
                raise ValueError(f"Invalid earliest date: {row}")


def main() -> None:
    requests = read_csv("requests.csv")
    profiles = read_csv("financial_profiles.csv")
    financial_events = read_csv("financial_events.csv")
    messages = read_csv("messages.csv")
    exchange_rates = read_csv("exchange_rates.csv")

    rates = build_rates(exchange_rates)

    profiles_by_user = {
        first(row, "user_id"): row
        for row in profiles
        if first(row, "user_id")
    }

    events_by_user: dict[str, list[dict]] = defaultdict(list)

    for row in financial_events:
        user_id = first(row, "user_id")
        if user_id:
            events_by_user[user_id].append(row)

    messages_by_user: dict[str, list[dict]] = defaultdict(list)

    for row in messages:
        user_id = first(row, "user_id")
        if user_id:
            messages_by_user[user_id].append(row)

    output_rows = []

    for request in requests:
        request_id = first(request, "request_id", "id")
        user_id = first(request, "user_id")

        profile = profiles_by_user.get(user_id, {})
        user_events = events_by_user.get(user_id, [])
        user_messages = messages_by_user.get(user_id, [])

        # Build message facts now so the extraction boundary is explicit.
        # The deterministic planner does not trust free-form message content.
        extract_message_facts(user_messages)

        try:
            result = process_request(
                request,
                profile,
                user_events,
                rates,
                user_messages,
            )
        except Exception as exc:
            # Fail closed while preserving the required output schema.
            result = {
                "request_id": request_id,
                "amount_safe_to_pay": "0",
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": (
                    f"Unable to establish a safe forecast from the supplied "
                    f"records; no payment is recommended. Internal reason: "
                    f"{type(exc).__name__}."
                ),
            }

        output_rows.append(result)

    validate_output(output_rows, requests)

    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows)} predictions to {OUTPUT}")


if __name__ == "__main__":
    main()
