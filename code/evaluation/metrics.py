"""Scoring helpers. No model calls, no file writes, no label loading.

Currencies are never pooled: an INR error of 1,000 and a USD error of 1,000 are
not comparable quantities, so amount error is reported per currency and a
normalized (relative) error is reported alongside it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional, Sequence


def accuracy(pairs: Sequence[tuple[str, str]]) -> tuple[int, int]:
    """Return (correct, total) so the caller can print numerator/denominator."""
    return sum(1 for pred, gold in pairs if pred == gold), len(pairs)


def macro_f1(pairs: Sequence[tuple[str, str]]) -> float:
    labels = {gold for _, gold in pairs} | {pred for pred, _ in pairs}
    scores = []
    for label in labels:
        tp = sum(1 for p, g in pairs if p == label and g == label)
        fp = sum(1 for p, g in pairs if p == label and g != label)
        fn = sum(1 for p, g in pairs if p != label and g == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def confusion(pairs: Sequence[tuple[str, str]]) -> Counter:
    """Counter of (gold -> pred) for mismatches only."""
    return Counter((gold, pred) for pred, gold in pairs if pred != gold)


def to_decimal(text: str) -> Optional[Decimal]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def amount_error_by_currency(
    rows: Iterable[tuple[str, str, str]],
) -> dict[str, dict[str, float]]:
    """`rows` is (currency, predicted, gold). Returns per-currency MAE, exact
    match and normalized error -- never a pooled cross-currency average."""
    buckets: dict[str, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    unparsed: Counter = Counter()
    for currency, predicted, gold in rows:
        p, g = to_decimal(predicted), to_decimal(gold)
        if p is None or g is None:
            unparsed[currency] += 1
            continue
        buckets[currency].append((p, g))

    out: dict[str, dict[str, float]] = {}
    for currency, pairs in sorted(buckets.items()):
        errors = [abs(p - g) for p, g in pairs]
        exact = sum(1 for p, g in pairs if p == g)
        relative = [
            float(abs(p - g) / g) for p, g in pairs if g != 0
        ]
        out[currency] = {
            "n": len(pairs),
            "mae": float(sum(errors) / len(errors)),
            "exact": exact,
            "exact_rate": exact / len(pairs),
            "normalized_mae": sum(relative) / len(relative) if relative else 0.0,
            "zero_gold": sum(1 for _, g in pairs if g == 0),
            "unparsed": unparsed.get(currency, 0),
        }
    return out


def exact_match(pairs: Sequence[tuple[str, str]]) -> tuple[int, int]:
    """String-equality match, used for payment_plan and dates."""
    return sum(1 for p, g in pairs if (p or "").strip() == (g or "").strip()), len(pairs)


def date_day_error(pairs: Sequence[tuple[str, str]]) -> tuple[float, int, int, int]:
    """Mean absolute day error over pairs where BOTH sides are dates.

    Returns (mean_days, compared, both_empty, disagree_on_emptiness) -- the last
    bucket matters: predicting "never safe" when the gold has a date is a
    different error from being a few days out.
    """
    from datetime import date

    deltas: list[int] = []
    both_empty = 0
    mismatched_emptiness = 0
    for predicted, gold in pairs:
        p, g = (predicted or "").strip(), (gold or "").strip()
        if not p and not g:
            both_empty += 1
            continue
        if not p or not g:
            mismatched_emptiness += 1
            continue
        try:
            deltas.append(abs((date.fromisoformat(p) - date.fromisoformat(g)).days))
        except ValueError:
            mismatched_emptiness += 1
    mean = sum(deltas) / len(deltas) if deltas else 0.0
    return mean, len(deltas), both_empty, mismatched_emptiness
