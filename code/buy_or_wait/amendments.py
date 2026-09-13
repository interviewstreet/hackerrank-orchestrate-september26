"""Narrow, deterministic extraction of high-confidence message amendments."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .load import LoadedDataset
from .models import EvidenceAmendment, Event, Message

_SALARY_CHANGE = re.compile(r"monthly salary has increased to (?P<currency>EUR|IDR|INR|USD|ZAR) (?P<amount>[0-9]+(?:\.[0-9]+)?).+?applies from (?P<date>\d{4}-\d{2}-\d{2})", re.I)

@dataclass(frozen=True)
class AmendmentReport:
    amendments: tuple[EvidenceAmendment, ...]
    rejected_message_ids: tuple[str, ...]
    linked_without_safe_amendment: tuple[str, ...]
    conflicts: int

class EvidenceAmendmentEngine:
    """Accepts only explicit employer salary increases with amount/date/stream link.

    All other observed templates are recorded as rejected rather than guessed.
    """
    def __init__(self, dataset: LoadedDataset) -> None:
        self.dataset = dataset
        self.events_by_user: dict[str, tuple[Event, ...]] = {}
        for user_id in {event.user_id for event in dataset.events}:
            self.events_by_user[user_id] = tuple(event for event in dataset.events if event.user_id == user_id)

    def inspect(self) -> AmendmentReport:
        candidates: list[EvidenceAmendment] = []
        rejected: list[str] = []
        linked_rejected: list[str] = []
        for message in self.dataset.messages:
            amendment = self._parse_salary_increase(message)
            if amendment is None:
                rejected.append(message.message_id)
                if message.related_event_id:
                    linked_rejected.append(message.message_id)
            else:
                candidates.append(amendment)
        # Same stream/effective date conflicts: newest message from the source wins.
        winners: dict[tuple[str, date], EvidenceAmendment] = {}
        conflicts = 0
        sent_at = {message.message_id: message.sent_at for message in self.dataset.messages}
        for candidate in candidates:
            key = (candidate.affected_event_id, candidate.effective_date)
            old = winners.get(key)
            if old is None or sent_at[candidate.source_message_id] > sent_at[old.source_message_id]:
                if old is not None: conflicts += 1
                winners[key] = candidate
            else:
                conflicts += 1
        return AmendmentReport(tuple(sorted(winners.values(), key=lambda item: item.amendment_id)), tuple(rejected), tuple(linked_rejected), conflicts)

    def for_user(self, user_id: str) -> tuple[EvidenceAmendment, ...]:
        return tuple(item for item in self.inspect().amendments if self._event(item.affected_event_id).user_id == user_id)

    def _event(self, event_id: str) -> Event:
        return next(event for event in self.dataset.events if event.event_id == event_id)

    def _parse_salary_increase(self, message: Message) -> EvidenceAmendment | None:
        if message.source_type != "employer":
            return None
        match = _SALARY_CHANGE.search(message.message_text)
        if match is None:
            return None
        effective = date.fromisoformat(match["date"])
        amount = Decimal(match["amount"])
        streams = [event for event in self.events_by_user.get(message.user_id, ()) if event.event_type == "income" and event.category == "salary" and event.direction == "credit" and event.currency == match["currency"] and event.status == "settled" and event.settlement_date and event.settlement_date < effective]
        # A single latest salary stream is the required deterministic linkage.
        if not streams:
            return None
        latest_date = max(event.settlement_date for event in streams if event.settlement_date)
        latest = [event for event in streams if event.settlement_date == latest_date]
        if len(latest) != 1:
            return None
        event = latest[0]
        return EvidenceAmendment(f"amendment:{message.message_id}", "salary_amount_change", message.message_id, event.event_id, effective, event.amount, amount, event.status, event.status, "Employer explicitly supplied a new salary amount and effective date.")
