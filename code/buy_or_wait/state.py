"""Cash-state reconstruction: which supplied records move real money, when.

The single most important rule here is that **history is not replayed**.
`current_available_balance` already represents the user's cash today; adding
settled historical events back on top of it would double-count every one of
them. Settled history is used only to *learn* recurrence (see `recurrence.py`).

Measured on the shipped dataset, the split is exact: every `settled` event is
dated on or before its request date, and every `pending` / `scheduled` /
`cancelled` / `failed` / `unrealized` event is dated after it. So "settled means
already in the balance" is not an approximation here.

Every record the forecast declines to fund carries an `exclusion_reason`, so a
later explanation can say *why* something was not counted rather than leaving it
silently absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from .fx import RateTable, RateUnavailable, convert
from .schema import FinancialEvent, Profile

# --- Why a record does not fund anything ------------------------------------

ALREADY_IN_BALANCE = "already_in_balance"
CANCELLED = "cancelled"
FAILED = "failed"
UNREALIZED = "unrealized_non_cash"
PENDING_CREDIT = "pending_credit_not_counted"
AMOUNT_UNKNOWN = "amount_unknown"
RATE_UNAVAILABLE = "rate_unavailable"


@dataclass(frozen=True)
class CashMovement:
    """One real future movement of money, in the user's home currency."""

    event_id: str
    on_date: date
    amount_home: Decimal          # always positive; direction carries the sign
    direction: str                # "debit" | "credit"
    category: str
    description: str
    source: str                   # "confirmed" | "projected"
    provenance: str               # human-readable citation of where it came from

    @property
    def signed(self) -> Decimal:
        return -self.amount_home if self.direction == "debit" else self.amount_home


@dataclass(frozen=True)
class ExcludedRecord:
    event_id: str
    reason: str
    direction: str
    detail: str = ""

    @property
    def is_unfunded_obligation(self) -> bool:
        """A debit we could not quantify.

        This is the dangerous class: an unknown *credit* merely means we forecast
        less income, which is conservative, but an unknown *debit* means a real
        obligation is missing from the forecast and any headroom we compute is
        unproven (review finding R01).
        """
        return self.direction == "debit" and self.reason in (AMOUNT_UNKNOWN, RATE_UNAVAILABLE)


@dataclass(frozen=True)
class CashState:
    opening_balance: Decimal
    minimum_balance: Decimal
    home_currency: str
    confirmed: tuple[CashMovement, ...]
    excluded: tuple[ExcludedRecord, ...]

    @property
    def unfunded_obligations(self) -> tuple[ExcludedRecord, ...]:
        """Debits that exist but could not be quantified.

        While this is non-empty the engine cannot certify a positive safe
        amount: the true balance is at most what we computed, and possibly less
        by an unknown quantity.
        """
        return tuple(r for r in self.excluded if r.is_unfunded_obligation)


def reconstruct(
    events: Iterable[FinancialEvent],
    profile: Profile,
    request_date: date,
    rates: RateTable,
) -> CashState:
    """Split the user's events into future cash movements and excluded records."""
    confirmed: list[CashMovement] = []
    excluded: list[ExcludedRecord] = []

    for event in events:
        reason = _exclusion_reason(event, request_date)
        if reason is not None:
            excluded.append(ExcludedRecord(event.event_id, reason, event.direction))
            continue

        if event.amount is None:
            # Blank amount: UNKNOWN, never zero. 15 of the 16 are debits.
            excluded.append(ExcludedRecord(event.event_id, AMOUNT_UNKNOWN, event.direction,
                                           f"{event.category} on {event.cash_date}"))
            continue

        try:
            converted = convert(
                event.amount,
                from_currency=event.currency,
                to_currency=profile.home_currency,
                on_date=event.cash_date,
                rates=rates,
            )
        except RateUnavailable as exc:
            excluded.append(ExcludedRecord(event.event_id, RATE_UNAVAILABLE, event.direction,
                                           str(exc)))
            continue

        confirmed.append(CashMovement(
            event_id=event.event_id,
            # A debit still pending on the request date is reserved immediately
            # rather than on a settlement date that has already passed.
            on_date=max(event.cash_date, request_date),
            amount_home=converted.amount,
            direction=event.direction,
            category=event.category,
            description=event.description,
            source="confirmed",
            provenance=f"event {event.event_id} ({event.status}) {converted.cite()}",
        ))

    return CashState(
        opening_balance=profile.current_available_balance,
        minimum_balance=profile.minimum_balance_to_keep,
        home_currency=profile.home_currency,
        confirmed=tuple(sorted(confirmed, key=lambda m: (m.on_date, m.event_id))),
        excluded=tuple(excluded),
    )


def _exclusion_reason(event: FinancialEvent, request_date: date) -> Optional[str]:
    """Why this event does not fund the forecast, or None if it does.

    Order matters: a cancelled record is cancelled regardless of its date.
    """
    if event.status == "cancelled":
        return CANCELLED
    if event.status == "failed":
        # A failed debit did not leave the account. If a message later says it
        # will be retried, M2 reinstates it as a new obligation -- it is not
        # resurrected here on the strength of the status alone.
        return FAILED
    if event.status == "unrealized" or event.direction == "non_cash":
        # Displayed portfolio value is not cash and no units were sold.
        return UNREALIZED
    if event.status == "pending" and event.direction == "credit":
        # Pending credits (refunds, prizes, bonuses, gig payouts) do not fund a
        # payment until they settle -- AGENTS.md section 6.3.
        return PENDING_CREDIT
    if event.status == "settled" and event.cash_date <= request_date:
        # Already reflected in current_available_balance; replaying it would
        # double-count.
        return ALREADY_IN_BALANCE
    return None


def linked_double_count_risk(state: CashState, events: Iterable[FinancialEvent]) -> tuple[str, ...]:
    """Report lifecycle links where both ends fund the forecast.

    A `linked_event_id` is not a generic duplicate marker: an
    investment purchase and its later sale are two real cash flows, and so are a
    debit and its refund. But two *representations* of one movement both counting
    would double-count it. Measured: this returns empty on the shipped dataset,
    which is why no generic de-duplication rule is applied. If the data ever
    changes, this makes the risk visible rather than silent.
    """
    funded = {m.event_id for m in state.confirmed}
    by_id = {e.event_id: e for e in events}
    return tuple(
        f"{event_id} and its linked {by_id[event_id].linked_event_id} both fund the forecast"
        for event_id in sorted(funded)
        if by_id[event_id].linked_event_id in funded
    )
