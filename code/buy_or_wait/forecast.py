"""The 90-day balance forecast and the safety check every plan must pass.

A forecast is a dated list of movements plus an opening balance. Safety is a
single question asked at every step: *does the balance ever fall below
`minimum_balance_to_keep`?* The answer must be checked after each movement, not
at month ends, because a bill on the 6th can breach the minimum even though the
balance recovers by the 15th.

Two conservative choices, both stated rather than assumed:

* **Debits settle before credits on the same date.** The dataset has no times,
  so we test the balance at its lowest plausible point that day.
* **An unquantified debit blocks certification.** If the state carries an
  obligation whose amount is unknown, the computed headroom is an upper bound,
  not a proof, and `certifiable` is False. The planner must not approve a
  payment on an upper bound.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from . import config
from .money import ZERO
from .recurrence import Recurrence
from .state import CashMovement, CashState


@dataclass(frozen=True)
class Step:
    """One point on the timeline, after applying that movement."""

    on_date: date
    balance: Decimal
    movement: CashMovement | None


@dataclass(frozen=True)
class Forecast:
    """A resolved timeline for one request."""

    request_date: date
    horizon: date
    opening_balance: Decimal
    minimum_balance: Decimal
    movements: tuple[CashMovement, ...]
    certifiable: bool
    uncertainty: tuple[str, ...]

    # -- core queries --------------------------------------------------------

    def walk(self, extra: Sequence[tuple[date, Decimal]] = ()) -> list[Step]:
        """Replay the timeline, optionally injecting extra debits (payments).

        `extra` is a list of `(date, amount)` payments, treated as debits.
        """
        ordered = _order(self.movements, extra)
        balance = self.opening_balance
        steps: list[Step] = [Step(self.request_date, balance, None)]
        for on_date, signed, movement in ordered:
            balance += signed
            steps.append(Step(on_date, balance, movement))
        return steps

    def minimum_over_window(self, extra: Sequence[tuple[date, Decimal]] = ()) -> Decimal:
        """Lowest balance reached at any point in the window."""
        return min(step.balance for step in self.walk(extra))

    def is_safe(self, extra: Sequence[tuple[date, Decimal]] = ()) -> bool:
        """Does the balance stay at or above the minimum throughout?

        The comparison is `>=`: landing exactly on `minimum_balance_to_keep` is
        safe, because the requirement is not to fall *below* it.
        """
        return self.minimum_over_window(extra) >= self.minimum_balance

    def breach_date(self, extra: Sequence[tuple[date, Decimal]] = ()) -> date | None:
        for step in self.walk(extra):
            if step.balance < self.minimum_balance:
                return step.on_date
        return None

    # -- the two headline numbers -------------------------------------------

    def headroom(self) -> Decimal:
        """The most that could be removed today without ever breaching.

        This is the baseline capacity, before any optional spending change and
        before considering which payment methods the user accepts.
        """
        return self.minimum_over_window() - self.minimum_balance

    def amount_safe_to_pay(self, requested: Decimal) -> Decimal:
        """`min(requested, max(0, headroom))`, and zero while uncertain.

        An unquantified obligation makes headroom an upper bound rather than a
        proof, so no positive amount can be certified from it.
        """
        if not self.certifiable:
            return ZERO
        return min(requested, max(ZERO, self.headroom()))

    def earliest_full_payment_date(self, requested: Decimal) -> date | None:
        """First date in the window on which paying `requested` in full is safe.

        Searched chronologically with the complete safety check, so a date only
        qualifies if the balance survives the payment *and* everything after it.
        This is pure capacity: it ignores optional spending changes and the
        user's payment-method preferences entirely
        (`problem_statement.md:163`).
        """
        if not self.certifiable:
            return None
        cursor = self.request_date
        while cursor <= self.horizon:
            if self.is_safe([(cursor, requested)]):
                return cursor
            cursor += timedelta(days=1)
        return None


def build(
    state: CashState,
    recurrence: Recurrence,
    request_date: date,
    *,
    horizon_days: int = config.FORECAST_DAYS,
) -> Forecast:
    """Assemble confirmed movements and projected recurrence into a timeline."""
    horizon = request_date + timedelta(days=horizon_days)

    movements = [m for m in state.confirmed if request_date <= m.on_date <= horizon]

    # Fixed commitments land on their own dates -- when they fall is what decides
    # whether the balance dips below the minimum.
    for item in recurrence.fixed:
        for when in item.occurrences_between(request_date, horizon):
            movements.append(CashMovement(
                event_id=f"projected:{item.category}:{item.description}:{when}",
                on_date=when,
                amount_home=item.amount_home,
                direction=item.direction,
                category=item.category,
                description=item.description,
                source="projected",
                provenance=item.provenance,
            ))

    # Variable essentials accrue daily. Charged at the start of each day, before
    # any credit that day, so the balance is tested at its lowest point.
    for rate in recurrence.rates:
        if rate.daily_amount <= ZERO:
            continue
        cursor = request_date
        while cursor <= horizon:
            movements.append(CashMovement(
                event_id=f"accrual:{rate.category}:{cursor}",
                on_date=cursor,
                amount_home=rate.daily_amount,
                direction="debit",
                category=rate.category,
                description=f"projected {rate.category} spending",
                source="projected",
                provenance=rate.provenance,
            ))
            cursor += timedelta(days=1)

    unfunded = state.unfunded_obligations
    uncertainty = tuple(
        f"{record.event_id}: {record.reason}" + (f" ({record.detail})" if record.detail else "")
        for record in unfunded
    )

    return Forecast(
        request_date=request_date,
        horizon=horizon,
        opening_balance=state.opening_balance,
        minimum_balance=state.minimum_balance,
        movements=tuple(sorted(movements, key=lambda m: (m.on_date, m.event_id))),
        certifiable=not unfunded,
        uncertainty=uncertainty,
    )


def _order(
    movements: Sequence[CashMovement],
    extra: Sequence[tuple[date, Decimal]],
) -> list[tuple[date, Decimal, CashMovement | None]]:
    """Sort movements by date, then by intra-day rank within a date.

    The dataset carries no times, so ordering within a day is a modelling choice
    and it is made differently for two different things:

    * rank 0 -- **existing obligations** (debits). Applied first, so the balance
      is tested at the lowest point the user does not control. Conservative.
    * rank 1 -- **credits**. Salary and other income.
    * rank 2 -- **a proposed payment**. Applied last, because the user chooses
      when to pay and would do so once the day's income has landed.

    Putting a proposed payment at rank 0 would be conservative in the abstract
    but wrong here: the solved examples repeatedly give an
    `earliest_date_for_full_payment` that is exactly the salary date, which is
    only reachable if the payment may follow that day's credit. Treating a
    voluntary payment like an unavoidable direct debit shifted every such answer
    one day late.
    """
    rows: list[tuple[date, int, str, Decimal, CashMovement | None]] = []
    for movement in movements:
        rank = 0 if movement.direction == "debit" else 1
        rows.append((movement.on_date, rank, movement.event_id, movement.signed, movement))
    for index, (when, amount) in enumerate(extra):
        rows.append((when, 2, f"__payment_{index:03d}", -amount, None))

    if not config.DEBITS_BEFORE_CREDITS:  # pragma: no cover - conservative default
        rows = [(d, 0, e, s, m) for d, _, e, s, m in rows]

    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return [(when, signed, movement) for when, _, _, signed, movement in rows]
