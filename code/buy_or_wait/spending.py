"""Spending-change candidates: which recurring flexible expenses may be cut.

`problem_statement.md`: "Only recurring expenses marked as flexible may be
changed." That scopes this module to `recurrence.fixed` debit series -- the
category-rate essentials in `recurrence.rates` are the sum of many different
transactions with no single `event_id` to cite, so they are not representable
as a `stop:<event_id>` / `reduce_to:<event_id>:<amount>` action and are
excluded here, not silently included at the wrong grain.

A future occurrence of a fixed series is a synthetic `CashMovement` created by
`forecast.build` (`event_id` like ``projected:category:description:date``), so
an action cannot reference that occurrence directly. It cites the series'
*most recent real event row* instead -- the one whose `flexibility` and
`minimum_allowed_amount` the series itself was built from -- and is applied to
every future occurrence of that (category, description) pair within the
forecast window.

`apply()` is the single production implementation of "what a spending change
does to a forecast". Both the planner (building candidates from live
`SpendingAction` objects) and the validation gate (rebuilding actions from the
published CSV strings via `from_literal`) call it, so a row can never be
approved on one arithmetic and re-checked on another.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterator, Optional, Sequence

from .forecast import Forecast
from .money import format_amount
from .recurrence import Recurrence
from .schema import (
    REDUCIBLE_FLEXIBILITIES,
    STOPPABLE_FLEXIBILITIES,
    FinancialEvent,
    Profile,
)

#: `problem_statement.md` "spending_changes_needed may contain up to three".
MAX_ACTIONS = 3


@dataclass(frozen=True)
class SpendingAction:
    action: str            # "stop" | "reduce"
    event_id: str          # citation: the series' most recent real event row
    category: str
    description: str
    freed_amount: Decimal  # headroom gained per occurrence, before replay
    new_amount: Optional[Decimal] = None   # set only for "reduce"

    def as_literal(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{format_amount(self.new_amount)}"


def eligible_actions(recurrence: Recurrence, profile: Profile) -> list[SpendingAction]:
    """Every action a spending-change candidate could legally propose.

    A `reducible_or_stoppable` series may offer both a stop and a reduce
    action on the *same* `event_id`; `combos()` below is responsible for never
    choosing both at once (`problem_statement.md`: "Stopping and reducing the
    same financial event are mutually exclusive").
    """
    actions: list[SpendingAction] = []
    for series in recurrence.fixed:
        if series.direction != "debit":
            continue
        if series.category in profile.expense_categories_to_protect:
            continue
        event_id = series.event_ids[-1]

        if (series.flexibility in STOPPABLE_FLEXIBILITIES
                and series.category in profile.expense_categories_user_is_willing_to_stop):
            actions.append(SpendingAction(
                action="stop", event_id=event_id, category=series.category,
                description=series.description, freed_amount=series.amount_home,
            ))

        if (series.flexibility in REDUCIBLE_FLEXIBILITIES
                and series.category in profile.expense_categories_user_is_willing_to_reduce
                and series.minimum_allowed_amount is not None
                and series.minimum_allowed_amount < series.amount_home):
            actions.append(SpendingAction(
                action="reduce", event_id=event_id, category=series.category,
                description=series.description,
                freed_amount=series.amount_home - series.minimum_allowed_amount,
                new_amount=series.minimum_allowed_amount,
            ))

    return sorted(actions, key=lambda a: (a.category, a.description, a.action))


def combos(actions: Sequence[SpendingAction]) -> Iterator[tuple[SpendingAction, ...]]:
    """Every combination of 1..MAX_ACTIONS actions touching distinct events.

    Smallest combinations first, so a caller that stops at the first success
    finds the fewest-actions plan deterministically.
    """
    for size in range(1, MAX_ACTIONS + 1):
        for combo in itertools.combinations(actions, size):
            ids = [a.event_id for a in combo]
            if len(set(ids)) == len(ids):
                yield combo


def apply(forecast: Forecast, actions: Sequence[SpendingAction]) -> Forecast:
    """Return a forecast with `actions` applied to every matching projection.

    Only touches synthetic projected debit movements -- a stop/reduce never
    reaches into `source == "confirmed"` movements, which are real supplied
    events outside this module's scope.
    """
    if not actions:
        return forecast
    stop_keys = {(a.category, a.description) for a in actions if a.action == "stop"}
    reduce_map = {(a.category, a.description): a.new_amount
                  for a in actions if a.action == "reduce"}
    if not stop_keys and not reduce_map:
        return forecast

    movements = []
    for movement in forecast.movements:
        key = (movement.category, movement.description)
        if movement.source == "projected" and movement.direction == "debit":
            if key in stop_keys:
                continue
            if key in reduce_map:
                movements.append(replace(movement, amount_home=reduce_map[key]))
                continue
        movements.append(movement)
    return replace(forecast, movements=tuple(movements))


def from_literal(item: str) -> Optional[tuple[str, str, Optional[Decimal]]]:
    """Parse one `spending_changes_needed` entry into `(action, event_id, new_amount)`.

    Returns `None` for anything that does not match the two documented shapes
    -- the caller (the validation gate) treats that as a failure, not a crash.
    """
    if item.startswith("stop:"):
        event_id = item[len("stop:"):]
        return ("stop", event_id, None) if event_id else None
    if item.startswith("reduce_to:"):
        rest = item[len("reduce_to:"):]
        parts = rest.split(":")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None
        try:
            amount = Decimal(parts[1])
        except Exception:  # noqa: BLE001 - any malformed literal is just invalid
            return None
        return ("reduce", parts[0], amount)
    return None


def apply_literals(
    forecast: Forecast,
    literals: Sequence[str],
    events_by_id: dict[str, FinancialEvent],
) -> Forecast:
    """Independently reconstruct and apply spending changes from published strings.

    Used only by the validation gate, so the gate proves what the row actually
    says rather than trusting the candidate object that produced it.
    """
    actions: list[SpendingAction] = []
    for item in literals:
        parsed = from_literal(item)
        if parsed is None:
            continue
        action, event_id, new_amount = parsed
        if new_amount is not None and (not new_amount.is_finite() or new_amount < 0):
            # A non-finite or negative reduce_to amount is invalid regardless
            # of validation.check's E7 -- do not let it corrupt the replay
            # forecast (e.g. a NaN movement amount).
            continue
        event = events_by_id.get(event_id)
        if event is None:
            continue
        actions.append(SpendingAction(
            action=action, event_id=event_id, category=event.category,
            description=event.description, freed_amount=Decimal("0"),
            new_amount=new_amount,
        ))
    return apply(forecast, actions)
