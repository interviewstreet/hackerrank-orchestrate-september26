"""Currency conversion using the fixed, dated rates in exchange_rates.csv.

The dataset supplies rates for specific dates and a specific direction. For a
foreign-currency cash event we look up the row matching its settlement date and
the stated from->to direction, falling back to the nearest available date and
then to the reciprocal of the inverse pair.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import date

from validators.schemas import ExchangeRate


class ExchangeConverter:
    """Dated FX lookup with nearest-date and reciprocal fallbacks."""

    def __init__(self, rates: list[ExchangeRate]) -> None:
        self._by_pair: dict[tuple[str, str], dict[date, float]] = {}
        for rate in rates:
            pair = (rate.from_currency.upper(), rate.to_currency.upper())
            self._by_pair.setdefault(pair, {})[rate.rate_date] = rate.rate
        self._sorted_dates: dict[tuple[str, str], list[date]] = {
            pair: sorted(table) for pair, table in self._by_pair.items()
        }

    def convert(self, amount: float, from_currency: str, to_currency: str, on: date) -> float:
        """Convert `amount` into `to_currency` using the rate dated at `on`."""
        src = (from_currency or "").upper()
        dst = (to_currency or "").upper()
        if not src or not dst or src == dst:
            return amount

        rate = self._lookup(src, dst, on)
        if rate is not None:
            return amount * rate

        inverse = self._lookup(dst, src, on)
        if inverse:
            return amount / inverse

        # No rate supplied for this pair: return unconverted rather than
        # fabricating a rate, and let the caller's logging surface it.
        return amount

    def _lookup(self, src: str, dst: str, on: date) -> float | None:
        table = self._by_pair.get((src, dst))
        if not table:
            return None
        if on in table:
            return table[on]
        return table[self._nearest_date((src, dst), on)]

    def _nearest_date(self, pair: tuple[str, str], on: date) -> date:
        dates = self._sorted_dates[pair]
        idx = bisect_left(dates, on)
        if idx == 0:
            return dates[0]
        if idx >= len(dates):
            return dates[-1]
        before, after = dates[idx - 1], dates[idx]
        return before if (on - before) <= (after - on) else after
