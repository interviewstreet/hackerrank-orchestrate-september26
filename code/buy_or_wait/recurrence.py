"""What repeats, and how much of it to reserve.

Settled history never touches the balance (see `state.py`); its only job is to
tell us what will happen again. This module answers that in two parts, because
the dataset contains two genuinely different kinds of spending and one model
cannot serve both:

**Fixed commitments** -- rent, a loan instalment, a subscription. Identical
amount, regular cadence, few in number. Projected as discrete dated movements,
because *when* they land decides whether a balance dips below the minimum.

**Variable essentials** -- groceries, transport, dining. Many descriptions,
changing amounts, irregular gaps. Reserved as a per-category daily rate built
from what the user actually spent over the lookback window. This is the part an
earlier design got wrong in both directions at once: projecting only the series
with three or more occurrences silently dropped a third of real spending
(12 of 25 series for `user_13`), while taking the maximum observed amount for
the ones it kept over-reserved the rest. Using the observed total over the
observed period is self-calibrating -- it reserves what this user actually
spends, no more and no less.

Every settled debit in the window is therefore counted exactly once: either it
belongs to a fixed series, or it feeds its category's rate.

**Income** is projected only when history shows a cadence, and stops being
projected when history shows it stopped: a series silent for more than one full
period has lapsed and is not carried forward. That is what keeps an ended
seasonal contract from funding a purchase.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from . import config
from .fx import RateTable, RateUnavailable, convert
from .money import ZERO, quantize
from .schema import FinancialEvent, Profile


@dataclass(frozen=True)
class FixedSeries:
    """A commitment that repeats at a stable amount and cadence."""

    category: str
    description: str
    direction: str
    period_days: int
    amount_home: Decimal
    last_seen: date
    occurrences: int
    event_ids: tuple[str, ...]
    flexibility: str
    minimum_allowed_amount: Decimal | None

    @property
    def provenance(self) -> str:
        return (f"{self.description} ({self.category}): {self.occurrences} occurrences "
                f"every ~{self.period_days}d, last {self.last_seen}")

    def occurrences_between(self, start: date, end: date) -> list[date]:
        out: list[date] = []
        cursor = self.last_seen + timedelta(days=self.period_days)
        while cursor <= end:
            if cursor >= start:
                out.append(cursor)
            cursor += timedelta(days=self.period_days)
        return out


@dataclass(frozen=True)
class CategoryRate:
    """Observed daily spend in a category, for essentials that vary."""

    category: str
    daily_amount: Decimal
    observed_total: Decimal
    observed_days: int
    event_ids: tuple[str, ...]

    @property
    def provenance(self) -> str:
        return (f"{self.category}: {self.observed_total} over {self.observed_days}d "
                f"({len(self.event_ids)} charges) = {self.daily_amount}/day")


@dataclass(frozen=True)
class Recurrence:
    fixed: tuple[FixedSeries, ...]
    rates: tuple[CategoryRate, ...]

    @property
    def all_provenance(self) -> tuple[str, ...]:
        return tuple(s.provenance for s in self.fixed) + tuple(r.provenance for r in self.rates)


def detect(
    events: Iterable[FinancialEvent],
    profile: Profile,
    request_date: date,
    rates: RateTable,
) -> Recurrence:
    """Split the user's recent history into fixed series and category rates."""
    window_days = config.RECURRENCE_LOOKBACK_DAYS
    window_start = request_date - timedelta(days=window_days)

    debits: list[tuple[FinancialEvent, Decimal]] = []
    credits: list[tuple[FinancialEvent, Decimal]] = []
    for event in events:
        if event.direction == "non_cash" or event.amount is None:
            continue
        if event.direction == "credit":
            # Scheduled income counts as evidence of cadence as well as a
            # confirmed movement: for a new job the only two salary records may
            # be one settled and one scheduled.
            if event.status not in ("settled", "scheduled"):
                continue
        elif event.status != "settled":
            continue
        if not (window_start <= event.cash_date <= request_date + timedelta(days=window_days)):
            continue
        if event.cash_date > request_date and event.direction == "debit":
            continue
        try:
            amount = convert(event.amount, from_currency=event.currency,
                             to_currency=profile.home_currency,
                             on_date=event.cash_date, rates=rates).amount
        except RateUnavailable:
            continue
        (credits if event.direction == "credit" else debits).append((event, amount))

    fixed: list[FixedSeries] = []
    consumed: set[str] = set()

    # --- fixed debit commitments -------------------------------------------
    for key, rows in _group(debits, by_description=True):
        series = _fixed_series(key[0], key[1], rows, require_constant=True)
        if series is not None:
            fixed.append(series)
            consumed.update(series.event_ids)

    # --- variable essentials: everything the fixed pass did not take -------
    leftovers = [(e, a) for e, a in debits if e.event_id not in consumed]
    category_rates = _category_rates(leftovers, window_days)

    # --- income ------------------------------------------------------------
    if config.PROJECT_RECURRING_INCOME:
        for key, rows in _group(credits, by_description=False):
            series = _income_series(key[0], rows, request_date)
            if series is not None:
                fixed.append(series)

    return Recurrence(
        fixed=tuple(sorted(fixed, key=lambda s: (s.category, s.description))),
        rates=tuple(category_rates),
    )


