"""
Buy or Wait? — Phase 2: basic 90-day cash forecast.

The dataset has no recurrence column. Cadence is inferred from repeated
settled history (same event_type + category + direction).

Cash is applied on settlement_date when present, otherwise event_date.
"""

from __future__ import annotations

from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

import pandas as pd


FORECAST_DAYS = 90
FLOAT_TOLERANCE = 0.000001

# Statuses the problem says to ignore for cash forecasting.
IGNORE_STATUSES = frozenset({"failed", "cancelled", "unrealized"})
NON_CASH_DIRECTIONS = frozenset({"non_cash"})

# These types/categories are one-off in the dataset, not a bill cycle.
ONE_OFF_EVENT_TYPES = frozenset(
    {
        "refund",
        "investment_valuation",
        "investment_purchase",
        "investment_sale",
    }
)
ONE_OFF_CATEGORIES = frozenset({"windfall"})

MIN_RECURRENCE_OCCURRENCES = 3
INTERVAL_TOLERANCE_DAYS = 3
MONTHLY_DIFF_MIN = 27
MONTHLY_DIFF_MAX = 33


@dataclass
class RecurringStream:
    event_type: str
    category: str
    direction: str
    amount: float
    interval: str  # "monthly" or "days"
    interval_days: int | None
    day_of_month: int | None
    last_date: date
    occurrences: int
    source_event_id: str = ""
    flexibility: str = "fixed"
    minimum_allowed_amount: float | None = None


@dataclass
class ForecastResult:
    starting_balance: float
    total_confirmed_income: float
    total_protected_expenses: float
    lowest_forecast_balance: float
    lowest_balance_date: date
    minimum_balance_required: float
    is_safe: bool
    daily_closing_balances: dict[date, float] = field(default_factory=dict)
    skipped_events: list[str] = field(default_factory=list)
    recurring_streams: list[RecurringStream] = field(default_factory=list)
    amount_safe_to_pay: float = 0.0


