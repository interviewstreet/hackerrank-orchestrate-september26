"""Module 3: event_normalizer.

Turns the raw `financial_events.csv` rows plus optional structured `Fact`s
(the output of Module 6's `llm_extract`, empty for now) into one clean,
conflict-resolved timeline per user, following AGENTS.md §6.3:

- Drop `cancelled` / `failed` events outright — they never happened.
- When a `Fact` conflicts with an event (or another `Fact`) about the same
  event, resolve in this order (§6.3, confirmed with PLAN.md §8 test cases):
    1. An explicit cancellation, settlement, or amendment beats a merely
       confirming or ambiguous one.
    2. Among equally explicit facts, the newer record from the same source
       wins.
    3. Otherwise, prefer whichever implies the event is `settled`.
    4. Otherwise, take the financially safer interpretation: for a credit,
       treat it as *not* received; for a debit, keep it reserved.
- A `Fact` that names no target event and is not a brand-new event (e.g. an
  ambiguous windfall report with no `related_event_id`) attaches to nothing
  safely, so it is logged and dropped rather than invented into the
  timeline (§6.3 "do not invent unsupported ... financial facts").

This module does not decide *how* pending/settled/unrealized events count
toward cash flow — that is Module 4 (`forecast_engine`). It only produces
the cleaned, deduplicated set of events that Module 4 walks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Literal, Optional

from loaders import FinancialEvent

logger = logging.getLogger(__name__)

EXCLUDED_STATUSES = {"cancelled", "failed"}

FactKind = Literal["amend_event", "cancel_event", "confirm_event", "new_event"]


@dataclass(frozen=True)
class Fact:
    """A structured fact distilled from a message or image (Module 6 output).

    `kind="new_event"` carries a fully-formed `new_event` and no `target_event_id`.
    Every other kind targets an existing event via `target_event_id` and carries
    only the fields it amends (the rest stay `None` = "no change").
    """

    kind: FactKind
    source_message_id: Optional[str] = None
    source_type: str = ""
    source_sent_at: Optional[datetime] = None
    target_event_id: Optional[str] = None
    amended_amount: Optional[float] = None
    amended_status: Optional[str] = None
    amended_settlement_date: Optional[date] = None
    new_event: Optional[FinancialEvent] = None
    note: str = ""


def _is_explicit(fact: Fact) -> bool:
    return fact.kind in ("cancel_event", "amend_event")


_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def _comparable_sent_at(fact: Fact) -> datetime:
    """Normalize to an aware datetime so facts with/without tzinfo (or none
    at all) can always be compared, even though real Message.sent_at values
    are UTC-aware and a hand-built or missing one might not be."""
    sent_at = fact.source_sent_at
    if sent_at is None:
        return _MIN_DATETIME
    if sent_at.tzinfo is None:
        return sent_at.replace(tzinfo=timezone.utc)
    return sent_at


def _newest_per_source(facts: list[Fact]) -> list[Fact]:
    by_source: dict[str, list[Fact]] = {}
    for fact in facts:
        by_source.setdefault(fact.source_type, []).append(fact)
    return [max(group, key=_comparable_sent_at) for group in by_source.values()]


def _safer_fact(facts: list[Fact], base_event: FinancialEvent) -> Fact:
    """Step 4: pick whichever candidate does not overstate available cash."""

    def is_safe(fact: Fact) -> bool:
        implies_uncounted = fact.kind == "cancel_event" or (
            fact.amended_status is not None and fact.amended_status != "settled"
        )
        if base_event.direction == "credit":
            # Safer to NOT count a credit until it is confirmed settled.
            return implies_uncounted
        # Safer to keep a debit reserved rather than drop the obligation.
        return not implies_uncounted

    safe = [f for f in facts if is_safe(f)]
    return safe[0] if safe else facts[0]


def _resolve_conflict(facts: list[Fact], base_event: FinancialEvent) -> Optional[Fact]:
    """Reduce every fact targeting one event down to a single winner, per §6.3."""
    if len(facts) == 1:
        winner = facts[0]
    else:
        # Step 1: explicit cancellation/amendment beats a mere confirmation.
        explicit = [f for f in facts if _is_explicit(f)]
        pool = explicit if explicit else facts

        # Step 2: newer record wins within each source; if that leaves one
        # candidate, it is the winner.
        pool = _newest_per_source(pool)
        if len(pool) == 1:
            winner = pool[0]
        else:
            # Step 3: prefer whichever candidate implies `settled`.
            settled = [f for f in pool if f.amended_status == "settled"]
            if settled:
                winner = settled[0]
            else:
                # Step 4: financially safer interpretation.
                winner = _safer_fact(pool, base_event)

    return None if winner.kind == "confirm_event" else winner


def _apply_fact(base_event: FinancialEvent, fact: Fact) -> FinancialEvent:
    if fact.kind == "cancel_event":
        return replace(base_event, status="cancelled")
    updates: dict[str, object] = {}
    if fact.amended_amount is not None:
        updates["amount"] = fact.amended_amount
    if fact.amended_status is not None:
        updates["status"] = fact.amended_status
    if fact.amended_settlement_date is not None:
        updates["settlement_date"] = fact.amended_settlement_date
    return replace(base_event, **updates) if updates else base_event


def normalize_events(
    events: list[FinancialEvent], facts: list[Fact] = ()
) -> list[FinancialEvent]:
    """Build one clean, chronological timeline from raw events + optional facts."""
    working: dict[str, FinancialEvent] = {
        e.event_id: e for e in events if e.status not in EXCLUDED_STATUSES
    }

    facts_by_target: dict[str, list[Fact]] = {}
    new_events: list[FinancialEvent] = []
    for fact in facts:
        if fact.kind == "new_event":
            if fact.new_event is not None:
                new_events.append(fact.new_event)
            continue
        if not fact.target_event_id:
            logger.info(
                "event_normalizer: dropping fact with no target event and no "
                "new_event (kind=%s, message=%s) — no safe way to attach it",
                fact.kind,
                fact.source_message_id,
            )
            continue
        facts_by_target.setdefault(fact.target_event_id, []).append(fact)

    for event_id, target_facts in facts_by_target.items():
        base_event = working.get(event_id)
        if base_event is None:
            # Target was excluded already (cancelled/failed) or never existed;
            # an amendment can't resurrect it. Explicit cancellation wins first (§6.3).
            logger.info(
                "event_normalizer: dropping fact(s) for %s — event is absent or "
                "already excluded",
                event_id,
            )
            continue
        winning_fact = _resolve_conflict(target_facts, base_event)
        if winning_fact is not None:
            working[event_id] = _apply_fact(base_event, winning_fact)

    timeline = [e for e in working.values() if e.status not in EXCLUDED_STATUSES]
    timeline.extend(e for e in new_events if e.status not in EXCLUDED_STATUSES)
    timeline.sort(key=lambda e: (e.settlement_date or e.event_date or date.min, e.event_id))
    return timeline
