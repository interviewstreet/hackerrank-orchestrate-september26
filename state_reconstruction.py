"""
state_reconstruction.py

Turns the raw financial_events.csv rows for one user into:
  1. A list of concrete forward-looking events (pending/scheduled items that
     land inside the forecast window as explicit rows), and
  2. A list of detected RECURRING SERIES (rent, salary, subscriptions, etc.)
     inferred from historical settled events, so they can be projected
     forward into the 90-day forecast (the dataset only gives historical
     occurrences + at most one "next confirmed salary" row per user - it
     does NOT pre-populate future rent/utility/subscription rows).

Conflict-resolution and exclusion rules applied here (per problem_statement.md):
  - status in {cancelled, failed}            -> excluded entirely
  - status == pending AND direction == credit -> excluded (pending credits ignored)
  - status == pending AND direction == debit  -> kept (only pending credits are
    excluded per the spec; pending debits represent likely real spending)
  - status == settled  -> historical fact; used for recurrence detection, but
    NOT re-applied to the forward balance (current_available_balance in
    financial_profiles.csv already reflects settled history)
  - status == scheduled -> a confirmed future event (e.g. next salary);
    applied on settlement_date if that date falls inside the forecast window
  - linked_event_id chains (authorization -> settlement, charge -> refund):
    since cancelled/failed rows are dropped and only the settled/scheduled
    replacement survives, this naturally implements "prefer explicit
    cancellation/settlement/amendment" without extra bookkeeping.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Optional

from utils import DATE_FMT, days_between, parse_date, safe_float


EXCLUDED_STATUSES = {"cancelled", "failed"}


@dataclass
class ForwardEvent:
    """A single, concrete, dated cash-flow event to apply during simulation."""
    event_id: str
    date: str            # settlement_date - the date balance actually moves
    amount: float        # signed: positive for credit, negative for debit
    category: str
    flexibility: str     # fixed | stoppable | reducible | reducible_or_stoppable
    minimum_allowed_amount: Optional[float]
    source: str          # "one_off" | "recurring"
    series_key: Optional[str] = None  # set for recurring occurrences
    origin_event_id: Optional[str] = None
    currency: str = ""
 # display-only: the real financial_events.csv
    # row this occurrence was projected from (for recurring) or itself (for
    # one_off) - used to label spending_changes_needed, since series_key is
    # an internal synthetic string, not a real event_id.


@dataclass
class RecurringSeries:
    """A detected recurring pattern (e.g. monthly rent, monthly salary)."""
    series_key: str
    user_id: str
    category: str
    description: str
    direction: str          # debit | credit
    typical_amount: float
    interval_days: int      # median gap between historical occurrences
    last_date: str          # most recent historical (or scheduled) occurrence
    flexibility: str
    minimum_allowed_amount: Optional[float]
    day_of_month_anchor: int  # approx day-of-month to project onto
    currency: str = ""
    last_event_id: Optional[str] = None  # the real financial_events.csv row this series was last detected from
    # Set by apply_employer_message_override() - None means no message-driven change.
    override_amount: Optional[float] = None
    override_effective_date: Optional[str] = None  # new amount applies on/after this date; None = applies to all future occurrences
    override_next_date: Optional[str] = None       # reschedule-only: shift just the next occurrence to this date
    override_stop: bool = False                    # employment/contract ended - project no further occurrences


def signed_amount(direction: str, amount: float) -> float:
    return amount if direction == "credit" else -amount


# Regex-based classifier for employer payroll messages. Verified against all
# 126 employer-source messages in dataset/messages.csv (English + Indonesian):
# they reduce to 47 template skeletons, all covered by 4 outcomes below,
# distinguished purely by (a) whether a CUR AMT token is present, (b) whether
# an ISO date is present, (c) "ended"/"berakhir" language. No amount AND no
# "ended" language (e.g. "bonus still pending approval", "regular salary
# already confirmed" with no figure, reimbursement notices) correctly fall
# through to 'none' since there's nothing concrete to act on - never invent
# unsupported figures.
_CUR_AMT_RE = re.compile(r"\b([A-Z]{3})\s(\d[\d,]*\.?\d*)\b")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ENDED_RE = re.compile(r"ended|berakhir", re.IGNORECASE)


def classify_employer_message(text: str) -> dict:
    """
    Treat message_text purely as data to pattern-match against - never as
    instructions to follow. Returns one of:
      {"action": "none"}
      {"action": "stop"}
      {"action": "set_amount", "amount": float, "effective_date": str|None}
      {"action": "reschedule", "new_date": str}
    """
    amt_match = _CUR_AMT_RE.search(text)
    date_match = _DATE_RE.search(text)

    if amt_match:
        return {
            "action": "set_amount",
            "amount": safe_float(amt_match.group(2).replace(",", "")),
            "effective_date": date_match.group(0) if date_match else None,
        }
    if _ENDED_RE.search(text):
        return {"action": "stop"}
    if date_match:
        return {"action": "reschedule", "new_date": date_match.group(0)}
    return {"action": "none"}


def apply_employer_message_override(series: RecurringSeries, messages: list[dict]) -> RecurringSeries:
    """
    Apply the most recent employer message (by sent_at) about this user's
    income to a detected recurring credit series. Only ever called on
    direction=='credit' series - see build_user_forward_events.
    """
    if not messages:
        return series
    latest = max(messages, key=lambda m: m.get("sent_at", ""))
    result = classify_employer_message(latest.get("message_text", ""))

    if result["action"] == "stop":
        series.override_stop = True
    elif result["action"] == "set_amount" and result["amount"] is not None:
        series.override_amount = result["amount"]
        series.override_effective_date = result["effective_date"]
    elif result["action"] == "reschedule":
        series.override_next_date = result["new_date"]

    return series


def load_user_raw_events(all_events: list[dict], user_id: str) -> list[dict]:
    return [e for e in all_events if e.get("user_id") == user_id]


def _is_excluded(raw: dict) -> bool:
    status = (raw.get("status") or "").strip().lower()
    if status in EXCLUDED_STATUSES:
        return True
    if status == "pending" and (raw.get("direction") or "").strip().lower() == "credit":
        return True
    return False


def resolve_event_amount(raw: dict, images_by_related_event: dict[str, list[dict]],
                          image_amount_lookup) -> Optional[float]:
    """
    Resolve a possibly-blank amount. Never treat blank as zero.
    `image_amount_lookup(image_id)` is a callable you implement to read the
    amount out of dataset/media/images/<image_id>.png (vision LLM or OCR).
    """
    amount = safe_float(raw.get("amount"))
    if amount is not None:
        return amount

    event_id = raw.get("event_id")
    linked_images = images_by_related_event.get(event_id, [])
    if not linked_images:
        return None  # genuinely unresolved - handle conservatively downstream

    return image_amount_lookup(linked_images[0]["image_id"])


def build_forward_and_history(
    raw_events: list[dict],
    images_by_related_event: dict[str, list[dict]],
    image_amount_lookup,
) -> tuple[list[dict], list[dict]]:
    """
    Split cleaned (non-excluded, amount-resolved) events into:
      - history: status == settled  (used only for recurrence detection)
      - forward_candidates: status in {pending, scheduled} (concrete future rows)
    Each returned dict is the original raw row plus a resolved 'amount' float.
    """
    history: list[dict] = []
    forward_candidates: list[dict] = []

    for raw in raw_events:
        if _is_excluded(raw):
            continue

        amount = resolve_event_amount(raw, images_by_related_event, image_amount_lookup)
        if amount is None:
            # Could not resolve - conservative choice: skip rather than
            # guess. Document this decision in decision_explanation upstream
            # if it affects a specific request.
            continue

        row = dict(raw)
        row["amount"] = amount

        status = (raw.get("status") or "").strip().lower()
        if status == "settled":
            history.append(row)
        elif status in ("pending", "scheduled"):
            forward_candidates.append(row)

    return history, forward_candidates


def detect_recurring_series(history: list[dict], user_id: str) -> list[RecurringSeries]:
    """
    Group historical settled events by (category, direction) and treat a
    group as a recurring series if it has >= 2 occurrences with a roughly
    consistent interval (approximately monthly, weekly, etc.).

    IMPORTANT: we deliberately do NOT include `description` in the grouping
    key. Verified against the real dataset (e.g. user_01's weekly groceries):
    the same underlying recurring expense rotates through several synonym
    descriptions ("Neighbourhood grocer", "Bulk pantry shop", "Fresh food
    shop", ...) at a genuinely weekly cadence. Grouping by (category,
    description) fragments one true weekly series into ~5-7 fake series that
    each only recur every 35-49 days, which either gets filtered out
    (interval > 45) or wildly understates true spending frequency - this
    silently corrupted amount_safe_to_pay for most users. `direction` is
    kept in the key (rather than category alone) so an occasional refund
    credit in an otherwise all-debit category doesn't get merged into the
    expense series and flip its projected sign.

    This is a heuristic (documented in usage_report.md / README as an
    assumption): the dataset supplies rich historical detail but only
    explicit *future* rows for pending/scheduled items, so recurring
    obligations (rent, subscriptions, salary, groceries, etc.) must be
    projected forward from their historical pattern.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in history:
        key = (row.get("category", ""), row.get("direction", ""))
        groups[key].append(row)

    series_list: list[RecurringSeries] = []
    for (category, direction), rows in groups.items():
        if len(rows) < 2:
            continue  # not enough data to call it recurring

        rows_sorted = sorted(rows, key=lambda r: r["settlement_date"])
        dates = [r["settlement_date"] for r in rows_sorted]
        gaps = [days_between(dates[i], dates[i + 1]) for i in range(len(dates) - 1)]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            continue

        interval = int(round(median(gaps)))
        # Only treat as recurring if the interval looks like a real cadence
        # (roughly weekly to roughly monthly-ish); otherwise it's probably
        # irregular one-off spending in the same category (e.g. "groceries"
        # bought at random intervals still recurs frequently enough to count).
        if interval < 3 or interval > 45:
            continue

        last_row = rows_sorted[-1]
        recent_amounts = [safe_float(r["amount"], 0.0) for r in rows_sorted[-3:]]
        typical_amount = median(recent_amounts)

        # Most common description among recent occurrences, purely for the
        # human-readable series description - never used for grouping/keys.
        recent_descriptions = [r.get("description", "") for r in rows_sorted[-5:]]
        display_description = max(set(recent_descriptions), key=recent_descriptions.count)

        series_key = f"{user_id}::{category}::{direction}"
        series_list.append(RecurringSeries(
            series_key=series_key,
            user_id=user_id,
            category=category,
            description=display_description,
            direction=last_row.get("direction", "debit"),
            typical_amount=typical_amount,
            interval_days=interval,
            last_date=last_row["settlement_date"],
            flexibility=last_row.get("flexibility", "fixed"),
            minimum_allowed_amount=safe_float(last_row.get("minimum_allowed_amount")),
            currency=last_row.get("currency", ""),
            day_of_month_anchor=parse_date(last_row["settlement_date"]).day,
            last_event_id=last_row.get("event_id"),
        ))

    return series_list


def _add_months_clamped(year: int, month: int, months: int, day: int) -> "datetime":
    """First advance (year, month) by `months`, then clamp `day` into that
    month's actual length (handles e.g. anchor day 31 landing in a 30-day
    or February month)."""
    import calendar
    from datetime import datetime as _dt

    total = (month - 1) + months
    new_year = year + total // 12
    new_month = total % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return _dt(new_year, new_month, min(day, last_day))


def project_recurring_occurrences(
    series: RecurringSeries,
    window_start: str,
    window_end: str,
) -> list[ForwardEvent]:
    """
    Project a recurring series forward from its last known occurrence.

    Monthly-cadence series (interval_days roughly 25-35, e.g. rent, salary,
    subscriptions) are anchored to day_of_month_anchor and stepped by
    calendar months rather than a fixed day-count. Stepping by a fixed
    interval_days (e.g. the median-detected 31) instead of by calendar month
    drifts the projected date by 1-3 days per cycle - confirmed against
    dataset/sample_requests.csv, where this was the direct cause of nearly
    every earliest_date_for_full_payment mismatch (expected dates land
    exactly on the 15th-of-month style anchor; ours drifted off it).
    Non-monthly cadences (weekly groceries, biweekly dining, etc.) keep the
    original fixed day-count stepping, which is correct for them.

    Honors employer-message overrides set by apply_employer_message_override
    (see that function's docstring for the three override kinds).
    """
    if series.override_stop:
        return []

    is_monthly = 25 <= series.interval_days <= 35

    occurrences: list[ForwardEvent] = []
    end_dt = parse_date(window_end)
    start_dt = parse_date(window_start)
    step_count = 0
    anchor_date = series.last_date
    date_shift_applied = False

    while True:
        step_count += 1
        if is_monthly:
            base = parse_date(anchor_date)
            next_date = _add_months_clamped(
                base.year, base.month, step_count, series.day_of_month_anchor,
            )
        else:
            from datetime import timedelta
            next_date = parse_date(anchor_date) + timedelta(days=series.interval_days * step_count)

        # Reschedule only the first projected occurrence; re-anchor from there.
        if series.override_next_date and not date_shift_applied and step_count == 1:
            next_date = parse_date(series.override_next_date)
            anchor_date = series.override_next_date
            date_shift_applied = True
            if is_monthly:
                step_count = 0  # restart calendar-month stepping from the new anchor

        if next_date > end_dt:
            break
        if next_date < start_dt:
            continue

        date_str = next_date.strftime(DATE_FMT)
        amount = series.typical_amount
        if series.override_amount is not None:
            if series.override_effective_date is None or date_str >= series.override_effective_date:
                amount = series.override_amount

        occurrences.append(ForwardEvent(
            event_id=f"{series.series_key}#{step_count}",
            date=date_str,
            amount=signed_amount(series.direction, amount),
            category=series.category,
            flexibility=series.flexibility,
            minimum_allowed_amount=series.minimum_allowed_amount,
            currency=series.currency,
            source="recurring",
            series_key=series.series_key,
            origin_event_id=series.last_event_id,
        ))

    return occurrences


def build_user_forward_events(
    raw_events: list[dict],
    images_by_related_event: dict[str, list[dict]],
    image_amount_lookup,
    user_id: str,
    window_start: str,
    window_end: str,
    employer_messages: Optional[list[dict]] = None,
) -> list[ForwardEvent]:
    """
    Full pipeline for one user: clean events -> detect recurring series ->
    project them forward -> add concrete pending/scheduled rows that fall
    inside the window -> return one combined, date-sorted list.

    employer_messages: this user's source_type=='employer' rows from
    messages.csv (may be empty/None). Applied to credit (income) series only.
    """
    history, forward_candidates = build_forward_and_history(
        raw_events, images_by_related_event, image_amount_lookup
    )

    events: list[ForwardEvent] = []

    # concrete pending/scheduled rows (e.g. "next confirmed salary")
    for row in forward_candidates:
        settlement_date = row["settlement_date"]
        if window_start <= settlement_date <= window_end:
            events.append(ForwardEvent(
                event_id=row["event_id"],
                date=settlement_date,
                amount=signed_amount(row.get("direction", "debit"), row["amount"]),
                category=row.get("category", ""),
                flexibility=row.get("flexibility", "fixed"),
                minimum_allowed_amount=safe_float(row.get("minimum_allowed_amount")),
                currency=row.get("currency", ""),
                source="one_off",
                origin_event_id=row["event_id"],
            ))

    # The dataset gives at most ONE explicit future income row (the "next
    # confirmed salary", status=scheduled). Most users only have a single
    # historical settled salary too, so detect_recurring_series alone never
    # sees >=2 occurrences and salary is never treated as recurring - every
    # paycheck after the one scheduled row silently disappears from the
    # forecast, which is wrong: the spec requires forecasting with
    # "recurring income and expenses". Fix: fold scheduled CREDIT rows into
    # the pool used for recurrence detection (debits from forward_candidates
    # are left out - those are genuinely one-off pending items, not income).
    # Because last_date then becomes the scheduled row's own date, projection
    # starts strictly after it (step_count >= 1), so the scheduled row above
    # is never duplicated.
    scheduled_credit_rows = [
        row for row in forward_candidates
        if (row.get("direction") or "").strip().lower() == "credit"
        and (row.get("status") or "").strip().lower() == "scheduled"
    ]
    recurrence_source = history + scheduled_credit_rows

    # recurring series projected forward
    for series in detect_recurring_series(recurrence_source, user_id):
        if series.direction == "credit" and employer_messages:
            series = apply_employer_message_override(series, employer_messages)
        events.extend(project_recurring_occurrences(series, window_start, window_end))

    events.sort(key=lambda e: e.date)
    return events