# ------------------------------------------------------------------ helpers --


def _group(rows: Sequence[tuple[FinancialEvent, Decimal]], *, by_description: bool):
    grouped: dict[tuple[str, str], list[tuple[FinancialEvent, Decimal]]] = {}
    for event, amount in rows:
        key = (event.category, event.description if by_description else "")
        grouped.setdefault(key, []).append((event, amount))
    return sorted(grouped.items())


def _period_of(dates: Sequence[date]) -> int | None:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    if not gaps:
        return None
    period = int(statistics.median(gaps))
    if not config.RECURRENCE_MIN_PERIOD_DAYS <= period <= config.RECURRENCE_MAX_PERIOD_DAYS:
        return None
    return period


def _fixed_series(category: str, description: str,
                  rows: Sequence[tuple[FinancialEvent, Decimal]],
                  *, require_constant: bool) -> FixedSeries | None:
    if len(rows) < config.RECURRENCE_MIN_OCCURRENCES:
        return None
    rows = sorted(rows, key=lambda pair: (pair[0].cash_date, pair[0].event_id))
    amounts = [amount for _, amount in rows]
    if require_constant and len(set(amounts)) != 1:
        # Varies -> it is not a fixed commitment; the category rate covers it.
        return None
    dates = [event.cash_date for event, _ in rows]
    period = _period_of(dates)
    if period is None:
        return None
    last_event = rows[-1][0]
    return FixedSeries(
        category=category,
        description=description,
        direction=last_event.direction,
        period_days=period,
        amount_home=max(amounts),
        last_seen=dates[-1],
        occurrences=len(rows),
        event_ids=tuple(event.event_id for event, _ in rows),
        flexibility=last_event.flexibility,
        minimum_allowed_amount=last_event.minimum_allowed_amount,
    )


def _income_series(category: str, rows: Sequence[tuple[FinancialEvent, Decimal]],
                   request_date: date) -> FixedSeries | None:
    """Project income only where a cadence is supported and still running.

    Grouped by category rather than description because payroll descriptions
    change while the salary continues -- `user_01`'s two records are "Prorated
    first salary" and "Next confirmed salary", one cadence under two names.
    Two occurrences suffice here (unlike debits, which need three) because
    income records are few, large and regular; requiring three would refuse to
    forecast any salary for a recently-started job.
    """
    if len(rows) < config.INCOME_MIN_OCCURRENCES:
        return None
    rows = sorted(rows, key=lambda pair: (pair[0].cash_date, pair[0].event_id))
    dates = [event.cash_date for event, _ in rows]
    period = _period_of(dates)
    if period is None:
        return None
    # Lapsed: silent for more than a full period means it stopped.
    if (request_date - dates[-1]).days > period:
        return None
    amounts = [amount for _, amount in rows]
    amount = amounts[-1] if config.PROJECTED_CREDIT_AMOUNT_POLICY == "latest" else min(amounts)
    last_event = rows[-1][0]
    return FixedSeries(
        category=category,
        description=f"recurring {category}",
        direction="credit",
        period_days=period,
        amount_home=amount,
        last_seen=dates[-1],
        occurrences=len(rows),
        event_ids=tuple(event.event_id for event, _ in rows),
        flexibility=last_event.flexibility,
        minimum_allowed_amount=None,
    )


def _category_rates(rows: Sequence[tuple[FinancialEvent, Decimal]],
                    window_days: int) -> list[CategoryRate]:
    """Daily spend per category from what was actually spent in the window."""
    pools: dict[str, list[tuple[FinancialEvent, Decimal]]] = {}
    for event, amount in rows:
        pools.setdefault(event.category, []).append((event, amount))

    out: list[CategoryRate] = []
    for category, entries in sorted(pools.items()):
        if category in config.PROJECTED_DEBIT_EXCLUDED_CATEGORIES:
            continue
        total = sum((amount for _, amount in entries), ZERO)
        if total <= ZERO:
            continue
        out.append(CategoryRate(
            category=category,
            daily_amount=quantize(total / Decimal(window_days)),
            observed_total=total,
            observed_days=window_days,
            event_ids=tuple(event.event_id for event, _ in entries),
        ))
    return out
