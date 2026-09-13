"""
state_reconstruction.py

Turns raw financial_events.csv rows for one user into:
  1. Concrete forward-looking events (pending/scheduled items inside window)
  2. Projected recurring series (rent, salary, subscriptions, etc.)

Rules per problem_statement.md:
  - cancelled / failed              → excluded
  - pending credit                  → excluded (unconfirmed income)
  - unrealized / non_cash           → excluded (no real cash flow)
  - pending debit                   → included (likely real spending)
  - settled                         → history for recurrence detection only
  - scheduled                       → concrete future event

FX:
  Each event amount is converted to home_currency before recurrence detection
  so typical_amount always reflects the home-currency value.

Salary-stream rules:
  1. If ALL salary credits look like variable gig payouts → don't project.
  2. If the last salary description signals termination ("final", "ended") → don't project.
  3. Try to split into distinct streams by description cluster; only do so when
     there are ≥ 2 description groups each with ≥ 2 occurrences. Otherwise treat
     all salary events as one stream (handles user_01 who has only 2 salary records).
  4. Drop any salary stream whose last occurrence is > 1.5 × interval days before
     request_date (stream has lapsed — handles user_13's ended secondary income).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Optional

from utils import DATE_FMT, days_between, parse_date, safe_float


EXCLUDED_STATUSES = {"cancelled", "failed"}

SALARY_TERMINATION_KEYWORDS = [
    "final employer payroll",
    "final payroll",
    "last payroll",
    "last salary",
    "employment has ended",
    "employment ended",
    "contract has ended",
    "seasonal contract has ended",
    "no off-season income",
]

GIG_INCOME_KEYWORDS = [
    "platform payout",
    "app earnings",
    "marketplace payout",
    "driver platform payout",
    "gig payout",
    "freelance payout",
    "task payout",
    "task marketplace payout",
    "weekly app earnings",
    "delivery platform payout",
]


@dataclass
class ForwardEvent:
    event_id: str
    date: str
    amount: float          # signed: positive=credit, negative=debit
    category: str
    flexibility: str
    minimum_allowed_amount: Optional[float]
    source: str            # "one_off" | "recurring"
    series_key: Optional[str] = None


@dataclass
class RecurringSeries:
    series_key: str
    user_id: str
    category: str
    description: str
    direction: str
    typical_amount: float
    interval_days: int
    last_date: str
    flexibility: str
    minimum_allowed_amount: Optional[float]
    day_of_month_anchor: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def signed_amount(direction: str, amount: float) -> float:
    return amount if direction == "credit" else -amount


def _is_excluded(raw: dict) -> bool:
    status = (raw.get("status") or "").strip().lower()
    if status in EXCLUDED_STATUSES:
        return True
    direction = (raw.get("direction") or "").strip().lower()
    if status == "pending" and direction == "credit":
        return True
    if status == "unrealized":
        return True
    if (raw.get("event_type") or "").strip().lower() == "non_cash":
        return True
    return False


def _is_gig_income(row: dict) -> bool:
    desc = (row.get("description") or "").lower()
    return any(kw in desc for kw in GIG_INCOME_KEYWORDS)


def _is_salary_terminated(last_row: dict) -> bool:
    desc = (last_row.get("description") or "").lower()
    return any(kw in desc for kw in SALARY_TERMINATION_KEYWORDS)


def _series_overdue(last_date: str, interval_days: int, request_date: str) -> bool:
    """True when last known occurrence is > 1.5 × interval before request_date."""
    try:
        gap = days_between(last_date, request_date)
        threshold = max(int(interval_days * 1.5), interval_days + 14)
        return gap > threshold
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Amount resolution with FX
# ---------------------------------------------------------------------------

def resolve_event_amount(
    raw: dict,
    images_by_related_event: dict,
    image_amount_lookup,
    home_currency: str = "",
    fx=None,
    fallback_date: str = "",
) -> Optional[float]:
    """Resolve blank amount via image lookup, then FX-convert to home_currency."""
    amount = safe_float(raw.get("amount"))
    if amount is None:
        event_id = raw.get("event_id")
        imgs = images_by_related_event.get(event_id, [])
        if not imgs:
            return None
        amount = image_amount_lookup(imgs[0]["image_id"])
        if amount is None:
            return None

    if fx and home_currency:
        event_ccy = (raw.get("currency") or "").strip()
        if event_ccy and event_ccy != home_currency:
            settle_date = (raw.get("settlement_date") or "").strip() or fallback_date
            try:
                rate = fx.get_rate(settle_date, event_ccy, home_currency)
                amount = amount * rate
            except Exception:
                pass

    return amount


# ---------------------------------------------------------------------------
# History / forward split
# ---------------------------------------------------------------------------

def build_forward_and_history(
    raw_events: list[dict],
    images_by_related_event: dict,
    image_amount_lookup,
    home_currency: str = "",
    fx=None,
    fallback_date: str = "",
) -> tuple[list[dict], list[dict]]:
    history: list[dict] = []
    forward_candidates: list[dict] = []

    for raw in raw_events:
        if _is_excluded(raw):
            continue
        amount = resolve_event_amount(
            raw, images_by_related_event, image_amount_lookup,
            home_currency, fx, fallback_date,
        )
        if amount is None:
            continue
        row = dict(raw)
        row["amount"] = amount
        status = (raw.get("status") or "").strip().lower()
        if status == "settled":
            history.append(row)
        elif status in ("pending", "scheduled"):
            forward_candidates.append(row)

    return history, forward_candidates


# ---------------------------------------------------------------------------
# Recurring-series detection
# ---------------------------------------------------------------------------

def _build_series_from_rows(
    rows: list[dict],
    category: str,
    direction: str,
    series_key: str,
    user_id: str,
    request_date: str = "",
    min_interval: int = 3,
    max_interval: int = 45,
    check_termination: bool = False,
    check_overdue: bool = False,
) -> Optional[RecurringSeries]:
    """Build one RecurringSeries from a sorted list of rows, or None if invalid."""
    if len(rows) < 2:
        return None

    rows_sorted = sorted(rows, key=lambda r: r["settlement_date"])
    dates = [r["settlement_date"] for r in rows_sorted]
    gaps = [days_between(dates[i], dates[i + 1]) for i in range(len(dates) - 1)]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return None

    interval = int(round(median(gaps)))
    if interval < min_interval or interval > max_interval:
        return None

    last_row = rows_sorted[-1]

    if check_termination and _is_salary_terminated(last_row):
        return None

    if check_overdue and request_date and _series_overdue(
            last_row["settlement_date"], interval, request_date):
        return None

    recent_amounts = [v for r in rows_sorted[-3:]
                      if (v := safe_float(r["amount"], 0.0)) is not None]
    typical_amount = median(recent_amounts) if recent_amounts else 0.0

    recent_descs = [r.get("description", "") for r in rows_sorted[-5:]]
    display_desc = max(set(recent_descs), key=recent_descs.count)

    return RecurringSeries(
        series_key=series_key,
        user_id=user_id,
        category=category,
        description=display_desc,
        direction=direction,
        typical_amount=typical_amount,
        interval_days=interval,
        last_date=last_row["settlement_date"],
        flexibility=last_row.get("flexibility", "fixed"),
        minimum_allowed_amount=safe_float(last_row.get("minimum_allowed_amount")),
        day_of_month_anchor=parse_date(last_row["settlement_date"]).day,
    )


def _salary_description_key(row: dict) -> str:
    """First 3 words of the description as a soft stream cluster key."""
    desc = (row.get("description") or "").strip().lower()
    return " ".join(desc.split()[:3])


def detect_recurring_series(
    history: list[dict],
    user_id: str,
    request_date: str = "",
    salary_stop: bool = False,
    salary_override_amount: Optional[float] = None,
    salary_override_next_date: Optional[str] = None,
) -> list[RecurringSeries]:
    """
    Detect all recurring expense and income series.

    salary_stop: suppress all projected salary (gig income signalled as pending).
    salary_override_amount: replace typical_amount for salary series (from message).
    salary_override_next_date: shift last_date so next projection hits this date.
    """
    series_list: list[RecurringSeries] = []

    # ---- Non-salary categories (grouped by category+direction) ----
    groups: dict[tuple, list] = defaultdict(list)
    for row in history:
        cat = row.get("category", "")
        if cat == "salary":
            continue
        key = (cat, row.get("direction", ""))
        groups[key].append(row)

    for (category, direction), rows in groups.items():
        s = _build_series_from_rows(
            rows, category, direction,
            series_key=f"{user_id}::{category}::{direction}",
            user_id=user_id, request_date=request_date,
        )
        if s:
            series_list.append(s)

    # ---- Salary income ----
    if salary_stop:
        return series_list

    salary_rows = [r for r in history
                   if r.get("category") == "salary"
                   and r.get("direction", "").strip().lower() == "credit"]

    if not salary_rows:
        return series_list

    # If ALL salary records look like gig income → don't project
    if all(_is_gig_income(r) for r in salary_rows):
        return series_list

    # Attempt description-based stream splitting ONLY when there are clearly
    # ≥ 2 distinct groups each with ≥ 2 occurrences (multi-income household).
    # For single-stream users (e.g. user_01 with 1-2 records), fall back to
    # treating all salary as one stream so we don't lose the series entirely.
    desc_groups: dict[str, list] = defaultdict(list)
    for row in salary_rows:
        desc_groups[_salary_description_key(row)].append(row)

    qualifying_subgroups = {k: v for k, v in desc_groups.items() if len(v) >= 2}

    if len(qualifying_subgroups) >= 2:
        # Multiple distinct salary streams (e.g. primary + secondary household)
        for stream_key, rows in qualifying_subgroups.items():
            s = _build_series_from_rows(
                rows, "salary", "credit",
                series_key=f"{user_id}::salary::{stream_key}",
                user_id=user_id, request_date=request_date,
                min_interval=14, max_interval=45,
                check_termination=True,
                check_overdue=True,
            )
            if s:
                s = _apply_salary_overrides(s, salary_override_amount,
                                            salary_override_next_date)
                series_list.append(s)
    else:
        # Single salary stream (most users).
        # Use the dominant (largest) qualifying subgroup when available to avoid
        # corrupting interval/last_date with one-off bonuses or arrears payments.
        # Fall back to all salary_rows only when no subgroup qualifies (e.g. new job,
        # only 2 records total with different descriptions).
        if qualifying_subgroups:
            dominant_key = max(qualifying_subgroups, key=lambda k: len(qualifying_subgroups[k]))
            stream_rows = qualifying_subgroups[dominant_key]
        else:
            stream_rows = salary_rows

        s = _build_series_from_rows(
            stream_rows, "salary", "credit",
            series_key=f"{user_id}::salary::credit",
            user_id=user_id, request_date=request_date,
            min_interval=14, max_interval=45,
            check_termination=True,
            check_overdue=False,  # don't drop single-stream salary as overdue
        )
        if s:
            s = _apply_salary_overrides(s, salary_override_amount,
                                        salary_override_next_date)
            series_list.append(s)

    return series_list


def _apply_salary_overrides(
    s: RecurringSeries,
    override_amount: Optional[float],
    override_next_date: Optional[str],
) -> RecurringSeries:
    """Return an updated RecurringSeries with message-driven overrides applied."""
    if override_amount is not None:
        s = RecurringSeries(
            series_key=s.series_key, user_id=s.user_id,
            category=s.category, description=s.description,
            direction=s.direction, typical_amount=override_amount,
            interval_days=s.interval_days, last_date=s.last_date,
            flexibility=s.flexibility,
            minimum_allowed_amount=s.minimum_allowed_amount,
            day_of_month_anchor=s.day_of_month_anchor,
        )
    if override_next_date is not None:
        try:
            new_last = parse_date(override_next_date) - timedelta(days=s.interval_days)
            s = RecurringSeries(
                series_key=s.series_key, user_id=s.user_id,
                category=s.category, description=s.description,
                direction=s.direction, typical_amount=s.typical_amount,
                interval_days=s.interval_days,
                last_date=new_last.strftime(DATE_FMT),
                flexibility=s.flexibility,
                minimum_allowed_amount=s.minimum_allowed_amount,
                day_of_month_anchor=s.day_of_month_anchor,
            )
        except Exception:
            pass
    return s


# ---------------------------------------------------------------------------
# Forward projection
# ---------------------------------------------------------------------------

def project_recurring_occurrences(
    series: RecurringSeries,
    window_start: str,
    window_end: str,
) -> list[ForwardEvent]:
    occurrences: list[ForwardEvent] = []
    end_dt = parse_date(window_end)
    start_dt = parse_date(window_start)
    step = 0

    while True:
        step += 1
        next_dt = parse_date(series.last_date) + timedelta(days=series.interval_days * step)
        if next_dt > end_dt:
            break
        if next_dt < start_dt:
            continue
        occurrences.append(ForwardEvent(
            event_id=f"{series.series_key}#{step}",
            date=next_dt.strftime(DATE_FMT),
            amount=signed_amount(series.direction, series.typical_amount),
            category=series.category,
            flexibility=series.flexibility,
            minimum_allowed_amount=series.minimum_allowed_amount,
            source="recurring",
            series_key=series.series_key,
        ))
    return occurrences


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_user_forward_events(
    raw_events: list[dict],
    images_by_related_event: dict,
    image_amount_lookup,
    user_id: str,
    window_start: str,
    window_end: str,
    home_currency: str = "",
    fx=None,
    salary_stop: bool = False,
    salary_override_amount: Optional[float] = None,
    salary_override_next_date: Optional[str] = None,
) -> list[ForwardEvent]:
    """
    Full pipeline for one user:
      1. Clean + FX-convert events
      2. Split history vs forward candidates
      3. Detect recurring series
      4. Project recurring series into window
      5. Add concrete pending/scheduled rows
      Return date-sorted combined list.
    """
    history, forward_candidates = build_forward_and_history(
        raw_events, images_by_related_event, image_amount_lookup,
        home_currency=home_currency, fx=fx, fallback_date=window_start,
    )

    events: list[ForwardEvent] = []

    # Concrete one-off forward events (pending debits + scheduled credits)
    for row in forward_candidates:
        sd = row["settlement_date"]
        if window_start <= sd <= window_end:
            events.append(ForwardEvent(
                event_id=row["event_id"],
                date=sd,
                amount=signed_amount(row.get("direction", "debit"), row["amount"]),
                category=row.get("category", ""),
                flexibility=row.get("flexibility", "fixed"),
                minimum_allowed_amount=safe_float(row.get("minimum_allowed_amount")),
                source="one_off",
            ))

    # Fold scheduled credits into recurrence pool so projection starts after them
    scheduled_credits = [
        r for r in forward_candidates
        if (r.get("direction") or "").strip().lower() == "credit"
        and (r.get("status") or "").strip().lower() == "scheduled"
    ]
    recurrence_source = history + scheduled_credits

    series_list = detect_recurring_series(
        recurrence_source, user_id,
        request_date=window_start,
        salary_stop=salary_stop,
        salary_override_amount=salary_override_amount,
        salary_override_next_date=salary_override_next_date,
    )

    for series in series_list:
        events.extend(project_recurring_occurrences(series, window_start, window_end))

    events.sort(key=lambda e: e.date)
    return events
