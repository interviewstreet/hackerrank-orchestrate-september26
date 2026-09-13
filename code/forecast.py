"""
forecast.py

The 90-day safety-check engine. Given a starting balance and a list of
ForwardEvent objects (from state_reconstruction.py), this module answers:

  - amount_safe_to_pay: the most that can be paid TODAY without any future
    day in the 90-day window dropping below minimum_balance_to_keep
  - earliest_date_for_full_payment: the first date on/after request_date
    where paying the FULL requested amount keeps every subsequent day safe
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from state_reconstruction import ForwardEvent
from utils import DATE_FMT, date_range, parse_date, format_date

FORECAST_DAYS = 90


def build_daily_deltas(events: list[ForwardEvent], window_dates: list[str]) -> dict[str, float]:
    """Sum signed event amounts landing on each date in the window."""
    deltas = {d: 0.0 for d in window_dates}
    for ev in events:
        if ev.date in deltas:
            deltas[ev.date] += ev.amount
    return deltas


def running_balance(
    start_balance: float,
    daily_deltas: dict[str, float],
    window_dates: list[str],
) -> list[float]:
    """
    End-of-day balance for each date in window_dates, in order, assuming
    NO extra payment is subtracted (pure organic forecast).
    """
    balances = []
    balance = start_balance
    for d in window_dates:
        balance += daily_deltas.get(d, 0.0)
        balances.append(balance)
    return balances


def min_balance_from(balances: list[float], from_index: int) -> float:
    """Minimum balance from a given index (inclusive) to the end of the window."""
    return min(balances[from_index:]) if from_index < len(balances) else float("inf")


def amount_safe_to_pay(
    start_balance: float,
    events: list[ForwardEvent],
    request_date: str,
    minimum_balance_to_keep: float,
    requested_amount: float,
    forecast_days: int = FORECAST_DAYS,
) -> float:
    """
    Largest amount payable on request_date such that every day from
    request_date through request_date+forecast_days stays >= minimum_balance_to_keep.

    A payment made on request_date reduces the balance on request_date and
    every subsequent day (it's a one-time withdrawal, not recurring), so the
    binding constraint is simply:

        payment <= min(organic_balances_over_window) - minimum_balance_to_keep

    capped to [0, requested_amount].
    """
    window_dates = date_range(request_date, forecast_days)
    deltas = build_daily_deltas(events, window_dates)
    organic_balances = running_balance(start_balance, deltas, window_dates)

    worst_case_balance = min(organic_balances)  # includes day 0 (request_date)
    headroom = worst_case_balance - minimum_balance_to_keep

    safe_amount = max(0.0, headroom)
    return min(safe_amount, requested_amount)


def earliest_date_for_full_payment(
    start_balance: float,
    events: list[ForwardEvent],
    request_date: str,
    minimum_balance_to_keep: float,
    requested_amount: float,
    forecast_days: int = FORECAST_DAYS,
) -> Optional[str]:
    """
    First date on/after request_date where paying the FULL requested_amount
    on that date keeps every subsequent day (through request_date+forecast_days)
    at or above minimum_balance_to_keep.

    We extend the window a little past forecast_days from request_date so a
    late-window payment still has its own tail checked, but never search
    past request_date + forecast_days per the spec's "within the forecast
    period" language.
    """
    window_dates = date_range(request_date, forecast_days)
    deltas = build_daily_deltas(events, window_dates)
    organic_balances = running_balance(start_balance, deltas, window_dates)

    for i, pay_date in enumerate(window_dates):
        # If we pay the full amount on pay_date, every day from pay_date
        # onward is reduced by requested_amount (one-time withdrawal).
        tail_min = min_balance_from(organic_balances, i) - requested_amount
        if tail_min >= minimum_balance_to_keep:
            return pay_date

    return None  # never becomes safe within the forecast window


def is_schedule_safe(
    start_balance: float,
    events: list[ForwardEvent],
    request_date: str,
    minimum_balance_to_keep: float,
    payments: list[tuple[str, float]],
    forecast_days: int = FORECAST_DAYS,
) -> bool:
    """
    Generic safety check for an arbitrary list of (date, amount) payments
    (used for installment plans and the two-payment partial_payment plan).
    Every payment is treated as a one-time withdrawal on its date, reducing
    balance on that date and every subsequent day within the window.
    """
    window_dates = date_range(request_date, forecast_days)
    deltas = build_daily_deltas(events, window_dates)
    organic_balances = running_balance(start_balance, deltas, window_dates)

    # cumulative withdrawal in effect by each date
    index_of = {d: i for i, d in enumerate(window_dates)}
    cumulative_withdrawal = [0.0] * len(window_dates)

    for pay_date, amount in payments:
        if pay_date not in index_of:
            # payment falls outside the forecast window - treat conservatively
            # as unsafe to verify (caller should avoid proposing such plans)
            return False
        start_idx = index_of[pay_date]
        for i in range(start_idx, len(window_dates)):
            cumulative_withdrawal[i] += amount

    for i, bal in enumerate(organic_balances):
        if bal - cumulative_withdrawal[i] < minimum_balance_to_keep:
            return False

    return True


def apply_spending_changes(
    events: list[ForwardEvent],
    changes: list[tuple[str, str, Optional[float]]],
) -> list[ForwardEvent]:
    """
    Apply spending changes to a copy of the event list.
    changes: list of (action, event_id_or_series_key, new_amount_or_None)
             action is "stop" or "reduce_to"
    Only events/series marked flexible (stoppable/reducible/reducible_or_stoppable)
    should ever be passed in here - enforce that at the call site using
    profile's expense_categories_user_is_willing_to_reduce / _to_stop lists
    combined with each event's own `flexibility` field.
    """
    changed = []
    change_map = {c[1]: c for c in changes}

    for ev in events:
        key = ev.series_key or ev.event_id
        if key in change_map:
            action, _, new_amount = change_map[key]
            if action == "stop":
                continue  # drop this occurrence entirely
            if action == "reduce_to" and new_amount is not None:
                # preserve sign (debit events are negative)
                sign = -1 if ev.amount < 0 else 1
                changed.append(ForwardEvent(
                    event_id=ev.event_id, date=ev.date,
                    amount=sign * abs(new_amount),
                    category=ev.category, flexibility=ev.flexibility,
                    minimum_allowed_amount=ev.minimum_allowed_amount,
                    source=ev.source, series_key=ev.series_key,
                ))
                continue
        changed.append(ev)

    return changed