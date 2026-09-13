"""The only place expected-output values are read.

`code/buy_or_wait/` never imports this module. `RequestInput` has no field that
could hold a label, so prediction code cannot accidentally receive one; this
module is the matching behavioural half of that structural guarantee.

If you find yourself wanting to import `labels` from inside the engine, the
answer is no -- that is the leak this file exists to make obvious.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from buy_or_wait.schema import SAMPLE_COLUMNS, SAMPLE_LABEL_COLUMNS


@dataclass(frozen=True)
class SampleLabel:
    """Expected output for one public sample, kept as raw strings.

    Deliberately untyped beyond `str`: the evaluator compares rendered output to
    the file's own text, so parsing here would hide formatting differences that
    the scorer needs to see.
    """

    request_id: str
    amount_safe_to_pay: str
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str


def load_labels(sample_path: Path) -> dict[str, SampleLabel]:
    """Read `sample_requests.csv` label columns, keyed by request_id."""
    with Path(sample_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = tuple(reader.fieldnames or ())
        if actual != SAMPLE_COLUMNS:
            raise ValueError(f"sample_requests.csv header mismatch: {list(actual)}")
        labels: dict[str, SampleLabel] = {}
        for row in reader:
            request_id = (row["request_id"] or "").strip()
            labels[request_id] = SampleLabel(
                request_id=request_id,
                **{column: (row[column] or "").strip() for column in SAMPLE_LABEL_COLUMNS},
            )
    return labels


def label_columns() -> tuple[str, ...]:
    return SAMPLE_LABEL_COLUMNS


def find_leaked_columns(candidate: object) -> list[str]:
    """Return any label column exposed by `candidate`.

    Used by the label-isolation test to assert that nothing crossing the
    prediction boundary carries an expected output.
    """
    names: set[str] = set()
    if isinstance(candidate, dict):
        names = {str(k) for k in candidate}
    else:
        names = set(getattr(candidate, "__dataclass_fields__", {}) or {})
        if not names:
            names = {n for n in dir(candidate) if not n.startswith("_")}
    return sorted(names & set(SAMPLE_LABEL_COLUMNS))


def sample_exposure_note() -> str:
    """One sentence to print anywhere sample-derived numbers are reported."""
    return (
        "Public sample subset; all 25 examples were read during development, "
        "so reported numbers carry disclosed exposure and are not a hidden-test estimate."
    )


def optional_label(labels: dict[str, SampleLabel], request_id: str) -> Optional[SampleLabel]:
    return labels.get(request_id)
