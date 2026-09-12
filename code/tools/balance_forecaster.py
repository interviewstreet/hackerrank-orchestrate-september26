"""90-day balance simulation -- the deterministic accuracy core.

Cash-state rules enforced here (from the challenge spec):

* ``cancelled`` / ``failed`` rows never move money.
* ``non_cash`` / ``unrealized`` rows (investment valuations) are not cash.
* Pending *debits* are reserved; pending *credits* are ignored until settled.
* ``scheduled`` rows in the future are counted on their settlement date.
* Recurrence is inferred from history only -- never assumed.
* Foreign-currency cash events convert at the rate dated on settlement.

Recurrence is detected per ``(direction, category)`` rather than per
description, because variable essentials arrive under many different
descriptions ("Local market purchase", "Fresh food shop", "Supermarket
basket") that are one economic series.
"""

from __future__ import annotations

import re
from collections import defaultdict
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean

from tools.exchange_converter import ExchangeConverter
from validators.schemas import (
    BalanceForecast,
    CashFlow,
    Direction,
    EventStatus,
    FinancialEvent,
    FinancialProfile,
    Flexibility,
    SpendingChange,
)

# Event types that are inherently one-off: never projected forward.
NON_RECURRING_TYPES = frozenset(
    {"refund", "investment_purchase", "investment_sale", "investment_valuation"}
)
NON_RECURRING_CATEGORIES = frozenset({"windfall", "investment", "work_expense"})

# Statuses that never move money.
DEAD_STATUSES = frozenset({EventStatus.CANCELLED, EventStatus.FAILED, EventStatus.UNREALIZED})

# Descriptions naming a one-off receipt or charge. The spec forbids counting
# bonuses, commissions and windfalls as dependable future income, so these
# never seed a recurring series even when several appear in the history.
# Gig income ("Delivery platform payout", "Client retainer payment") is
# genuinely recurring here, so only unambiguous one-offs are listed.
ONE_OFF_DESCRIPTION = re.compile(
    r"\b(bonus|commission|arrear|windfall|lottery|prize|reimbursement|"
    r"reversal|authorization|one[- ]?time)\b",
    re.IGNORECASE,
)

