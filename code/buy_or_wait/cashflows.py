"""Normalize validated events into conservative, explainable baseline cash flows."""

from __future__ import annotations

from collections import defaultdict
import calendar
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .load import ExchangeRate, LoadedDataset
from .models import CashFlow, Event, MessageAmendment, Profile, Request
from .amendments import EvidenceAmendment, EvidenceAmendmentEngine


class CashFlowNormalizationError(ValueError):
    """Raised when a qualifying event cannot be safely normalized."""


class ExchangeRateUnavailableError(CashFlowNormalizationError):
    """Raised when supplied fixed rates do not contain a required conversion."""


class CashFlowNormalizer:
    """Converts only eligible, evidenced events into home-currency flows.

    The current balance is a request-date snapshot, so only events dated on or
    after the request date are direct flows. Earlier settled events are used
    solely as evidence for the deliberately strict recurrence detector.
    """

    def __init__(self, dataset: LoadedDataset) -> None:
        self.dataset = dataset
        self.profiles = {profile.user_id: profile for profile in dataset.profiles}
        self.events_by_user: dict[str, tuple[Event, ...]] = defaultdict(tuple)
        grouped: dict[str, list[Event]] = defaultdict(list)
        for event in dataset.events:
            grouped[event.user_id].append(event)
        self.events_by_user = {user_id: tuple(events) for user_id, events in grouped.items()}
        self.rates = {(rate.rate_date, rate.from_currency, rate.to_currency): rate.rate for rate in dataset.exchange_rates}
        self.events_by_id = {event.event_id: event for event in dataset.events}
        self.amendment_engine = EvidenceAmendmentEngine(dataset)
        amendments_by_user: dict[str, list[EvidenceAmendment]] = defaultdict(list)
        for amendment in self.amendment_engine.inspect().amendments:
            amendments_by_user[self.events_by_id[amendment.affected_event_id].user_id].append(amendment)
        self.amendments_by_user = {user_id: tuple(amendments) for user_id, amendments in amendments_by_user.items()}
        self.superseded_duplicate_ids: set[str] = set()
        for later in dataset.events:
            if not later.linked_event_id:
                continue
            earlier = self.events_by_id.get(later.linked_event_id)
            if earlier and self._same_cash_record(earlier, later):
                self.superseded_duplicate_ids.add(earlier.event_id)

    def amendments_for(self, request: Request) -> tuple[MessageAmendment, ...]:
        """Expose recognized evidence without fabricating a cash flow from prose.

        Messages are only considered amendments where they explicitly confirm
        existing status semantics. Amount/date changes without an unambiguous
        event link are intentionally left for a later evidence-normalization
        task rather than guessed here.
        """
        amendments: list[MessageAmendment] = []
        for message in self.dataset.messages:
            if message.user_id != request.user_id:
                continue
            text = message.message_text.lower()
            if message.related_event_id and "has not reached your account" in text:
                amendments.append(MessageAmendment(message.message_id, message.related_event_id, "pending_credit_unavailable", "Pending credit remains excluded."))
            elif message.related_event_id and "previous debit attempt failed" in text:
                amendments.append(MessageAmendment(message.message_id, message.related_event_id, "failed_debit_unsettled", "Failed event is not cash; no replacement date or amount is invented."))
            elif message.related_event_id and "no cash proceeds" in text:
                amendments.append(MessageAmendment(message.message_id, message.related_event_id, "non_cash_valuation", "Investment valuation remains excluded from cash."))
        return tuple(amendments)

    def normalize(self, request: Request, *, horizon_days: int = 90) -> tuple[CashFlow, ...]:
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        profile = self.profiles[request.user_id]
        end_date = request.request_date + timedelta(days=horizon_days - 1)
        direct: list[CashFlow] = []
        direct_event_ids: set[str] = set()
        for event in self.events_by_user.get(request.user_id, ()):
            if self._is_superseded_duplicate(event):
                continue
            flow_date = self._cash_date(event)
            if flow_date is None or not request.request_date <= flow_date <= end_date:
                continue
            flow = self._event_to_flow(event, profile, flow_date, sequence=len(direct))
            if flow is not None:
                direct.append(flow)
                direct_event_ids.add(event.event_id)
        recurring = self._expand_recurring(request, profile, end_date, direct_event_ids, len(direct))
        return tuple(sorted(direct + recurring, key=lambda flow: (flow.flow_date, flow.sequence, flow.source_event_id or "")))

    def _is_superseded_duplicate(self, event: Event) -> bool:
        """Drop only an exact linked duplicate, never an actual refund/sale lifecycle."""
        return event.event_id in self.superseded_duplicate_ids

    def _same_cash_record(self, earlier: Event, later: Event) -> bool:
        return earlier.direction == later.direction and earlier.amount == later.amount and earlier.currency == later.currency and self._cash_date(earlier) == self._cash_date(later)

    @staticmethod
    def _cash_date(event: Event) -> date | None:
        # Settlement date is authoritative for cash timing when supplied.
        return event.settlement_date or event.event_date

    def _event_to_flow(self, event: Event, profile: Profile, flow_date: date, *, sequence: int, is_recurring: bool = False) -> CashFlow | None:
        if event.status in {"failed", "cancelled", "unrealized"}:
            return None
        if event.direction == "non_cash":
            return None
        # Pending credits are explicitly unavailable. Pending debits remain reserved.
        if event.status == "pending" and event.direction == "credit":
            return None
        amount, rate = self._convert(event.amount, event.currency, profile.home_currency, flow_date, event.event_id)
        return CashFlow(flow_date, amount, profile.home_currency, event.direction, event.event_id, event.description, is_recurring=is_recurring, original_currency=event.currency, conversion_rate=rate, sequence=sequence)

    def _convert(self, amount: Decimal, source_currency: str, home_currency: str, rate_date: date, event_id: str) -> tuple[Decimal, Decimal | None]:
        if source_currency == home_currency:
            return amount, None
        rate = self.rates.get((rate_date, source_currency, home_currency))
        if rate is None:
            raise ExchangeRateUnavailableError(f"{event_id}: no supplied FX rate for {source_currency}->{home_currency} on {rate_date.isoformat()}")
        return amount * rate, rate

    def _expand_recurring(self, request: Request, profile: Profile, end_date: date, direct_event_ids: set[str], sequence_start: int) -> list[CashFlow]:
        result: list[CashFlow] = []
        groups: dict[tuple[object, ...], list[Event]] = defaultdict(list)
        for event in self.events_by_user.get(request.user_id, ()):
            cash_date = self._cash_date(event)
            if cash_date is None or cash_date >= request.request_date:
                continue
            if event.status != "settled" or event.direction == "non_cash":
                continue
            groups[(event.event_type, event.description, event.category, event.direction, event.currency, event.amount)].append(event)
        sequence = sequence_start
        for events in groups.values():
            events.sort(key=lambda event: self._cash_date(event) or date.min)
            interval = self._established_interval(events)
            if interval is None:
                continue
            source = events[-1]
            amendments = [item for item in self.amendments_by_user.get(request.user_id, ()) if item.affected_event_id == source.event_id]
            monthly = 27 <= interval <= 32
            anchor_day = (self._cash_date(source) or request.request_date).day
            next_date = self._next_recurrence_date(
                self._cash_date(source) or request.request_date, interval, monthly, anchor_day
            )
            while next_date <= end_date:
                if next_date >= request.request_date and source.event_id not in direct_event_ids:
                    # Never invent a future conversion.  A recurrence can be
                    # evidenced independently of its FX rate, but it is not a
                    # usable home-currency cash flow on a date without the
                    # supplied directional rate.
                    if (source.currency != profile.home_currency and
                            (next_date, source.currency, profile.home_currency) not in self.rates):
                        break
                    flow = self._event_to_flow(source, profile, next_date, sequence=sequence, is_recurring=True)
                    if flow is not None:
                        applicable = [item for item in amendments if item.effective_date <= next_date]
                        if applicable:
                            amendment = max(applicable, key=lambda item: item.effective_date)
                            flow = CashFlow(flow.flow_date, amendment.new_amount or flow.amount, flow.currency, flow.direction, flow.source_event_id, flow.description, flow.is_recurring, True, flow.original_currency, flow.conversion_rate, flow.sequence)
                        result.append(flow)
                        sequence += 1
                next_date = self._next_recurrence_date(next_date, interval, monthly, anchor_day)
        return result

    @staticmethod
    def _next_recurrence_date(current: date, interval: int, monthly: bool, anchor_day: int) -> date:
        """Advance a monthly series by calendar month, not an arbitrary day gap.

        The detector permits 27--32-day gaps because month lengths differ.  Once
        that cadence is established, repeatedly adding its median gap drifts a
        payment anchored on (for example) the 15th.  Weekly and biweekly series
        retain their evidenced fixed-day interval.  Foreign-currency series are
        allowed here as well, but ``_event_to_flow`` still fails closed unless an
        exact supplied FX rate exists for every projected occurrence.
        """
        if not monthly:
            return current + timedelta(days=interval)
        year = current.year + (current.month == 12)
        month = 1 if current.month == 12 else current.month + 1
        return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))

    @staticmethod
    def _established_interval(events: list[Event]) -> int | None:
        """Require three same-amount, same-description settled observations.

        Supported cadences are weekly, biweekly, and monthly. Both observed
        intervals must be close to the median; this deliberately rejects a
        one-off or irregular spending sequence.
        """
        if len(events) < 3:
            return None
        dates = [CashFlowNormalizer._cash_date(event) for event in events]
        intervals = [(later - earlier).days for earlier, later in zip(dates, dates[1:]) if earlier and later]
        if len(intervals) < 2:
            return None
        cadence = int(median(intervals))
        if not any(low <= cadence <= high for low, high in ((6, 8), (13, 15), (27, 32))):
            return None
        if any(abs(value - cadence) > 2 for value in intervals):
            return None
        return cadence
