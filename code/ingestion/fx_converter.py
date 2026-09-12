"""
fx_converter.py — Dated Exchange Rate Engine.

Loads dataset/exchange_rates.csv and provides:
1. Direct lookup:      convert(amount, from_curr, to_curr, on_date)
2. Inverse rate:       if (to, from) exists but not (from, to)
3. Triangulation:      via USD or EUR as a bridge currency

Per §6.3: "For a foreign-currency cash event, use the row for its
settlement_date and the stated from_currency to to_currency direction."

Rate selection priority (per §6.3 conflict rules):
  - Exact date match first
  - Then the most recent rate on or before the settlement_date
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# (from_currency, to_currency) -> sorted list of (rate_date, rate)
_RateKey = Tuple[str, str]
_RateRecord = Tuple[date, Decimal]

BRIDGE_CURRENCIES = ("USD", "EUR")


@dataclass(frozen=True)
class ConversionResult:
    original_amount: Decimal
    from_currency: str
    to_currency: str
    rate: Decimal
    converted_amount: Decimal
    rate_date: date
    via: Optional[str] = None  # bridge currency used, if any


class FXConverter:
    """
    Dated FX conversion engine built from exchange_rates.csv.

    Usage:
        fx = FXConverter(Path("dataset/exchange_rates.csv"))
        result = fx.convert(Decimal("100"), "EUR", "ZAR", date(2024, 3, 3))
        home_amount = result.converted_amount
    """

    def __init__(self, rates_path: Path) -> None:
        self._rates_path = Path(rates_path)
        # (from_currency, to_currency) -> sorted [(date, rate), ...]
        self._table: Dict[_RateKey, List[_RateRecord]] = {}
        self._loaded = False

    def load(self) -> None:
        """Parse exchange_rates.csv into an in-memory lookup table. Idempotent."""
        if self._loaded:
            return
        if not self._rates_path.exists():
            raise FileNotFoundError(f"Exchange rates file not found: {self._rates_path}")

        with open(self._rates_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    rate_date = date.fromisoformat(row["rate_date"].strip())
                    from_curr = row["from_currency"].strip().upper()
                    to_curr = row["to_currency"].strip().upper()
                    rate = Decimal(row["rate"].strip())
                    if rate <= 0:
                        raise ValueError(f"rate must be positive, got {rate}")
                    key: _RateKey = (from_curr, to_curr)
                    self._table.setdefault(key, []).append((rate_date, rate))
                except Exception as exc:
                    logger.warning("Skipping bad FX row: %s | %s", row, exc)

        # Sort each list chronologically for bisect-style lookups
        for key in self._table:
            self._table[key].sort(key=lambda r: r[0])

        self._loaded = True
        logger.info("FX table loaded: %d rate pairs", len(self._table))

    # ── Public API ──────────────────────────────────────────────────────────

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        on_date: date,
    ) -> ConversionResult:
        """
        Convert `amount` from `from_currency` to `to_currency` using the
        most recent rate on or before `on_date`.

        Raises ValueError if no conversion path can be found.
        """
        if not self._loaded:
            self.load()

        from_curr = from_currency.upper()
        to_curr = to_currency.upper()

        if from_curr == to_curr:
            return ConversionResult(
                original_amount=amount,
                from_currency=from_curr,
                to_currency=to_curr,
                rate=Decimal("1"),
                converted_amount=amount,
                rate_date=on_date,
            )

        # 1. Direct lookup
        direct = self._lookup_rate(from_curr, to_curr, on_date)
        if direct is not None:
            rate_date, rate = direct
            return ConversionResult(
                original_amount=amount,
                from_currency=from_curr,
                to_currency=to_curr,
                rate=rate,
                converted_amount=self._apply(amount, rate),
                rate_date=rate_date,
            )

        # 2. Inverse lookup
        inverse = self._lookup_rate(to_curr, from_curr, on_date)
        if inverse is not None:
            rate_date, rate = inverse
            inv_rate = Decimal("1") / rate
            return ConversionResult(
                original_amount=amount,
                from_currency=from_curr,
                to_currency=to_curr,
                rate=inv_rate,
                converted_amount=self._apply(amount, inv_rate),
                rate_date=rate_date,
            )

        # 3. Triangulate via bridge currencies
        for bridge in BRIDGE_CURRENCIES:
            if bridge in (from_curr, to_curr):
                continue
            leg1 = self._get_rate_any_direction(from_curr, bridge, on_date)
            leg2 = self._get_rate_any_direction(bridge, to_curr, on_date)
            if leg1 is not None and leg2 is not None:
                rate_date1, rate1 = leg1
                rate_date2, rate2 = leg2
                combined_rate = rate1 * rate2
                converted = self._apply(amount, combined_rate)
                logger.debug(
                    "FX triangulation %s->%s->%s on %s rate=%.6f",
                    from_curr, bridge, to_curr, on_date, combined_rate,
                )
                return ConversionResult(
                    original_amount=amount,
                    from_currency=from_curr,
                    to_currency=to_curr,
                    rate=combined_rate,
                    converted_amount=converted,
                    rate_date=min(rate_date1, rate_date2),
                    via=bridge,
                )

        raise ValueError(
            f"No FX conversion path found: {from_curr} -> {to_curr} on {on_date}. "
            f"Available pairs: {[f'{a}->{b}' for a, b in self._table.keys()]}"
        )

    def is_home_currency(self, currency: str, home_currency: str) -> bool:
        return currency.upper() == home_currency.upper()

    def to_home_currency(
        self,
        amount: Decimal,
        currency: str,
        home_currency: str,
        on_date: date,
    ) -> Decimal:
        """Convert to home currency; returns amount unchanged if already home."""
        if self.is_home_currency(currency, home_currency):
            return amount
        result = self.convert(amount, currency, home_currency, on_date)
        return result.converted_amount

    # ── Private helpers ─────────────────────────────────────────────────────

    def _lookup_rate(
        self,
        from_curr: str,
        to_curr: str,
        on_date: date,
    ) -> Optional[_RateRecord]:
        """Return the most recent (date, rate) on or before on_date, or None."""
        key: _RateKey = (from_curr, to_curr)
        records = self._table.get(key)
        if not records:
            return None
        # Binary search: find rightmost record with date <= on_date
        best: Optional[_RateRecord] = None
        lo, hi = 0, len(records) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if records[mid][0] <= on_date:
                best = records[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _get_rate_any_direction(
        self,
        from_curr: str,
        to_curr: str,
        on_date: date,
    ) -> Optional[_RateRecord]:
        """Try direct lookup, then inverse lookup."""
        direct = self._lookup_rate(from_curr, to_curr, on_date)
        if direct is not None:
            return direct
        inverse = self._lookup_rate(to_curr, from_curr, on_date)
        if inverse is not None:
            rate_date, rate = inverse
            return rate_date, Decimal("1") / rate
        return None

    @staticmethod
    def _apply(amount: Decimal, rate: Decimal) -> Decimal:
        """Multiply and round to 2 decimal places."""
        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
