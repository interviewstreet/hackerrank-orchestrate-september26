"""Structural and referential audit of the loaded dataset.

`data.py` enforces what a single row must look like. This module enforces what
must be true *across* rows, and re-derives every closed vocabulary from the data
so a dataset change surfaces here -- as a named finding -- instead of as a
confusing validation failure three milestones later.

The audit makes no financial judgements and reads no labels. It is safe to run
with no credentials and no network.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .data import DataError, DataSet, safe_media_path
from .money import SOURCE_AMOUNT_DECIMALS, decimal_places
from .schema import (
    CURRENCIES,
    DIRECTIONS,
    EVENT_CATEGORIES,
    EVENT_STATUSES,
    EVENT_TYPES,
    FLEXIBILITIES,
    OBSERVED_FINANCIAL_PRIORITIES,
    PAYMENT_OPTION_METHODS,
    REQUEST_TYPES,
    SOURCE_TYPES,
)

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7}] {self.code}: {self.message}"


def _vocab_finding(code: str, name: str, expected: Iterable[str], actual: Iterable[str]) -> list[Finding]:
    expected_set, actual_set = set(expected), set(actual)
    out: list[Finding] = []
    if actual_set - expected_set:
        out.append(Finding(code, ERROR, f"{name}: values in data not in schema: {sorted(actual_set - expected_set)}"))
    if expected_set - actual_set:
        out.append(Finding(code, WARNING, f"{name}: values in schema not in data: {sorted(expected_set - actual_set)}"))
    return out


def audit_dataset(data: DataSet, *, media_dir: Path | None = None) -> list[Finding]:
    """Return every finding. An empty list means the dataset matches the contract."""
    findings: list[Finding] = []
    media_dir = media_dir or (data.dataset_dir / "media" / "images")

    # A01 -- closed vocabularies re-derived from the data.
    findings += _vocab_finding("A01", "event_type", EVENT_TYPES, {e.event_type for e in data.events})
    findings += _vocab_finding("A01", "category", EVENT_CATEGORIES, {e.category for e in data.events})
    findings += _vocab_finding("A01", "direction", DIRECTIONS, {e.direction for e in data.events})
    findings += _vocab_finding("A01", "status", EVENT_STATUSES, {e.status for e in data.events})
    findings += _vocab_finding("A01", "flexibility", FLEXIBILITIES, {e.flexibility for e in data.events})
    findings += _vocab_finding("A01", "currency", CURRENCIES, {e.currency for e in data.events})
    findings += _vocab_finding("A01", "source_type", SOURCE_TYPES, {m.source_type for m in data.messages})
    findings += _vocab_finding(
        "A01", "request_type", REQUEST_TYPES,
        {r.request_type for r in data.requests} | {r.request_type for r in data.sample_requests},
    )
    findings += _vocab_finding(
        "A01", "payment_option_method", PAYMENT_OPTION_METHODS,
        {o.payment_method for o in data.payment_options},
    )
    # Priorities are observed, not gating (see schema.OBSERVED_FINANCIAL_PRIORITIES),
    # so drift is reported and never fails the run.
    observed_priorities = {p for profile in data.profiles for p in profile.financial_priorities}
    for unexpected in sorted(observed_priorities - set(OBSERVED_FINANCIAL_PRIORITIES)):
        findings.append(Finding(
            "A01", WARNING,
            f"financial_priorities: {unexpected!r} not in the observed vocabulary "
            f"(informational -- priorities authorize nothing)",
        ))

    # A02 -- every request's user has a profile.
    for request in list(data.requests) + list(data.sample_requests):
        if request.user_id not in data.profiles_by_user:
            findings.append(Finding("A02", ERROR, f"{request.request_id}: no profile for {request.user_id}"))

    # A03 -- every event belongs to a known user.
    for event in data.events:
        if event.user_id not in data.profiles_by_user:
            findings.append(Finding("A03", ERROR, f"{event.event_id}: unknown user {event.user_id}"))

    # A04 -- lifecycle links resolve, stay in one user, and do not cycle.
    for event in data.events:
        link = event.linked_event_id
        if link is None:
            continue
        target = data.events_by_id.get(link)
        if target is None:
            findings.append(Finding("A04", ERROR, f"{event.event_id}: linked_event_id {link} does not exist"))
        elif target.user_id != event.user_id:
            findings.append(Finding(
                "A04", ERROR,
                f"{event.event_id} (user {event.user_id}) links to {link} owned by {target.user_id}",
            ))
        elif link == event.event_id:
            findings.append(Finding("A04", ERROR, f"{event.event_id}: links to itself"))
    findings += _link_cycles(data)

    # A05 -- offer coverage: 2-4 per request, and no orphan offers.
    known_requests = {r.request_id for r in data.requests} | {r.request_id for r in data.sample_requests}
    for request_id, options in sorted(data.options_by_request.items()):
        if request_id not in known_requests:
            findings.append(Finding("A05", ERROR, f"payment options reference unknown request {request_id}"))
        if not 2 <= len(options) <= 4:
            findings.append(Finding("A05", ERROR, f"{request_id}: {len(options)} payment options (expected 2-4)"))
    for request_id in sorted(known_requests):
        if request_id not in data.options_by_request:
            findings.append(Finding("A05", ERROR, f"{request_id}: no payment options"))

    # A06 -- offer arithmetic must be self-consistent; never silently repaired.
    for option in data.payment_options:
        product = option.payment_amount * option.number_of_payments
        if product != option.total_payable_amount:
            findings.append(Finding(
                "A06", ERROR,
                f"{option.payment_option_id}: payment_amount x n = {product} "
                f"!= total_payable_amount {option.total_payable_amount}",
            ))
        if option.total_payable_amount - option.financing_fee < Decimal("0"):
            findings.append(Finding("A06", ERROR, f"{option.payment_option_id}: financing_fee exceeds total"))
        if option.payment_method == "full_payment" and option.number_of_payments != 1:
            findings.append(Finding(
                "A06", ERROR,
                f"{option.payment_option_id}: full_payment offer has {option.number_of_payments} payments",
            ))

    # A07 -- an unknown amount must be recoverable; blank is never zero.
    for event in data.events:
        if not event.amount_is_unknown:
            continue
        linked = data.images_by_event.get(event.event_id, ())
        if not linked:
            findings.append(Finding(
                "A07", ERROR,
                f"{event.event_id}: amount is blank and no image links to it "
                f"({event.direction} {event.category}) -- it cannot be resolved or bounded",
            ))

    # A08 -- image references resolve and their files exist.
    for image in data.images:
        try:
            path = safe_media_path(media_dir, image.image_id)
        except DataError as exc:
            findings.append(Finding("A08", ERROR, str(exc)))
            continue
        if not path.exists():
            findings.append(Finding("A08", ERROR, f"{image.image_id}: missing file {path}"))
        if image.related_event_id:
            target = data.events_by_id.get(image.related_event_id)
            if target is None:
                findings.append(Finding(
                    "A08", ERROR, f"{image.image_id}: related_event_id {image.related_event_id} does not exist"
                ))
            elif target.user_id != image.user_id:
                findings.append(Finding(
                    "A08", ERROR,
                    f"{image.image_id} (user {image.user_id}) references event owned by {target.user_id}",
                ))
        if image.request_id:
            if image.request_id not in known_requests:
                findings.append(Finding("A08", ERROR, f"{image.image_id}: unknown request {image.request_id}"))
            elif data.request_owner(image.request_id) != image.user_id:
                findings.append(Finding(
                    "A13", ERROR,
                    f"{image.image_id} (user {image.user_id}) references request "
                    f"{image.request_id} owned by {data.request_owner(image.request_id)}",
                ))

    # A09 -- message references resolve and stay in scope.
    for message in data.messages:
        if message.user_id not in data.profiles_by_user:
            findings.append(Finding("A09", ERROR, f"{message.message_id}: unknown user {message.user_id}"))
        if message.related_event_id:
            target = data.events_by_id.get(message.related_event_id)
            if target is None:
                findings.append(Finding(
                    "A09", ERROR,
                    f"{message.message_id}: related_event_id {message.related_event_id} does not exist",
                ))
            elif target.user_id != message.user_id:
                findings.append(Finding(
                    "A09", ERROR,
                    f"{message.message_id} (user {message.user_id}) references event owned by {target.user_id}",
                ))
        if message.request_id:
            if message.request_id not in known_requests:
                findings.append(Finding(
                    "A09", ERROR, f"{message.message_id}: unknown request {message.request_id}"
                ))
            elif data.request_owner(message.request_id) != message.user_id:
                # A13 -- request-scoped evidence must not cross users. Existence
                # of the request id is necessary but nowhere near sufficient
                # (R-M0-03).
                findings.append(Finding(
                    "A13", ERROR,
                    f"{message.message_id} (user {message.user_id}) references request "
                    f"{message.request_id} owned by {data.request_owner(message.request_id)}",
                ))

    # A10 -- FX: every foreign cash record resolves on an EXACT directed
    # settlement-date rate. No nearest-date or reciprocal fallback is permitted,
    # so a gap here is a hard finding rather than a silent approximation.
    for event in data.events:
        profile = data.profiles_by_user.get(event.user_id)
        if profile is None or event.currency == profile.home_currency:
            continue
        key = (event.cash_date, event.currency, profile.home_currency)
        if key not in data.rates_by_key:
            findings.append(Finding(
                "A10", ERROR,
                f"{event.event_id}: no exact rate for {event.currency}->{profile.home_currency} "
                f"on {event.cash_date}",
            ))

    # A11 -- the blank template must describe exactly the evaluation set.
    template = data.dataset_dir / "output.csv"
    if template.exists():
        findings += _audit_template(template, {r.request_id for r in data.requests})

    # A14 -- informational: supplied precision beyond the output rendering
    # policy. Values are kept exactly as supplied (never rounded at load), so
    # this is not an error -- but if it fires, the two-decimal output convention
    # measured from the gold samples needs revisiting before publication.
    deep = [
        (event.event_id, event.amount) for event in data.events
        if event.amount is not None and decimal_places(event.amount) > SOURCE_AMOUNT_DECIMALS
    ]
    if deep:
        findings.append(Finding(
            "A14", WARNING,
            f"{len(deep)} event amount(s) carry more than {SOURCE_AMOUNT_DECIMALS} decimals "
            f"(e.g. {deep[0][0]}={deep[0][1]}); output rendering policy assumes 2",
        ))
    deep_rates = [r for r in data.exchange_rates if decimal_places(r.rate) > 6]
    if deep_rates:
        findings.append(Finding(
            "A14", WARNING, f"{len(deep_rates)} exchange rate(s) carry more than 6 decimals",
        ))

    # A12 -- informational: a permission the user can never act on.
    for profile in data.profiles:
        own = {e.category for e in data.events_by_user.get(profile.user_id, ())}
        unusable = (
            profile.expense_categories_user_is_willing_to_reduce
            | profile.expense_categories_user_is_willing_to_stop
        ) - own
        if unusable:
            findings.append(Finding(
                "A12", WARNING,
                f"{profile.user_id}: willing to change {sorted(unusable)} but has no such events",
            ))

    return findings


def _link_cycles(data: DataSet) -> list[Finding]:
    """Detect cycles in the `linked_event_id` chain (iterative; the chain is
    short but a cycle would otherwise hang traversal in a later milestone)."""
    findings: list[Finding] = []
    state: dict[str, int] = {}  # 0 = visiting, 1 = done
    for start in data.events:
        if state.get(start.event_id) == 1:
            continue
        path: list[str] = []
        current = start.event_id
        while current is not None and state.get(current) != 1:
            if state.get(current) == 0:
                findings.append(Finding("A04", ERROR, f"link cycle: {' -> '.join(path + [current])}"))
                break
            state[current] = 0
            path.append(current)
            node = data.events_by_id.get(current)
            current = node.linked_event_id if node else None
        for node_id in path:
            state[node_id] = 1
    return findings


def _audit_template(path: Path, expected_ids: set[str]) -> list[Finding]:
    import csv

    from .schema import OUTPUT_COLUMNS

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OUTPUT_COLUMNS:
            return [Finding("A11", ERROR, f"output.csv template header is {reader.fieldnames}")]
        ids = [row["request_id"] for row in reader]
    findings: list[Finding] = []
    if len(ids) != len(set(ids)):
        findings.append(Finding("A11", ERROR, "output.csv template has duplicate request_id values"))
    if set(ids) != expected_ids:
        findings.append(Finding(
            "A11", ERROR,
            f"output.csv template ids differ from requests.csv "
            f"(missing {len(expected_ids - set(ids))}, extra {len(set(ids) - expected_ids)})",
        ))
    return findings


def errors(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == ERROR]
