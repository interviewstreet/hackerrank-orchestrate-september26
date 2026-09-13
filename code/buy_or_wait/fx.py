"""Currency conversion using only the supplied dated rates.

The contract (`AGENTS.md` §6.1) is exact: for a foreign-currency cash event, use
the row for **its settlement date** and **the stated from->to direction**. This
module implements that and nothing else.

Three things it deliberately will not do:

* **No nearest-date fallback.** All 140 foreign-currency events in the shipped
  dataset resolve on an exact directed settlement-date row, so a fallback would
  never help correctness and would silently substitute a different number if the
  data changed.
* **No reciprocal.** A USD->ZAR row does not authorize a ZAR->USD conversion;
  inverting a rounded rate is not the supplied rate.
* **No live lookup.** There is no network in this engine.

A missing rate is *unresolved evidence*, raised as `RateUnavailable`, so the
caller can degrade the row honestly instead of guessing a number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping

from .money import quantize
from .schema import ExchangeRate


class RateUnavailable(LookupError):
    """No supplied rate covers this (date, from, to). Never guess one."""

    def __init__(self, on_date: date, from_currency: str, to_currency: str) -> None:
        super().__init__(
            f"no supplied rate for {from_currency}->{to_currency} on {on_date}"
        )
        self.on_date = on_date
        self.from_currency = from_currency
        self.to_currency = to_currency


@dataclass(frozen=True)
class Converted:
    """A conversion with its provenance, so an explanation can cite the rate."""

    amount: Decimal
    rate: Decimal | None          # None for an identity conversion
    rate_date: date | None
    from_currency: str
    to_currency: str

    def cite(self) -> str:
        if self.rate is None:
            return f"{self.from_currency} (home currency)"
        return f"{self.from_currency}->{self.to_currency} @ {self.rate} on {self.rate_date}"


RateTable = Mapping[tuple[date, str, str], ExchangeRate]


def convert(
    amount: Decimal,
    *,
    from_currency: str,
    to_currency: str,
    on_date: date,
    rates: RateTable,
) -> Converted:
    """Convert `amount` using the exact supplied rate for `on_date`.

    The converted value is rounded to two decimals because it is a value this
    engine produced; the *rate itself* is used at full supplied precision (see
    `money.parse_decimal` and review finding R-M0-04).
    """
    if from_currency == to_currency:
        return Converted(amount, None, None, from_currency, to_currency)

    row = rates.get((on_date, from_currency, to_currency))
    if row is None:
        raise RateUnavailable(on_date, from_currency, to_currency)

    return Converted(
        amount=quantize(amount * row.rate),
        rate=row.rate,
        rate_date=row.rate_date,
        from_currency=from_currency,
        to_currency=to_currency,
    )


def can_convert(*, from_currency: str, to_currency: str, on_date: date, rates: RateTable) -> bool:
    return from_currency == to_currency or (on_date, from_currency, to_currency) in rates