def parse_date(value: Any) -> date | None:
    """Parse a CSV date. Returns None for blank / NaN values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def to_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {field_name}: {value!r}") from exc
    if pd.isna(number):
        raise ValueError(f"Missing numeric value for {field_name}")
    return number


def add_months(start: date, months: int) -> date:
    """Move a date forward by whole months, clamping the day if needed."""
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def cash_date_for_row(row: Any) -> date | None:
    """Prefer settlement_date; fall back to event_date."""
    settlement = parse_date(getattr(row, "settlement_date", None))
    if settlement is not None:
        return settlement
    return parse_date(getattr(row, "event_date", None))


def split_categories(raw: Any) -> set[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return set()
    text = str(raw).strip()
    if not text:
        return set()
    return {part.strip() for part in text.split("|") if part.strip()}


def build_rate_lookup(exchange_rates: pd.DataFrame | None) -> dict[tuple[str, str, str], float]:
    """Map (rate_date, from_currency, to_currency) -> rate."""
    lookup: dict[tuple[str, str, str], float] = {}
    if exchange_rates is None or exchange_rates.empty:
        return lookup
    for row in exchange_rates.itertuples(index=False):
        rate_date = parse_date(row.rate_date)
        if rate_date is None:
            continue
        try:
            rate = float(row.rate)
        except (TypeError, ValueError):
            continue
        lookup[(rate_date.isoformat(), str(row.from_currency), str(row.to_currency))] = rate
    return lookup


def convert_to_home_currency(
    amount: float,
    currency: str,
    home_currency: str,
    on_date: date,
    rate_lookup: dict[tuple[str, str, str], float],
) -> float | None:
    """Convert using the dated from->to rate. Same currency needs no conversion."""
    if currency == home_currency:
        return amount
    key = (on_date.isoformat(), currency, home_currency)
    rate = rate_lookup.get(key)
    if rate is None:
        return None
    return amount * rate


def event_home_amount(
    row: Any,
    home_currency: str,
    rate_lookup: dict[tuple[str, str, str], float],
    skipped: list[str],
    blank_amounts: dict[str, float] | None = None,
) -> float | None:
    """Return the event amount in home currency, or None if it cannot be used."""
    raw_amount = getattr(row, "amount", None)
    if raw_amount is None or (isinstance(raw_amount, float) and pd.isna(raw_amount)):
        event_id = str(getattr(row, "event_id", ""))
        if blank_amounts and event_id in blank_amounts:
            amount = float(blank_amounts[event_id])
        else:
            skipped.append(
                f"{event_id}: blank amount skipped (not treated as zero; image OCR is later)"
            )
            return None
    else:
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            skipped.append(f"{row.event_id}: invalid amount {raw_amount!r}")
            return None

    on_date = cash_date_for_row(row)
    currency = str(getattr(row, "currency", home_currency))
    converted = convert_to_home_currency(
        amount, currency, home_currency, on_date or date.min, rate_lookup
    )
    if converted is None:
        skipped.append(
            f"{row.event_id}: no exchange rate for {currency}->{home_currency} on {on_date}"
        )
        return None
    return converted


def should_ignore_row(row: Any) -> bool:
    status = str(getattr(row, "status", "")).strip()
    direction = str(getattr(row, "direction", "")).strip()
    event_type = str(getattr(row, "event_type", "")).strip()
    if status in IGNORE_STATUSES:
        return True
    if direction in NON_CASH_DIRECTIONS:
        return True
    if event_type == "investment_valuation":
        return True
    # Pending credits (refunds, etc.) must not be counted until they settle.
    if status == "pending" and direction == "credit":
        return True
    return False


def _regular_amount_cluster(amounts: list[float]) -> list[float]:
    """Keep amounts close to the median so one-off bonuses/arrears are dropped."""
    if not amounts:
        return []
    mid = median(amounts)
    if mid == 0:
        return amounts
    cluster = [value for value in amounts if abs(value - mid) <= 0.20 * abs(mid)]
    return cluster if len(cluster) >= MIN_RECURRENCE_OCCURRENCES else amounts


def _detect_salary_streams(
    events: pd.DataFrame,
    request_date: date,
    home_currency: str,
    rate_lookup: dict[tuple[str, str, str], float],
    skipped: list[str],
    blank_amounts: dict[str, float] | None = None,
    user_id: str | None = None,
    user_salary_info: dict[str, dict[str, Any]] | None = None,
) -> list[RecurringStream]:
    u_info = (user_salary_info or {}).get(str(user_id), {}) if user_id else {}
    if u_info.get("has_ended") or u_info.get("is_unconfirmed"):
        return []

    override_amt = u_info.get("override_amount")
    override_day = u_info.get("override_day")

    # Check future scheduled salary events
    future_sal = pd.DataFrame()
    if not events.empty and "category" in events.columns and "direction" in events.columns:
        future_sal = events[
            (events["category"] == "salary")
            & (events["direction"] == "credit")
            & (events["settlement_date"] >= request_date.isoformat())
        ]
    if not future_sal.empty and override_amt is None:
        fs = future_sal.iloc[0]
        amt = event_home_amount(fs, home_currency, rate_lookup, skipped, blank_amounts=blank_amounts)
        sdt = parse_date(getattr(fs, "settlement_date", None))
        if amt and amt > 0:
            override_amt = amt
            if sdt and override_day is None:
                override_day = sdt.day

    # Check settled historical salary events
    settled_sal = pd.DataFrame()
    if not events.empty and "category" in events.columns and "direction" in events.columns:
        settled_sal = events[
            (events["category"] == "salary")
            & (events["direction"] == "credit")
            & (events["status"] == "settled")
            & (events["settlement_date"] < request_date.isoformat())
        ]

    # If the last historical payroll is marked "Final employer payroll", contract ended
    if not settled_sal.empty and override_amt is None:
        last_desc = str(settled_sal.iloc[-1].get("description", "")).lower()
        if "final" in last_desc:
            return []

    if settled_sal.empty and override_amt is None:
        return []

    if override_amt is not None:
        day = override_day if override_day is not None else 15
        return [
            RecurringStream(
                event_type="income",
                category="salary",
                direction="credit",
                amount=override_amt,
                interval="monthly",
                interval_days=None,
                day_of_month=day,
                last_date=request_date - timedelta(days=20),
                occurrences=5,
                source_event_id="salary_stream",
                flexibility="fixed",
            )
        ]

    # Cluster settled history by day of month (filtering out unconfirmed commission events)
    day_groups: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for row in settled_sal.itertuples(index=False):
        desc = str(getattr(row, "description", "")).lower()
        if "commission" in desc:
            continue
        c_on = cash_date_for_row(row)
        amt = event_home_amount(row, home_currency, rate_lookup, skipped, blank_amounts=blank_amounts)
        if c_on and amt and amt > 0:
            matched_day = None
            for existing_day in day_groups:
                if abs(existing_day - c_on.day) <= 2:
                    matched_day = existing_day
                    break
            target_day = matched_day if matched_day is not None else c_on.day
            day_groups[target_day].append((c_on, amt))

    streams: list[RecurringStream] = []
    for day, items in day_groups.items():
        if len(items) >= 2 or not future_sal.empty:
            amounts = [x[1] for x in items]
            stream_amt = median(amounts[-3:]) if len(amounts) >= 3 else amounts[-1]
            streams.append(
                RecurringStream(
                    event_type="income",
                    category="salary",
                    direction="credit",
                    amount=stream_amt,
                    interval="monthly",
                    interval_days=None,
                    day_of_month=day,
                    last_date=items[-1][0],
                    occurrences=len(items),
                    source_event_id=f"salary_stream_{day}",
                    flexibility="fixed",
                )
            )
    return streams


def detect_recurring_streams(
    events: pd.DataFrame,
    request_date: date,
    home_currency: str,
    rate_lookup: dict[tuple[str, str, str], float],
    skipped: list[str],
    blank_amounts: dict[str, float] | None = None,
    user_id: str | None = None,
    user_salary_info: dict[str, dict[str, Any]] | None = None,
) -> list[RecurringStream]:
    """Infer recurring streams from settled history before the request date."""
    grouped: dict[tuple[str, str, str], list[tuple]] = defaultdict(list)

    for row in events.itertuples(index=False):
        if str(row.status) != "settled":
            continue
        if str(row.event_type) in ONE_OFF_EVENT_TYPES:
            continue
        if str(row.category) in ONE_OFF_CATEGORIES:
            continue
        if str(row.direction) != "debit":
            continue
        cash_on = cash_date_for_row(row)
        if cash_on is None or cash_on >= request_date:
            continue
        amount = event_home_amount(row, home_currency, rate_lookup, skipped, blank_amounts=blank_amounts)
        if amount is None:
            continue
        min_allowed = None
        raw_min = getattr(row, "minimum_allowed_amount", None)
        if raw_min is not None and not (isinstance(raw_min, float) and pd.isna(raw_min)):
            try:
                min_allowed = float(raw_min)
            except (TypeError, ValueError):
                min_allowed = None
        key = (str(row.event_type), str(row.category), str(row.direction))
        grouped[key].append(
            (
                cash_on,
                amount,
                str(row.event_id),
                str(getattr(row, "flexibility", "fixed") or "fixed"),
                min_allowed,
            )
        )

    streams: list[RecurringStream] = []
    for (event_type, category, direction), items in grouped.items():
        items = sorted(items, key=lambda item: item[0])
        cadence_items = items
        if len(cadence_items) < MIN_RECURRENCE_OCCURRENCES:
            continue

        dates = [item[0] for item in cadence_items]
        diffs = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
        if not diffs:
            continue
        typical_gap = median(diffs)

        is_monthly = MONTHLY_DIFF_MIN <= typical_gap <= MONTHLY_DIFF_MAX
        close_count = 0
        for gap in diffs:
            if is_monthly and MONTHLY_DIFF_MIN <= gap <= MONTHLY_DIFF_MAX:
                close_count += 1
            elif abs(gap - typical_gap) <= INTERVAL_TOLERANCE_DAYS:
                close_count += 1
        if close_count / len(diffs) < 0.75:
            continue

        cadence_amounts = [item[1] for item in cadence_items]
        cluster = _regular_amount_cluster(cadence_amounts)
        stream_amount = median(cluster) if cluster else median(cadence_amounts)

        last_item = cadence_items[-1]
        source_event_id = str(last_item[2])
        flexibility = str(last_item[3] or "fixed")
        min_allowed = last_item[4]
        for item in reversed(cadence_items):
            if item[4] is not None:
                min_allowed = item[4]
                break

        if is_monthly:
            day_counts = Counter(item.day for item in dates)
            day_of_month = day_counts.most_common(1)[0][0]
            streams.append(
                RecurringStream(
                    event_type=event_type,
                    category=category,
                    direction=direction,
                    amount=stream_amount,
                    interval="monthly",
                    interval_days=None,
                    day_of_month=day_of_month,
                    last_date=dates[-1],
                    occurrences=len(cadence_items),
                    source_event_id=source_event_id,
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                )
            )
        else:
            interval_days = int(round(typical_gap))
            if interval_days < 5:
                continue
            streams.append(
                RecurringStream(
                    event_type=event_type,
                    category=category,
                    direction=direction,
                    amount=stream_amount,
                    interval="days",
                    interval_days=interval_days,
                    day_of_month=None,
                    last_date=dates[-1],
                    occurrences=len(cadence_items),
                    source_event_id=source_event_id,
                    flexibility=flexibility,
                    minimum_allowed_amount=min_allowed,
                )
            )

    # Detect salary streams
    sal_streams = _detect_salary_streams(
        events, request_date, home_currency, rate_lookup, skipped, blank_amounts, user_id, user_salary_info
    )
    streams.extend(sal_streams)

    return streams


def project_stream(stream: RecurringStream, start: date, end: date) -> list[date]:
    """Dates when a detected stream is expected to hit during the forecast window."""
    hits: list[date] = []
    if stream.interval == "monthly" and stream.day_of_month:
        cursor = add_months(stream.last_date, 1)
        cursor = date(
            cursor.year,
            cursor.month,
            min(stream.day_of_month, monthrange(cursor.year, cursor.month)[1]),
        )
        while cursor < start:
            cursor = add_months(cursor, 1)
            cursor = date(
                cursor.year,
                cursor.month,
                min(stream.day_of_month, monthrange(cursor.year, cursor.month)[1]),
            )
        while cursor <= end:
            hits.append(cursor)
            cursor = add_months(cursor, 1)
            cursor = date(
                cursor.year,
                cursor.month,
                min(stream.day_of_month, monthrange(cursor.year, cursor.month)[1]),
            )
        return hits

    if stream.interval == "days" and stream.interval_days:
        cursor = stream.last_date + timedelta(days=stream.interval_days)
        while cursor < start:
            cursor += timedelta(days=stream.interval_days)
        while cursor <= end:
            hits.append(cursor)
            cursor += timedelta(days=stream.interval_days)
    return hits


def explicit_cashflows(
    events: pd.DataFrame,
    request_date: date,
    end_date: date,
    home_currency: str,
    rate_lookup: dict[tuple[str, str, str], float],
    skipped: list[str],
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> dict[date, list[tuple[float, str, str]]]:
    """
    Outstanding / future rows that are not already inside opening balance.

    Each tuple is (signed_amount, category, event_id).
    Debits are negative. Credits are positive.
    """
    flows: dict[date, list[tuple[float, str, str]]] = defaultdict(list)
    seen_event_ids: set[str] = set()

    for row in events.itertuples(index=False):
        event_id = str(getattr(row, "event_id", "")).strip()
        if event_id:
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

        if cancelled_events and event_id in cancelled_events:
            continue

        if should_ignore_row(row):
            continue

        amount = event_home_amount(
            row, home_currency, rate_lookup, skipped, blank_amounts=blank_amounts
        )
        if amount is None:
            continue

        status = str(row.status)
        direction = str(row.direction)
        cash_on = cash_date_for_row(row)
        event_on = parse_date(row.event_date)

        # Apply amendments from evidence if present
        if amended_events and event_id in amended_events:
            amend = amended_events[event_id]
            if "amount" in amend and amend["amount"] is not None:
                amount = float(amend["amount"])
            if "date" in amend and amend["date"] is not None:
                cash_on = amend["date"]

        if cash_on is None:
            skipped.append(f"{event_id}: missing cash date")
            continue

        # Opening balance already includes settled history on/before request_date.
        if status == "settled" and cash_on <= request_date:
            continue
        if cash_on > end_date and not (status == "pending" and direction == "debit"):
            continue

        apply_on = cash_on
        # Reserve pending debits as soon as they are known.
        if status == "pending" and direction == "debit":
            known_on = event_on or cash_on
            apply_on = max(request_date, known_on)

        if apply_on < request_date or apply_on > end_date:
            continue

        signed = amount if direction == "credit" else -amount
        flows[apply_on].append((signed, str(row.category), event_id))

    # Add any extra confirmed incomes from evidence
    if confirmed_incomes:
        for inc in confirmed_incomes:
            inc_date = inc.get("date")
            inc_amt = inc.get("amount")
            inc_cat = inc.get("category", "salary")
            inc_id = inc.get("event_id", "confirmed_income")
            if inc_date and inc_amt is not None and inc_amt > 0:
                if request_date <= inc_date <= end_date:
                    flows[inc_date].append((float(inc_amt), str(inc_cat), str(inc_id)))

    return flows


def merge_projected_flows(
    streams: list[RecurringStream],
    explicit: dict[date, list[tuple[float, str, str]]],
    start: date,
    end: date,
) -> dict[date, list[tuple[float, str, str]]]:
    """Add projected recurrence, skipping dates that already have an explicit match."""
    merged: dict[date, list[tuple[float, str, str]]] = defaultdict(list)
    for apply_on, items in explicit.items():
        merged[apply_on].extend(items)

    for stream in streams:
        for hit in project_stream(stream, start, end):
            already_covered = False
            for delta in range(-2, 3):
                nearby = hit + timedelta(days=delta)
                for _signed, category, event_id in merged.get(nearby, []):
                    explicit_is_credit = _signed > 0
                    stream_is_credit = stream.direction == "credit"
                    if category == stream.category and explicit_is_credit == stream_is_credit:
                        already_covered = True
                        break
                if already_covered:
                    break
            if already_covered:
                continue
            signed = stream.amount if stream.direction == "credit" else -stream.amount
            merged[hit].append((signed, stream.category, stream.source_event_id or f"projected:{stream.category}"))
    return merged


def apply_spending_changes(
    streams: list[RecurringStream],
    spending_changes: list[Any] | None,
) -> list[RecurringStream]:
    """Stop or reduce matching recurring debit streams. Unknown change IDs are ignored."""
    if not spending_changes:
        return list(streams)
    by_id = {change.event_id: change for change in spending_changes}
    adjusted: list[RecurringStream] = []
    for stream in streams:
        change = by_id.get(stream.source_event_id)
        if change is None:
            adjusted.append(stream)
            continue
        if change.action == "stop":
            continue
        if change.action == "reduce" and change.new_amount is not None:
            adjusted.append(
                RecurringStream(
                    event_type=stream.event_type,
                    category=stream.category,
                    direction=stream.direction,
                    amount=float(change.new_amount),
                    interval=stream.interval,
                    interval_days=stream.interval_days,
                    day_of_month=stream.day_of_month,
                    last_date=stream.last_date,
                    occurrences=stream.occurrences,
                    source_event_id=stream.source_event_id,
                    flexibility=stream.flexibility,
                    minimum_allowed_amount=stream.minimum_allowed_amount,
                )
            )
        else:
            adjusted.append(stream)
    return adjusted


def simulate_daily_balances(
    starting_balance: float,
    start: date,
    end: date,
    flows: dict[date, list[tuple[float, str, str]]],
    payment_on_request_date: float,
    protected_categories: set[str],
    extra_payments: dict[date, float] | None = None,
) -> tuple[dict[date, float], float, float, float, date]:
    """
    Walk each date. Planned request payments are extra debits.
    Debits are applied before credits on the same day (safer intra-day check).
    """
    extra_payments = dict(extra_payments or {})
    if payment_on_request_date > 0:
        extra_payments[start] = extra_payments.get(start, 0.0) + payment_on_request_date

    balance = starting_balance
    closing: dict[date, float] = {}
    total_income = 0.0
    total_protected = 0.0
    lowest = starting_balance
    lowest_date = start

    cursor = start
    while cursor <= end:
        pay = extra_payments.get(cursor, 0.0)
        if pay:
            balance -= pay
        day_items = list(flows.get(cursor, []))
        day_items.sort(key=lambda item: item[0])  # negatives (debits) first
        for signed, category, _event_id in day_items:
            balance += signed
            if signed > 0:
                total_income += signed
            elif category in protected_categories:
                total_protected += -signed
        closing[cursor] = balance
        if balance < lowest:
            lowest = balance
            lowest_date = cursor
        cursor += timedelta(days=1)

    return closing, total_income, total_protected, lowest, lowest_date


def forecast_90_days(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    payment_on_request_date: float = 0.0,
    exchange_rates: pd.DataFrame | None = None,
    extra_payments: dict[date, float] | None = None,
    spending_changes: list[Any] | None = None,
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> ForecastResult:
    """Simulate balances from request_date through the next 90 days."""
    request_date = parse_date(request["request_date"])
    if request_date is None:
        raise ValueError("request_date is missing")
    end_date = request_date + timedelta(days=FORECAST_DAYS)

    starting_balance = to_number(
        profile["current_available_balance"], "current_available_balance"
    )
    minimum_balance = to_number(
        profile["minimum_balance_to_keep"], "minimum_balance_to_keep"
    )
    home_currency = str(profile["home_currency"])
    protected = split_categories(profile.get("expense_categories_to_protect"))
    skipped: list[str] = []
    rate_lookup = build_rate_lookup(exchange_rates)

    streams = detect_recurring_streams(
        events, request_date, home_currency, rate_lookup, skipped
    )
    streams = apply_spending_changes(streams, spending_changes)
    explicit = explicit_cashflows(
        events,
        request_date,
        end_date,
        home_currency,
        rate_lookup,
        skipped,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )
    flows = merge_projected_flows(streams, explicit, request_date, end_date)

    closing, total_income, total_protected, lowest, lowest_date = simulate_daily_balances(
        starting_balance=starting_balance,
        start=request_date,
        end=end_date,
        flows=flows,
        payment_on_request_date=payment_on_request_date,
        protected_categories=protected,
        extra_payments=extra_payments,
    )

    is_safe = lowest + FLOAT_TOLERANCE >= minimum_balance
    return ForecastResult(
        starting_balance=starting_balance,
        total_confirmed_income=total_income,
        total_protected_expenses=total_protected,
        lowest_forecast_balance=lowest,
        lowest_balance_date=lowest_date,
        minimum_balance_required=minimum_balance,
        is_safe=is_safe,
        daily_closing_balances=closing,
        skipped_events=skipped,
        recurring_streams=streams,
    )


def earliest_full_payment_date(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    exchange_rates: pd.DataFrame | None = None,
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> date | None:
    """First date a single full payment is 90-day-safe, with no spending changes."""
    requested = to_number(request["requested_amount"], "requested_amount")
    start = parse_date(request["request_date"])
    if start is None:
        raise ValueError("request_date is missing")
    end = start + timedelta(days=FORECAST_DAYS)
    cursor = start
    while cursor <= end:
        result = forecast_90_days(
            request,
            profile,
            events,
            extra_payments={cursor: requested},
            exchange_rates=exchange_rates,
            spending_changes=None,
            blank_amounts=blank_amounts,
            confirmed_incomes=confirmed_incomes,
            cancelled_events=cancelled_events,
            amended_events=amended_events,
        )
        if result.is_safe:
            return cursor
        cursor += timedelta(days=1)
    return None


def amount_safe_to_pay(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    exchange_rates: pd.DataFrame | None = None,
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, ForecastResult]:
    """
    Largest payment on request_date that still keeps every forecast day
    at or above minimum_balance_to_keep. Clipped to [0, requested_amount].
    """
    requested = to_number(request["requested_amount"], "requested_amount")
    requested = max(0.0, requested)

    zero_case = forecast_90_days(
        request,
        profile,
        events,
        payment_on_request_date=0.0,
        exchange_rates=exchange_rates,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )
    if requested == 0 or not zero_case.is_safe:
        zero_case.amount_safe_to_pay = 0.0
        return 0.0, zero_case

    full = forecast_90_days(
        request,
        profile,
        events,
        payment_on_request_date=requested,
        exchange_rates=exchange_rates,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )
    if full.is_safe:
        full.amount_safe_to_pay = requested
        return requested, full

    low_cents = 0
    high_cents = int(round(requested * 100))
    best_cents = 0
    best_result = zero_case
    while low_cents <= high_cents:
        mid_cents = (low_cents + high_cents) // 2
        trial = mid_cents / 100.0
        result = forecast_90_days(
            request,
            profile,
            events,
            payment_on_request_date=trial,
            exchange_rates=exchange_rates,
            blank_amounts=blank_amounts,
            confirmed_incomes=confirmed_incomes,
            cancelled_events=cancelled_events,
            amended_events=amended_events,
        )
        if result.is_safe:
            best_cents = mid_cents
            best_result = result
            low_cents = mid_cents + 1
        else:
            high_cents = mid_cents - 1

    safe_amount = min(best_cents / 100.0, requested)
    best_result.amount_safe_to_pay = safe_amount
    return safe_amount, best_result


def print_forecast_summary(result: ForecastResult) -> None:
    print(f"Starting balance          : {result.starting_balance}")
    print(f"Total confirmed income    : {result.total_confirmed_income}")
    print(f"Total protected expenses  : {result.total_protected_expenses}")
    print(f"Lowest forecast balance   : {result.lowest_forecast_balance}")
    print(f"Date of lowest balance    : {result.lowest_balance_date.isoformat()}")
    print(f"Minimum balance required  : {result.minimum_balance_required}")
    print(f"Whether the forecast is safe: {'yes' if result.is_safe else 'no'}")
    print(f"Detected recurring streams: {len(result.recurring_streams)}")
    for stream in result.recurring_streams:
        cadence = (
            f"monthly on day {stream.day_of_month}"
            if stream.interval == "monthly"
            else f"every {stream.interval_days} days"
        )
        print(
            f"  - {stream.direction} {stream.category} {stream.amount} ({cadence}, "
            f"n={stream.occurrences})"
        )
    if result.skipped_events:
        print(f"Skipped events ({len(result.skipped_events)}):")
        for note in result.skipped_events[:10]:
            print(f"  - {note}")


def _synthetic_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def run_phase2_tests() -> None:
    """A few deterministic checks for the safe-amount and minimum-balance rules."""
    request = pd.Series(
        {
            "request_id": "test_req",
            "user_id": "test_user",
            "request_date": "2026-01-01",
            "requested_amount": 500.0,
        }
    )
    profile = pd.Series(
        {
            "user_id": "test_user",
            "home_currency": "USD",
            "current_available_balance": 1000.0,
            "minimum_balance_to_keep": 100.0,
            "expense_categories_to_protect": "rent",
        }
    )
    events = _synthetic_frame(
        [
            {
                "event_id": "e_rent1",
                "user_id": "test_user",
                "event_type": "expense",
                "description": "Rent",
                "category": "rent",
                "direction": "debit",
                "amount": 200.0,
                "currency": "USD",
                "event_date": "2025-10-10",
                "settlement_date": "2025-10-10",
                "status": "settled",
                "linked_event_id": None,
                "flexibility": "fixed",
                "minimum_allowed_amount": None,
            },
            {
                "event_id": "e_rent2",
                "user_id": "test_user",
                "event_type": "expense",
                "description": "Rent",
                "category": "rent",
                "direction": "debit",
                "amount": 200.0,
                "currency": "USD",
                "event_date": "2025-11-10",
                "settlement_date": "2025-11-10",
                "status": "settled",
                "linked_event_id": None,
                "flexibility": "fixed",
                "minimum_allowed_amount": None,
            },
            {
                "event_id": "e_rent3",
                "user_id": "test_user",
                "event_type": "expense",
                "description": "Rent",
                "category": "rent",
                "direction": "debit",
                "amount": 200.0,
                "currency": "USD",
                "event_date": "2025-12-10",
                "settlement_date": "2025-12-10",
                "status": "settled",
                "linked_event_id": None,
                "flexibility": "fixed",
                "minimum_allowed_amount": None,
            },
            {
                "event_id": "e_pending_credit",
                "user_id": "test_user",
                "event_type": "refund",
                "description": "Pending merchant refund",
                "category": "shopping",
                "direction": "credit",
                "amount": 999.0,
                "currency": "USD",
                "event_date": "2026-01-02",
                "settlement_date": "2026-01-12",
                "status": "pending",
                "linked_event_id": None,
                "flexibility": "fixed",
                "minimum_allowed_amount": None,
            },
            {
                "event_id": "e_cancelled",
                "user_id": "test_user",
                "event_type": "expense",
                "description": "Cancelled card auth",
                "category": "shopping",
                "direction": "debit",
                "amount": 400.0,
                "currency": "USD",
                "event_date": "2026-01-03",
                "settlement_date": "2026-01-03",
                "status": "cancelled",
                "linked_event_id": None,
                "flexibility": "fixed",
                "minimum_allowed_amount": None,
            },
        ]
    )

    safe_amount, result = amount_safe_to_pay(request, profile, events)
    unpaid = forecast_90_days(request, profile, events, payment_on_request_date=0.0)

    assert 0.0 <= safe_amount <= 500.0, "safe amount must stay inside [0, requested]"
    assert unpaid.is_safe, "baseline forecast without a purchase should stay above the minimum"
    paid_ok = forecast_90_days(
        request, profile, events, payment_on_request_date=safe_amount
    )
    assert paid_ok.is_safe, "paying the computed safe amount must keep the minimum balance"
    if safe_amount < 500.0:
        too_much = forecast_90_days(
            request,
            profile,
            events,
            payment_on_request_date=min(500.0, safe_amount + 1.0),
        )
        assert not too_much.is_safe, "one extra unit above the safe amount should break the rule"

    # Pending credit of 999 must not lift the safe amount.
    assert result.total_confirmed_income < 999.0, "pending credits must be ignored"

    print("Phase 2 assertions passed.")
    print(f"  synthetic amount_safe_to_pay = {safe_amount}")
    print(f"  synthetic lowest unpaid balance = {unpaid.lowest_forecast_balance}")
    print(f"  synthetic lowest date = {unpaid.lowest_balance_date.isoformat()}")
