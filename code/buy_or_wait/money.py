"""Decimal money handling for the Buy or Wait? engine.

Money never touches float. Amounts are parsed straight from the source strings
with `Decimal` so that a value written as ``1302.40`` stays exact.

**Parsing and rounding are deliberately separate operations** (see review finding
R-M0-04). `parse_decimal` validates and preserves the source precision exactly;
it never rounds. `quantize` is the *output* policy and is applied only to a value
the engine itself produced -- a converted home-currency amount or a CSV field.
Rounding a supplied exchange rate at load time would silently alter the arithmetic
the problem statement tells us to use: a rate of ``20.12345`` must stay
``20.12345``, not become ``20.12``.

Rendering convention (measured, not assumed): across the 25 solved examples in
``dataset/sample_requests.csv`` no gold amount carries more than two decimal
places, and trailing zeros are stripped -- EUR appears as ``603.3`` (i.e.
603.30), ZAR as ``25256``, IDR as ``17229139.2``. So the output rule is:
quantize to two decimal places, then strip trailing zeros and a trailing point.
There is no per-currency precision table.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

#: Output precision for amounts the engine produces.
CENTS = Decimal("0.01")

#: Decimal places permitted in a supplied monetary amount before the audit
#: reports it. The shipped dataset uses at most 2; more is not an error (we keep
#: the exact value) but it means the output rendering policy needs revisiting.
SOURCE_AMOUNT_DECIMALS = 2

ZERO = Decimal("0")


class MoneyError(ValueError):
    """Raised when a source string cannot be trusted as a numeric value."""


def parse_decimal(raw: str | None, *, field: str, allow_blank: bool = False) -> Decimal | None:
    """Parse a numeric CSV cell exactly. **Never rounds.**

    Returns ``None`` only when the cell is blank *and* ``allow_blank`` is set --
    blank means "unknown", which is a different thing from zero and must stay
    distinguishable all the way to the forecast (15 of the 16 blank-amount rows
    in financial_events.csv are debits; defaulting them to zero would
    under-reserve real obligations).

    Rejects NaN, infinity, and anything non-numeric. Negative values are
    rejected because direction is carried by the ``direction`` column, so a
    negative magnitude would double-encode the sign.
    """
    s = (raw or "").strip()
    if not s:
        if allow_blank:
            return None
        raise MoneyError(f"{field}: blank value where a number is required")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise MoneyError(f"{field}: {s!r} is not a valid decimal") from exc
    if not value.is_finite():
        raise MoneyError(f"{field}: {s!r} is not finite")
    if value < 0:
        raise MoneyError(f"{field}: {s!r} is negative; sign belongs to `direction`")
    return value


def decimal_places(value: Decimal) -> int:
    """Number of digits after the point, as written (``Decimal('1.50')`` -> 2)."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def quantize(value: Decimal) -> Decimal:
    """Round to two decimal places, half-up (the convention a bank statement uses).

    This is the *output* policy. Apply it to values the engine computed, never to
    a value read from the dataset.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_amount(value: Decimal) -> str:
    """Render an amount the way the dataset writes it: at most two decimals,
    trailing zeros stripped, never scientific notation.

    ``Decimal.normalize()`` is deliberately not used -- it renders large integers
    as ``1.5656E+7``, which would corrupt IDR amounts in the output CSV.
    """
    text = format(quantize(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
