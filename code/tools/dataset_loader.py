"""Load every dataset CSV once into validated Pydantic models.

Blank cells become None, never zero -- a blank `amount` means the value must be
recovered from a linked receipt image, which is a very different thing from an
event that costs nothing.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from functools import cached_property
from pathlib import Path

from validators.schemas import (
    ExchangeRate,
    FinancialEvent,
    FinancialProfile,
    ImageRef,
    Message,
    PaymentOption,
    RequestRow,
)

TRUE_VALUES = {"true", "yes", "1", "y", "t"}


def _text(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _opt(row: dict[str, str], key: str) -> str | None:
    value = _text(row, key)
    return value or None


def _num(row: dict[str, str], key: str) -> float | None:
    value = _text(row, key)
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _int(row: dict[str, str], key: str) -> int | None:
    value = _num(row, key)
    return int(value) if value is not None else None


def _day(row: dict[str, str], key: str) -> date | None:
    value = _text(row, key)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _pipe_list(row: dict[str, str], key: str) -> list[str]:
    value = _text(row, key)
    return [part.strip() for part in value.split("|") if part.strip()] if value else []


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class DatasetLoader:
    """Reads dataset/*.csv and indexes rows for per-request retrieval."""

    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir

    # ---- requests ----------------------------------------------------------

    @cached_property
    def requests(self) -> list[RequestRow]:
        return [self._request(row) for row in _read(self.dataset_dir / "requests.csv")]

    @cached_property
    def sample_requests(self) -> list[dict[str, str]]:
        """Kept as raw dicts: they carry the completed output columns too."""
        return _read(self.dataset_dir / "sample_requests.csv")

    @staticmethod
    def _request(row: dict[str, str]) -> RequestRow:
        return RequestRow(
            request_id=_text(row, "request_id"),
            user_id=_text(row, "user_id"),
            request_date=_day(row, "request_date") or date.min,
            request_type=_text(row, "request_type"),
            requested_amount=_num(row, "requested_amount") or 0.0,
            desired_completion_date=(
                _day(row, "desired_completion_date")
                or _day(row, "request_date")
                or date.min
            ),
            allows_partial_payment=_text(row, "allows_partial_payment").lower()
            in TRUE_VALUES,
            request_text=_text(row, "request_text"),
        )

    # ---- profiles ----------------------------------------------------------

    @cached_property
    def profiles(self) -> dict[str, FinancialProfile]:
        profiles: dict[str, FinancialProfile] = {}
        for row in _read(self.dataset_dir / "financial_profiles.csv"):
            profile = FinancialProfile(
                user_id=_text(row, "user_id"),
                home_currency=_text(row, "home_currency"),
                current_available_balance=_num(row, "current_available_balance") or 0.0,
                minimum_balance_to_keep=_num(row, "minimum_balance_to_keep") or 0.0,
                financial_priorities=_pipe_list(row, "financial_priorities"),
                expense_categories_to_protect=_pipe_list(
                    row, "expense_categories_to_protect"
                ),
                expense_categories_user_is_willing_to_reduce=_pipe_list(
                    row, "expense_categories_user_is_willing_to_reduce"
                ),
                expense_categories_user_is_willing_to_stop=_pipe_list(
                    row, "expense_categories_user_is_willing_to_stop"
                ),
                payment_methods_user_will_consider=_pipe_list(
                    row, "payment_methods_user_will_consider"
                ),
                max_installment_months=_int(row, "max_installment_months"),
            )
            profiles[profile.user_id] = profile
        return profiles

    # ---- events ------------------------------------------------------------

    @cached_property
    def events_by_user(self) -> dict[str, list[FinancialEvent]]:
        grouped: dict[str, list[FinancialEvent]] = defaultdict(list)
        for row in _read(self.dataset_dir / "financial_events.csv"):
            event = FinancialEvent(
                event_id=_text(row, "event_id"),
                user_id=_text(row, "user_id"),
                event_type=_text(row, "event_type"),
                description=_text(row, "description"),
                category=_text(row, "category"),
                direction=_text(row, "direction") or "debit",
                amount=_num(row, "amount"),
                currency=_opt(row, "currency"),
                event_date=_day(row, "event_date") or date.min,
                settlement_date=_day(row, "settlement_date"),
                status=_text(row, "status") or "settled",
                linked_event_id=_opt(row, "linked_event_id"),
                flexibility=_text(row, "flexibility") or "fixed",
                minimum_allowed_amount=_num(row, "minimum_allowed_amount"),
            )
            grouped[event.user_id].append(event)
        for events in grouped.values():
            events.sort(key=lambda e: (e.cash_date, e.event_id))
        return dict(grouped)

    # ---- evidence ----------------------------------------------------------

    @cached_property
    def messages_by_user(self) -> dict[str, list[Message]]:
        grouped: dict[str, list[Message]] = defaultdict(list)
        for row in _read(self.dataset_dir / "messages.csv"):
            message = Message(
                message_id=_text(row, "message_id"),
                user_id=_text(row, "user_id"),
                request_id=_opt(row, "request_id"),
                related_event_id=_opt(row, "related_event_id"),
                sent_at=_day(row, "sent_at") or date.min,
                source_type=_text(row, "source_type"),
                message_text=_text(row, "message_text"),
            )
            grouped[message.user_id].append(message)
        for messages in grouped.values():
            messages.sort(key=lambda m: (m.sent_at, m.message_id))
        return dict(grouped)

    @cached_property
    def images_by_user(self) -> dict[str, list[ImageRef]]:
        grouped: dict[str, list[ImageRef]] = defaultdict(list)
        for row in _read(self.dataset_dir / "images.csv"):
            ref = ImageRef(
                image_id=_text(row, "image_id"),
                user_id=_text(row, "user_id"),
                request_id=_opt(row, "request_id"),
                related_event_id=_opt(row, "related_event_id"),
            )
            grouped[ref.user_id].append(ref)
        return dict(grouped)

    @cached_property
    def images_by_event(self) -> dict[str, ImageRef]:
        return {
            ref.related_event_id: ref
            for refs in self.images_by_user.values()
            for ref in refs
            if ref.related_event_id
        }

    # ---- options and rates -------------------------------------------------

    @cached_property
    def options_by_request(self) -> dict[str, list[PaymentOption]]:
        grouped: dict[str, list[PaymentOption]] = defaultdict(list)
        for row in _read(self.dataset_dir / "request_payment_options.csv"):
            option = PaymentOption(
                payment_option_id=_text(row, "payment_option_id"),
                request_id=_text(row, "request_id"),
                payment_method=_text(row, "payment_method"),
                payment_amount=_num(row, "payment_amount") or 0.0,
                number_of_payments=_int(row, "number_of_payments") or 1,
                first_payment_date=_day(row, "first_payment_date") or date.min,
                payment_frequency_days=_int(row, "payment_frequency_days"),
                financing_fee=_num(row, "financing_fee") or 0.0,
                total_payable_amount=_num(row, "total_payable_amount") or 0.0,
            )
            grouped[option.request_id].append(option)
        for options in grouped.values():
            options.sort(key=lambda o: o.payment_option_id)
        return dict(grouped)

    @cached_property
    def exchange_rates(self) -> list[ExchangeRate]:
        return [
            ExchangeRate(
                rate_date=_day(row, "rate_date") or date.min,
                from_currency=_text(row, "from_currency"),
                to_currency=_text(row, "to_currency"),
                rate=_num(row, "rate") or 1.0,
            )
            for row in _read(self.dataset_dir / "exchange_rates.csv")
        ]
