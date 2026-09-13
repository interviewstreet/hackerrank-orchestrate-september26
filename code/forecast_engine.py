"""Module 4: forecast_engine.

Builds the 90-day balance trajectory for one user's request and answers the
two questions Module 5 (`plan_selector`) needs before it can rank plans:
how much is safe to pay *today*, and the earliest date a *full* payment is
safe. Deterministic, stdlib-only — no LLM calls.

Pipeline (PLAN.md §6-7, AGENTS.md §6.3):

1. Detect recurring series per `(user_id, category, direction)` from the
   user's *settled, past* events (§7.1: group by category, not description).
   A group is recurring when it has >= 3 occurrences and the coefficient of
   variation (stdev/mean) of the day-gaps between them is < 0.3 (§7). A
   group whose amounts cluster into two clearly separated centers is split
   into two series instead of averaged together (§7.2 edge case).
2. Each recurring series gets one per-occurrence forecast amount: the most
   recent amount when its `flexibility` is `fixed`, otherwise the 75th
   percentile of its historical amounts (§6.2) — a deliberate overestimate
   of variable essential spending so the balance is never optimistic.
3. The forecast horizon (`request_date` .. `request_date + 90d`) is filled
   with two kinds of movements:
   - "known" future events already in the clean timeline (real event_id),
     honoring §6.3: `unrealized` is dropped entirely, a `pending` credit is
     not counted until it settles, everything else (`scheduled`, `pending`
     debit, a stray future `settled`) counts at its settlement date.
   - synthetic occurrences from each recurring series, stepped out from its
     last historical date by its cycle length — skipped for any cycle slot
     already covered by a known future event of the same category/direction,
     so a real record is never double-counted with a forecast guess.
4. Walking those movements from `profile.current_available_balance` gives a
   checkpoint trajectory. Because balance is flat between checkpoints, the
   earliest date any payment becomes safe is always a checkpoint date, so a
   suffix-min over checkpoints answers both `amount_safe_to_pay` (suffix-min
   from `request_date`) and `earliest_date_for_full_payment` (first
   checkpoint whose suffix-min still clears `minimum_balance_to_keep` after
   `requested_amount` is subtracted).
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from fx import FxConverter
from loaders import FinancialEvent, FinancialProfile

logger = logging.getLogger(__name__)

MIN_OCCURRENCES = 3
MAX_CV_FOR_RECURRING = 0.3
DEFAULT_HORIZON_DAYS = 90


def _coefficient_of_variation(gaps: list[int]) -> float:
    if len(gaps) < 2:
        return 0.0
    mean = statistics.mean(gaps)
    if mean == 0:
        return float("inf")
    return statistics.pstdev(gaps) / mean


def _percentile_75(values: list[float]) -> float:
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * 0.75
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def _split_bimodal(events: list[FinancialEvent]) -> list[list[FinancialEvent]]:
    """PLAN.md §7.2: split one (category, direction) group into two recurring
    series if its amounts form two well-separated clusters rather than noise
    around one center. Conservative: only splits when both halves would still
    qualify as recurring on their own (>= 3 occurrences each)."""
    amounts = sorted(e.amount for e in events)
    if len(amounts) < 2 * MIN_OCCURRENCES:
        return [events]
    span = amounts[-1] - amounts[0]
    if span <= 0:
        return [events]
    gap, split_idx = max(
        ((amounts[i + 1] - amounts[i], i) for i in range(len(amounts) - 1)),
        key=lambda pair: pair[0],
    )
    if gap / span < 0.4:
        return [events]
    threshold = (amounts[split_idx] + amounts[split_idx + 1]) / 2
    low = [e for e in events if e.amount <= threshold]
    high = [e for e in events if e.amount > threshold]
    if len(low) >= MIN_OCCURRENCES and len(high) >= MIN_OCCURRENCES:
        logger.info(
            "forecast_engine: split a (%s, %s) group into 2 recurring clusters "
            "by amount (bimodal, gap ratio %.2f) — flag for manual review",
            events[0].category,
            events[0].direction,
            gap / span,
        )
        return [low, high]
    return [events]


@dataclass(frozen=True)
class RecurringSeries:
    category: str
    direction: str
    cycle_days: float
    per_occurrence_amount: float
    is_fixed: bool
    last_occurrence_date: date
    sample_size: int
    coefficient_of_variation: float


def detect_recurring_series(settled_past_events: list[FinancialEvent]) -> list[RecurringSeries]:
    groups: dict[tuple[str, str], list[FinancialEvent]] = {}
    for event in settled_past_events:
        if event.amount is None or event.direction not in ("debit", "credit"):
            continue
        groups.setdefault((event.category, event.direction), []).append(event)

    series: list[RecurringSeries] = []
    for (category, direction), events in groups.items():
        for cluster in _split_bimodal(events):
            if len(cluster) < MIN_OCCURRENCES:
                continue
            cluster = sorted(cluster, key=lambda e: e.event_date)
            gaps = [
                (cluster[i + 1].event_date - cluster[i].event_date).days
                for i in range(len(cluster) - 1)
            ]
            if any(g <= 0 for g in gaps):
                continue  # same-day duplicates aren't a dated cycle we can step
            cv = _coefficient_of_variation(gaps)
            if cv >= MAX_CV_FOR_RECURRING:
                continue
            cycle_days = statistics.mean(gaps)
            is_fixed = Counter(e.flexibility for e in cluster).most_common(1)[0][0] == "fixed"
            amounts = [e.amount for e in cluster]
            per_occurrence = amounts[-1] if is_fixed else _percentile_75(amounts)
            series.append(
                RecurringSeries(
                    category=category,
                    direction=direction,
                    cycle_days=cycle_days,
                    per_occurrence_amount=per_occurrence,
                    is_fixed=is_fixed,
                    last_occurrence_date=cluster[-1].event_date,
                    sample_size=len(cluster),
                    coefficient_of_variation=cv,
                )
            )
    return series


@dataclass(frozen=True)
class ForecastPoint:
    on_date: date
    balance: float


@dataclass
class Forecast:
    user_id: str
    request_date: date
    horizon_end: date
    minimum_balance_to_keep: float
    trajectory: list[ForecastPoint]
    recurring_series: list[RecurringSeries]
    future_known_events: list[FinancialEvent]
    _suffix_min: list[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        suffix_min: list[float] = [0.0] * len(self.trajectory)
        running = float("inf")
        for i in range(len(self.trajectory) - 1, -1, -1):
            running = min(running, self.trajectory[i].balance)
            suffix_min[i] = running
        self._suffix_min = suffix_min

    def amount_safe_to_pay_now(self, requested_amount: float) -> float:
        """Max of `requested_amount` payable at `request_date` without the
        trajectory ever dipping below `minimum_balance_to_keep` over the horizon."""
        headroom = self._suffix_min[0] - self.minimum_balance_to_keep
        return max(0.0, min(requested_amount, headroom))

    def earliest_date_for_full_payment(self, requested_amount: float) -> Optional[date]:
        """First checkpoint date at which paying `requested_amount` in full stays
        safe for the rest of the horizon, or `None` if none exists within it."""
        for point, suffix_min in zip(self.trajectory, self._suffix_min):
            if suffix_min - requested_amount >= self.minimum_balance_to_keep:
                return point.on_date
        return None


def _signed_home_amount(
    event: FinancialEvent, home_currency: str, fx: FxConverter
) -> Optional[float]:
    if event.amount is None:
        logger.warning(
            "forecast_engine: event %s has no amount (unresolved fact) — "
            "excluding from forecast",
            event.event_id,
        )
        return None
    on_date = event.settlement_date or event.event_date
    converted = fx.convert(event.amount, event.currency, home_currency, on_date)
    if converted is None:
        return None
    return converted if event.direction == "credit" else -converted


def build_forecast(
    user_id: str,
    request_date: date,
    user_timeline: list[FinancialEvent],
    profile: FinancialProfile,
    fx: FxConverter,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> Forecast:
    """`user_timeline` must already be Module 3's clean, per-user event list."""
    horizon_end = request_date + timedelta(days=horizon_days)

    settled_past = [
        e
        for e in user_timeline
        if e.status == "settled"
        and e.amount is not None
        and e.settlement_date is not None
        and e.settlement_date <= request_date
    ]
    recurring_series = detect_recurring_series(settled_past)

    future_known: list[tuple[date, float, FinancialEvent]] = []
    for event in user_timeline:
        settle = event.settlement_date or event.event_date
        if settle is None or settle <= request_date:
            continue
        if event.status == "unrealized":
            continue  # never treat unrealized investment value as available cash
        if event.status == "pending" and event.direction == "credit":
            continue  # don't count a pending credit until it settles
        signed = _signed_home_amount(event, profile.home_currency, fx)
        if signed is None:
            continue
        future_known.append((settle, signed, event))

    known_dates_by_series: dict[tuple[str, str], list[date]] = {}
    for settle, _, event in future_known:
        known_dates_by_series.setdefault((event.category, event.direction), []).append(settle)

    synthetic_movements: list[tuple[date, float]] = []
    for series in recurring_series:
        step = timedelta(days=max(round(series.cycle_days), 1))
        next_date = series.last_occurrence_date + step
        while next_date <= request_date:
            next_date += step
        known_dates = known_dates_by_series.get((series.category, series.direction), [])
        half_cycle = series.cycle_days / 2
        while next_date <= horizon_end:
            covered_by_known = any(
                abs((next_date - kd).days) <= half_cycle for kd in known_dates
            )
            if not covered_by_known:
                signed = (
                    series.per_occurrence_amount
                    if series.direction == "credit"
                    else -series.per_occurrence_amount
                )
                synthetic_movements.append((next_date, signed))
            next_date += step

    movements = [(settle, signed) for settle, signed, _ in future_known] + synthetic_movements
    movements.sort(key=lambda m: m[0])

    trajectory = [ForecastPoint(on_date=request_date, balance=profile.current_available_balance)]
    running_balance = profile.current_available_balance
    idx = 0
    while idx < len(movements):
        current_date = movements[idx][0]
        day_total = 0.0
        while idx < len(movements) and movements[idx][0] == current_date:
            day_total += movements[idx][1]
            idx += 1
        running_balance += day_total
        trajectory.append(ForecastPoint(on_date=current_date, balance=running_balance))

    return Forecast(
        user_id=user_id,
        request_date=request_date,
        horizon_end=horizon_end,
        minimum_balance_to_keep=profile.minimum_balance_to_keep,
        trajectory=trajectory,
        recurring_series=recurring_series,
        future_known_events=[event for _, _, event in future_known],
    )
