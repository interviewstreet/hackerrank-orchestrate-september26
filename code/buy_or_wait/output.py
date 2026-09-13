"""Explanation rendering and atomic publication of `output.csv`.

Explanations are **rendered from the decision**, never written alongside it. A
template can only interpolate values the engine actually computed, so a sentence
that contradicts the recommendation -- or cites a number nobody calculated -- is
not representable. That is a stronger guarantee than checking prose afterwards.

Publication is atomic and verified: the file is built in memory, written to a
temporary file beside the destination, re-read and checked with explicit
exceptions, and only then moved into place. A crashed or failed run therefore
leaves the previous `output.csv` intact rather than a half-written one.
"""
from __future__ import annotations

import csv
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from .money import format_amount
from .planner import Decision
from .schema import NONE_LITERAL, OUTPUT_COLUMNS


class PublishError(RuntimeError):
    """Raised when the file we wrote does not match what we intended to write."""


# ----------------------------------------------------------- rendering ------


def render_plan(decision: Decision) -> str:
    if not decision.payments:
        return NONE_LITERAL
    return "|".join(
        f"{p.on_date.isoformat()}:{format_amount(p.amount)}" for p in decision.payments
    )


def render_spending_changes(decision: Decision) -> str:
    return "|".join(decision.spending_changes) if decision.spending_changes else NONE_LITERAL


def render_explanation(decision: Decision, currency: str, requested: Decimal,
                       minimum_balance: Decimal) -> str:
    """Build the explanation from the decision's own values.

    Every number below comes from a field of `decision` or from the request and
    profile -- none is re-derived, so the sentence cannot drift from the row.
    """
    amount = f"{currency} {format_amount(requested)}"
    floor = f"{currency} {format_amount(minimum_balance)}"
    method = decision.recommended_payment_method

    if method == "full_payment":
        when = decision.payments[0].on_date
        if decision.spending_changes:
            return (f"Pay {amount} on {when.isoformat()} after applying the required spending "
                    f"change(s) ({'; '.join(decision.spending_changes)}). "
                    f"This keeps at least {floor} available over the next 90 days.")
        return (f"Pay {amount} today ({when.isoformat()}). "
                f"This keeps at least {floor} available over the next 90 days.")

    if method == "wait":
        when = decision.payments[0].on_date
        return (f"Wait until {when.isoformat()}, then pay {amount} in full. "
                f"Paying sooner would take the balance below the {floor} minimum.")

    if method == "partial_payment":
        first, second = decision.payments
        return (f"Pay {currency} {format_amount(first.amount)} on {first.on_date.isoformat()} "
                f"and the remaining {currency} {format_amount(second.amount)} on "
                f"{second.on_date.isoformat()}. This completes the {amount} request while "
                f"keeping at least {floor} available throughout.")

    if method == "installments":
        first = decision.payments[0]
        return (f"Use {len(decision.payments)} installments of {currency} "
                f"{format_amount(first.amount)}, starting {first.on_date.isoformat()}. "
                f"This completes the {amount} request while keeping at least {floor} available.")

    if method == "not_recommended":
        if decision.degraded:
            return (f"Do not proceed with the {amount} request yet. Some obligations could "
                    f"not be quantified from the available records, so the {floor} minimum "
                    f"cannot be shown to be protected.")
        safe = f"{currency} {format_amount(decision.amount_safe_to_pay)}"
        if decision.earliest_date_for_full_payment is not None:
            return (f"Do not proceed with the {amount} request. The full amount is not "
                    f"forecast to be safe until "
                    f"{decision.earliest_date_for_full_payment.isoformat()}, and no payment "
                    f"method the user accepts completes it safely before then. "
                    f"{safe} is available today.")
        return (f"Do not proceed with the {amount} request. Although {safe} is available "
                f"today, the full amount cannot be completed safely within 90 days while "
                f"keeping the {floor} minimum.")

    raise PublishError(f"no explanation template for method {method!r}")


def to_row(decision: Decision, currency: str, requested: Decimal,
           minimum_balance: Decimal) -> dict[str, str]:
    earliest = decision.earliest_date_for_full_payment
    return {
        "request_id": decision.request_id,
        "amount_safe_to_pay": format_amount(decision.amount_safe_to_pay),
        "affordability_status": decision.affordability_status,
        "recommended_payment_method": decision.recommended_payment_method,
        "payment_plan": render_plan(decision),
        "earliest_date_for_full_payment": earliest.isoformat() if earliest else "",
        "spending_changes_needed": render_spending_changes(decision),
        "decision_explanation": render_explanation(decision, currency, requested, minimum_balance),
    }


# ---------------------------------------------------------- publication -----


def publish(rows: Sequence[dict[str, str]], destination: Path, expected_ids: Sequence[str],
            *, dataset_dir: Path | None = None) -> None:
    """Write `rows` to `destination` atomically, verifying before replacing.

    Refuses to write inside `dataset_dir`: the inputs are immutable, and the
    generated artifact belongs at the repository root.
    """
    destination = Path(destination).resolve()
    if dataset_dir is not None:
        dataset_dir = Path(dataset_dir).resolve()
        if dataset_dir == destination.parent or dataset_dir in destination.parents:
            raise PublishError(f"refusing to write predictions inside the dataset: {destination}")

    _check_before_writing(rows, expected_ids)

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", delete=False,
        dir=str(destination.parent), prefix=".output-", suffix=".tmp",
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_COLUMNS))
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row[column] for column in OUTPUT_COLUMNS})
        _verify_written(temp_path, expected_ids)
        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _check_before_writing(rows: Sequence[dict[str, str]], expected_ids: Sequence[str]) -> None:
    if len(rows) != len(expected_ids):
        raise PublishError(f"have {len(rows)} rows for {len(expected_ids)} requests")
    written = [row["request_id"] for row in rows]
    if written != list(expected_ids):
        missing = set(expected_ids) - set(written)
        extra = set(written) - set(expected_ids)
        raise PublishError(
            f"row ids do not match requests.csv (missing {sorted(missing)[:5]}, "
            f"extra {sorted(extra)[:5]}, or out of order)"
        )
    for row in rows:
        absent = [column for column in OUTPUT_COLUMNS if column not in row]
        if absent:
            raise PublishError(f"{row.get('request_id')}: missing column(s) {absent}")


def _verify_written(path: Path, expected_ids: Sequence[str]) -> None:
    """Re-read the file we just wrote and prove it says what we meant.

    Explicit exceptions, not `assert`: assertions vanish under `python -O`, and
    this is the last check before a submission artifact is published.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
            raise PublishError(f"written header is {reader.fieldnames}, expected {list(OUTPUT_COLUMNS)}")
        ids = [row["request_id"] for row in reader]
    if ids != list(expected_ids):
        raise PublishError("written request ids do not match the requests in order")
    if len(set(ids)) != len(ids):
        raise PublishError("written file contains duplicate request_id values")
