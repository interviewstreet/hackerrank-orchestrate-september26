"""Propose spending changes when no plan is safe without them.

A change is permitted only when all of these hold:

* the event's ``flexibility`` allows it (stoppable / reducible);
* the event's category is in the matching profile list
  (``..._willing_to_stop`` / ``..._willing_to_reduce``);
* the category is not in ``expense_categories_to_protect``;
* a ``reduce_to`` respects the event's ``minimum_allowed_amount``.

At most three changes are returned, and a single event is never both stopped
and reduced.
"""

from __future__ import annotations

from tools.balance_forecaster import ForecastModel, Series
from validators.schemas import Direction, FinancialProfile, SpendingChange

MAX_CHANGES = 3


def suggest_spending_changes(
    model: ForecastModel,
    profile: FinancialProfile,
    deficit: float,
) -> list[SpendingChange]:
    """Greedily cover `deficit` using the highest-impact permitted changes."""
    if deficit <= 0:
        return []

    candidates = sorted(
        (s for s in model.series if _is_changeable(s, profile)),
        key=lambda s: _monthly_impact(s),
        reverse=True,
    )

    changes: list[SpendingChange] = []
    recovered = 0.0
    for series in candidates:
        if len(changes) >= MAX_CHANGES or recovered >= deficit:
            break
        change = _best_change(series, profile)
        if change is None:
            continue
        changes.append(change)
        recovered += _savings(series, change)

    return changes


def _is_changeable(series: Series, profile: FinancialProfile) -> bool:
    if series.direction is not Direction.DEBIT:
        return False
    if profile.is_protected(series.category):
        return False
    if series.can_stop and profile.may_stop(series.category):
        return True
    return series.can_reduce and profile.may_reduce(series.category)


def _best_change(series: Series, profile: FinancialProfile) -> SpendingChange | None:
    """Stopping frees more cash than reducing, so prefer it when permitted."""
    if series.can_stop and profile.may_stop(series.category):
        return SpendingChange(change_type="stop", event_id=series.exemplar_event_id)

    if series.can_reduce and profile.may_reduce(series.category):
        floor = series.minimum_allowed_amount
        if floor is None or floor >= series.amount:
            return None
        return SpendingChange(
            change_type="reduce_to",
            event_id=series.exemplar_event_id,
            new_amount=round(floor, 2),
        )
    return None


def _savings(series: Series, change: SpendingChange) -> float:
    """Cash freed over the forecast horizon by this single change."""
    per_occurrence = (
        series.amount
        if change.change_type == "stop"
        else max(0.0, series.amount - (change.new_amount or 0.0))
    )
    occurrences = max(1, 90 // max(1, series.cadence_days))
    return per_occurrence * occurrences


def _monthly_impact(series: Series) -> float:
    return series.amount * (30.0 / max(1, series.cadence_days))