# Descriptions stating that a series has ended. "Final employer payroll" is the
# last salary a user will receive, so projecting it forward would invent income.
TERMINAL_DESCRIPTION = re.compile(
    r"\b(final|last|closing|closed|terminated|ended|previous employer)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ForecastConfig:
    """Tunable knobs, calibrated against sample_requests.csv."""

    horizon_days: int = 90
    lookback_days: int = 120
    min_occurrences: int = 2
    # Conservatism for variable essentials: 0.0 = mean, 1.0 = observed max.
    variable_conservatism: float = 0.0
    # Cadences longer than this are treated as one-off, not recurring.
    max_cadence_days: int = 45
    min_cadence_days: int = 3


@dataclass
class Series:
    """A recurring cash series inferred from history."""

    key: str
    direction: Direction
    category: str
    cadence_days: int
    amount: float
    last_seen: date
    occurrences: int
    exemplar_event_id: str
    monthly: bool = False
    flexibility: Flexibility = Flexibility.FIXED
    minimum_allowed_amount: float | None = None
    descriptions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_variable(self) -> bool:
        return len(set(self.descriptions)) > 1

    @property
    def can_stop(self) -> bool:
        return self.flexibility in (
            Flexibility.STOPPABLE,
            Flexibility.REDUCIBLE_OR_STOPPABLE,
        )

    @property
    def can_reduce(self) -> bool:
        return self.flexibility in (
            Flexibility.REDUCIBLE,
            Flexibility.REDUCIBLE_OR_STOPPABLE,
        )


@dataclass
class ForecastModel:
    """Everything needed to simulate a user's balance forward."""

    profile: FinancialProfile
    request_date: date
    known_flows: list[CashFlow]
    series: list[Series]
    config: ForecastConfig

    def flows(
        self,
        spending_changes: list[SpendingChange] | None = None,
        extra: list[CashFlow] | None = None,
    ) -> list[CashFlow]:
        """All projected flows in the horizon, after optional spending changes."""
        stopped, reduced = _index_changes(spending_changes or [])
        horizon_end = self.request_date + timedelta(days=self.config.horizon_days)

        out = [f for f in self.known_flows if f.event_id not in stopped]
        for flow in out:
            if flow.event_id in reduced and flow.amount < 0:
                flow.amount = -abs(reduced[flow.event_id])

        for s in self.series:
            if s.exemplar_event_id in stopped:
                continue
            amount = s.amount
            if s.exemplar_event_id in reduced:
                amount = abs(reduced[s.exemplar_event_id])
            signed = amount if s.direction is Direction.CREDIT else -amount
            for when in _occurrences(s, self.request_date, horizon_end):
                out.append(
                    CashFlow(
                        on=when,
                        amount=signed,
                        label=f"{s.category} ({s.cadence_days}d)",
                        event_id=s.exemplar_event_id,
                        series_key=s.key,
                        projected=True,
                    )
                )

        out.extend(extra or [])
        # Existing commitments are reserved before same-day income (the safer
        # reading); a payment the plan adds is ordered last on its date.
        out.sort(key=lambda f: (f.on, f.sequence, f.amount))
        return out

    def simulate(
        self,
        spending_changes: list[SpendingChange] | None = None,
        extra: list[CashFlow] | None = None,
    ) -> tuple[float, dict[date, float]]:
        """Return the lowest balance reached and the balance after each dated flow."""
        balance = self.profile.current_available_balance
        lowest = balance
        trail: dict[date, float] = {}
        for flow in self.flows(spending_changes, extra):
            balance += flow.amount
            lowest = min(lowest, balance)
            trail[flow.on] = balance
        return lowest, trail

    # ---- headline figures --------------------------------------------------

    def amount_safe_today(
        self,
        requested_amount: float,
        spending_changes: list[SpendingChange] | None = None,
    ) -> float:
        """Most the user can pay on request_date without breaching the floor.

        A payment today shifts every later balance down by the same amount, so
        the ceiling is the lowest point of the unmodified projection minus the
        minimum the user wants to keep.
        """
        lowest, _ = self.simulate(spending_changes)
        headroom = lowest - self.profile.minimum_balance_to_keep
        return max(0.0, min(requested_amount, round(headroom, 2)))

    def earliest_full_payment(
        self,
        requested_amount: float,
        spending_changes: list[SpendingChange] | None = None,
    ) -> date | None:
        """First date a single full payment passes the safety check.

        Measures financial capacity only -- independent of which payment
        methods the user is willing to consider.
        """
        horizon_end = self.request_date + timedelta(days=self.config.horizon_days)
        when = self.request_date
        while when <= horizon_end:
            if self.is_safe_with(
                [
                    CashFlow(
                        on=when,
                        amount=-requested_amount,
                        label="full payment",
                        sequence=1,
                    )
                ],
                spending_changes,
            ):
                return when
            when += timedelta(days=1)
        return None

    def is_safe_with(
        self,
        payments: list[CashFlow],
        spending_changes: list[SpendingChange] | None = None,
    ) -> bool:
        """True when the projection stays at or above the floor throughout."""
        lowest, _ = self.simulate(spending_changes, extra=payments)
        return lowest >= self.profile.minimum_balance_to_keep - 0.005

    def summarise(
        self,
        requested_amount: float,
        spending_changes: list[SpendingChange] | None = None,
    ) -> BalanceForecast:
        lowest, _ = self.simulate(spending_changes)
        safe_today = self.amount_safe_today(requested_amount, spending_changes)
        return BalanceForecast(
            minimum_balance_reached=round(lowest, 2),
            amount_safe_to_pay=safe_today,
            earliest_full_payment_date=self.earliest_full_payment(
                requested_amount, spending_changes
            ),
            headroom_today=round(
                self.profile.current_available_balance
                - self.profile.minimum_balance_to_keep,
                2,
            ),
            is_safe=lowest >= self.profile.minimum_balance_to_keep - 0.005,
            flow_count=len(self.flows(spending_changes)),
        )


def build_forecast_model(
    profile: FinancialProfile,
    events: list[FinancialEvent],
    request_date: date,
    converter: ExchangeConverter,
    config: ForecastConfig | None = None,
) -> ForecastModel:
    """Reconstruct the user's forward cash position from their event history."""
    cfg = config or ForecastConfig()
    horizon_end = request_date + timedelta(days=cfg.horizon_days)

    known: list[CashFlow] = []
    history: dict[tuple[Direction, str], list[FinancialEvent]] = defaultdict(list)

    for event in events:
        if event.status in DEAD_STATUSES or not event.is_cash or event.amount is None:
            continue
        # Pending credits are not money yet.
        if event.status is EventStatus.PENDING and event.direction is Direction.CREDIT:
            continue

        when = event.cash_date
        amount = converter.convert(
            event.amount, event.currency or profile.home_currency,
            profile.home_currency, when,
        )
        signed = amount if event.direction is Direction.CREDIT else -amount

        if when > request_date:
            if when <= horizon_end:
                known.append(
                    CashFlow(
                        on=when,
                        amount=signed,
                        label=f"{event.status.value} {event.description}".strip(),
                        event_id=event.event_id,
                    )
                )
            # A confirmed future occurrence is still evidence of cadence: a
            # scheduled salary is often the only proof that income recurs.
            if _is_projectable(event):
                history[(event.direction, event.category)].append(event)
            continue

        if event.status is EventStatus.SETTLED and _is_projectable(event):
            history[(event.direction, event.category)].append(event)

    series = _detect_series(history, profile, converter, request_date, cfg)
    return ForecastModel(
        profile=profile,
        request_date=request_date,
        known_flows=known,
        series=series,
        config=cfg,
    )


def _is_projectable(event: FinancialEvent) -> bool:
    """Whether an event may contribute evidence of a recurring series."""
    if event.event_type in NON_RECURRING_TYPES:
        return False
    if event.category in NON_RECURRING_CATEGORIES:
        return False
    if ONE_OFF_DESCRIPTION.search(event.description):
        return False
    # A row linked to an earlier row is part of one lifecycle, not a series.
    return not event.linked_event_id


def _detect_series(
    history: dict[tuple[Direction, str], list[FinancialEvent]],
    profile: FinancialProfile,
    converter: ExchangeConverter,
    request_date: date,
    cfg: ForecastConfig,
) -> list[Series]:
    """Infer recurring series, using only categories with enough evidence."""
    window_start = request_date - timedelta(days=cfg.lookback_days)
    series: list[Series] = []

    for (direction, category), rows in history.items():
        recent = [e for e in rows if e.cash_date >= window_start]
        if len(recent) < cfg.min_occurrences:
            continue
        recent.sort(key=lambda e: e.cash_date)

        cadence = _cadence(recent)
        if cadence is None or not (cfg.min_cadence_days <= cadence <= cfg.max_cadence_days):
            continue
        # The series has been explicitly closed out; it does not continue.
        if TERMINAL_DESCRIPTION.search(recent[-1].description):
            continue

        amounts = [
            converter.convert(
                e.amount or 0.0, e.currency or profile.home_currency,
                profile.home_currency, e.cash_date,
            )
            for e in recent
        ]
        latest = recent[-1]
        series.append(
            Series(
                key=f"{direction.value}:{category}",
                direction=direction,
                category=category,
                cadence_days=cadence,
                amount=_projected_amount(amounts, direction, cfg),
                monthly=cadence == 30,
                last_seen=latest.cash_date,
                occurrences=len(recent),
                exemplar_event_id=latest.event_id,
                flexibility=_series_flexibility(recent),
                minimum_allowed_amount=_series_minimum(recent, profile, converter),
                descriptions=tuple(e.description for e in recent),
            )
        )
    series.sort(key=lambda s: s.key)
    return series


def _cadence(rows: list[FinancialEvent]) -> int | None:
    """Median gap between consecutive occurrences, snapped to a real rhythm.

    Observed gaps are noisy -- a monthly salary paid on the 15th shows gaps of
    28 to 31 days, and a mixed history can median out to something like 25. Real
    commitments recur weekly, fortnightly or monthly, so the raw median is
    snapped onto the nearest of those.
    """
    gaps = sorted(
        g
        for g in (
            (rows[i + 1].cash_date - rows[i].cash_date).days
            for i in range(len(rows) - 1)
        )
        if g > 0
    )
    if not gaps:
        return None
    median = gaps[len(gaps) // 2]
    for target, low, high in ((7, 6, 8), (14, 12, 16), (30, 25, 35)):
        if low <= median <= high:
            return target
    return max(1, median)


def _projected_amount(
    amounts: list[float], direction: Direction, cfg: ForecastConfig
) -> float:
    """Forward rate for a series.

    Income takes its most recently confirmed figure: a pay change is announced
    and then persists, so averaging it with superseded amounts would understate
    (or overstate) the rate going forward. Spending takes the mean of observed
    occurrences, optionally blended toward the observed maximum.
    """
    if not amounts:
        return 0.0
    if direction is Direction.CREDIT:
        return amounts[-1]
    average = mean(amounts)
    highest = max(amounts)
    return average + (highest - average) * cfg.variable_conservatism


def _series_flexibility(rows: list[FinancialEvent]) -> Flexibility:
    """The most permissive flexibility seen in the series."""
    for level in (
        Flexibility.REDUCIBLE_OR_STOPPABLE,
        Flexibility.STOPPABLE,
        Flexibility.REDUCIBLE,
    ):
        if any(e.flexibility is level for e in rows):
            return level
    return Flexibility.FIXED


def _series_minimum(
    rows: list[FinancialEvent], profile: FinancialProfile, converter: ExchangeConverter
) -> float | None:
    floors = [
        converter.convert(
            e.minimum_allowed_amount, e.currency or profile.home_currency,
            profile.home_currency, e.cash_date,
        )
        for e in rows
        if e.minimum_allowed_amount is not None
    ]
    return max(floors) if floors else None


def _occurrences(series: Series, after: date, until: date) -> list[date]:
    """Dates this series is projected to recur inside the window."""
    out: list[date] = []
    when = _advance(series, series.last_seen, 1)
    step = 1
    while when <= until:
        if when > after:
            out.append(when)
        step += 1
        when = _advance(series, series.last_seen, step)
    return out


def _advance(series: Series, anchor: date, steps: int) -> date:
    """The anchor moved forward by `steps` cadence periods."""
    if not series.monthly:
        return anchor + timedelta(days=series.cadence_days * steps)
    return _add_months(anchor, steps)


def _add_months(anchor: date, months: int) -> date:
    """Same day next month, clamped for short months (31 Jan -> 28 Feb)."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last_day = monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last_day))


def _index_changes(
    changes: list[SpendingChange],
) -> tuple[set[str], dict[str, float]]:
    stopped = {c.event_id for c in changes if c.change_type == "stop"}
    reduced = {
        c.event_id: c.new_amount
        for c in changes
        if c.change_type == "reduce_to" and c.new_amount is not None
    }
    return stopped, {k: v for k, v in reduced.items() if k not in stopped}
