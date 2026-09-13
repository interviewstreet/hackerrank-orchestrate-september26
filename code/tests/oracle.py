"""An independent balance-replay oracle for testing the forecast.

This is deliberately a *second implementation*, written from the contract rather
than from `forecast.py`. Testing a solver by calling the same solver again
proves only that it is self-consistent, so the critical safety tests compare
`Forecast.is_safe()` against this and against hand-computed expectations.

Kept intentionally naive: build the full list of (date, signed amount) pairs,
sort with debits before credits on a shared date, and walk it. No shared
helpers with the engine beyond the dataclasses it reads.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence


def replay(
    opening_balance: Decimal,
    movements: Iterable,           # objects with .on_date, .direction, .amount_home
    payments: Sequence[tuple[date, Decimal]] = (),
) -> list[tuple[date, Decimal]]:
    """Return the running balance after each movement, chronologically."""
    rows: list[tuple[date, int, Decimal]] = []
    for movement in movements:
        signed = -movement.amount_home if movement.direction == "debit" else movement.amount_home
        rows.append((movement.on_date, 0 if movement.direction == "debit" else 1, signed))
    for when, amount in payments:
        rows.append((when, 0, -amount))       # a payment is a debit

    rows.sort(key=lambda row: (row[0], row[1]))

    balance = opening_balance
    trail: list[tuple[date, Decimal]] = []
    for when, _, signed in rows:
        balance += signed
        trail.append((when, balance))
    return trail


def lowest_balance(
    opening_balance: Decimal,
    movements: Iterable,
    payments: Sequence[tuple[date, Decimal]] = (),
) -> Decimal:
    trail = replay(opening_balance, movements, payments)
    return min([balance for _, balance in trail] + [opening_balance])


def is_safe(
    opening_balance: Decimal,
    minimum_balance: Decimal,
    movements: Iterable,
    payments: Sequence[tuple[date, Decimal]] = (),
) -> bool:
    return lowest_balance(opening_balance, movements, payments) >= minimum_balance
