"""Module 2: fx — currency conversion.

Implements the 5-step fallback algorithm confirmed in PLAN.md §4:

1. Direct match: a `rate_date == on_date` row for `from_currency -> to_currency`.
2. Inverse: no direct row that date, but the reverse direction exists -> `1 / rate`.
3. Bridge through USD: neither direct nor inverse exists that date (e.g. ZAR->IDR)
   -> combine `from -> USD` (or inverse) and `USD -> to` (or inverse) on that date.
4. No rate at all for `on_date`: fall back to the most recent `rate_date` that is
   `<= on_date` (never a future rate — avoids lookahead bias) and retry 1-3 there.
5. Still nothing (even bridging): treat as a data gap. Log it and return `None`
   instead of crashing, so the caller can apply the "financially safer
   interpretation" from AGENTS.md §6.3 (e.g. exclude the amount from cash
   available) rather than inventing a rate.

Deterministic, stdlib-only. No LLM calls happen here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from loaders import ExchangeRate

logger = logging.getLogger(__name__)

RatesByPair = dict[tuple[str, str], list[ExchangeRate]]


def _rate_on_date(rates_by_pair: RatesByPair, from_ccy: str, to_ccy: str, on_date: date) -> float | None:
    """Direct-or-inverse lookup for one exact date (steps 1-2, reused as a leg in step 3)."""
    for rate in rates_by_pair.get((from_ccy, to_ccy), ()):
        if rate.rate_date == on_date:
            return rate.rate
    for rate in rates_by_pair.get((to_ccy, from_ccy), ()):
        if rate.rate_date == on_date:
            return 1.0 / rate.rate
    return None


def _rate_on_date_with_bridge(
    rates_by_pair: RatesByPair, from_ccy: str, to_ccy: str, on_date: date
) -> float | None:
    """Steps 1-3: direct, inverse, or a single bridge leg through USD, for one exact date."""
    direct = _rate_on_date(rates_by_pair, from_ccy, to_ccy, on_date)
    if direct is not None:
        return direct

    if from_ccy == "USD" or to_ccy == "USD":
        return None

    leg1 = _rate_on_date(rates_by_pair, from_ccy, "USD", on_date)
    leg2 = _rate_on_date(rates_by_pair, "USD", to_ccy, on_date)
    if leg1 is not None and leg2 is not None:
        return leg1 * leg2
    return None


@dataclass
class FxConverter:
    """Wraps the exchange-rate index built by Module 1 (`Dataset.rates_by_pair`)."""

    rates_by_pair: RatesByPair
    _all_rate_dates: list[date] = field(init=False, repr=False)
    _rate_cache: dict[tuple[str, str, date], float | None] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        dates: set[date] = set()
        for rates in self.rates_by_pair.values():
            dates.update(rate.rate_date for rate in rates)
        self._all_rate_dates = sorted(dates)

    def get_rate(self, from_currency: str, to_currency: str, on_date: date) -> float | None:
        """Rate such that `amount_in_to = amount_in_from * rate`, per the 5-step algorithm."""
        if from_currency == to_currency:
            return 1.0

        cache_key = (from_currency, to_currency, on_date)
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        # Steps 1-3, on the exact requested date.
        rate = _rate_on_date_with_bridge(self.rates_by_pair, from_currency, to_currency, on_date)

        # Step 4: carry-forward to the most recent rate_date <= on_date. Never look ahead.
        if rate is None:
            for candidate_date in reversed(self._all_rate_dates):
                if candidate_date > on_date:
                    continue
                rate = _rate_on_date_with_bridge(self.rates_by_pair, from_currency, to_currency, candidate_date)
                if rate is not None:
                    break

        # Step 5: no rate found anywhere, even after carry-forward and bridging.
        if rate is None:
            logger.warning(
                "fx: no exchange rate found for %s -> %s on or before %s; "
                "treating as a data gap (caller should exclude the amount from cash available)",
                from_currency,
                to_currency,
                on_date,
            )

        self._rate_cache[cache_key] = rate
        return rate

    def convert(self, amount: float, from_currency: str, to_currency: str, on_date: date) -> float | None:
        """Convert `amount` from `from_currency` to `to_currency`, valued on `on_date`.

        Returns `None` when no rate can be found (step 5) — the caller must not
        invent a value, per AGENTS.md §6.3.
        """
        rate = self.get_rate(from_currency, to_currency, on_date)
        if rate is None:
            return None
        return amount * rate
