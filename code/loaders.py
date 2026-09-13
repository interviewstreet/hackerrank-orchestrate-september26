"""Module 1: loaders.

Reads every CSV in `dataset/` and builds fast lookup structures indexed by
`user_id` / `request_id` / `event_id`, as described in PLAN.md step 1.

Deterministic, stdlib-only (csv + dataclasses). No LLM calls happen here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional


def _parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_datetime(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_float(value: str) -> Optional[float]:
    value = (value or "").strip()
    if not value:
        return None
    return float(value)


def _parse_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    return int(float(value))


def _parse_bool(value: str) -> bool:
    return (value or "").strip().lower() == "true"


def _parse_pipe_list(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    return [item for item in value.split("|") if item]


@dataclass(frozen=True)
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: Optional[int]


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: Optional[float]
    currency: str
    event_date: Optional[date]
    settlement_date: Optional[date]
    status: str
    linked_event_id: Optional[str]
    flexibility: str
    minimum_allowed_amount: Optional[float]


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: float


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: Optional[date]
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class SampleRequest(Request):
    amount_safe_to_pay: Optional[float] = None
    affordability_status: str = ""
    recommended_payment_method: str = ""
    payment_plan: str = ""
    earliest_date_for_full_payment: Optional[date] = None
    spending_changes_needed: str = ""
    decision_explanation: str = ""


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: float
    number_of_payments: Optional[int]
    first_payment_date: Optional[date]
    payment_frequency_days: Optional[int]
    financing_fee: Optional[float]
    total_payable_amount: float


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: Optional[datetime]
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageRef:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]

    def path(self, dataset_dir: Path) -> Path:
        return dataset_dir / "media" / "images" / f"{self.image_id}.png"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_financial_profiles(dataset_dir: Path) -> dict[str, FinancialProfile]:
    by_user: dict[str, FinancialProfile] = {}
    for row in _read_csv(dataset_dir / "financial_profiles.csv"):
        profile = FinancialProfile(
            user_id=row["user_id"],
            home_currency=row["home_currency"],
            current_available_balance=_parse_float(row["current_available_balance"]),
            minimum_balance_to_keep=_parse_float(row["minimum_balance_to_keep"]),
            financial_priorities=_parse_pipe_list(row["financial_priorities"]),
            expense_categories_to_protect=_parse_pipe_list(row["expense_categories_to_protect"]),
            expense_categories_user_is_willing_to_reduce=_parse_pipe_list(
                row["expense_categories_user_is_willing_to_reduce"]
            ),
            expense_categories_user_is_willing_to_stop=_parse_pipe_list(
                row["expense_categories_user_is_willing_to_stop"]
            ),
            payment_methods_user_will_consider=_parse_pipe_list(
                row["payment_methods_user_will_consider"]
            ),
            max_installment_months=_parse_int(row["max_installment_months"]),
        )
        by_user[profile.user_id] = profile
    return by_user


def load_financial_events(dataset_dir: Path) -> list[FinancialEvent]:
    events: list[FinancialEvent] = []
    for row in _read_csv(dataset_dir / "financial_events.csv"):
        events.append(
            FinancialEvent(
                event_id=row["event_id"],
                user_id=row["user_id"],
                event_type=row["event_type"],
                description=row["description"],
                category=row["category"],
                direction=row["direction"],
                amount=_parse_float(row["amount"]),
                currency=row["currency"],
                event_date=_parse_date(row["event_date"]),
                settlement_date=_parse_date(row["settlement_date"]),
                status=row["status"],
                linked_event_id=row["linked_event_id"] or None,
                flexibility=row["flexibility"],
                minimum_allowed_amount=_parse_float(row["minimum_allowed_amount"]),
            )
        )
    return events


def load_exchange_rates(dataset_dir: Path) -> list[ExchangeRate]:
    rates: list[ExchangeRate] = []
    for row in _read_csv(dataset_dir / "exchange_rates.csv"):
        rates.append(
            ExchangeRate(
                rate_date=_parse_date(row["rate_date"]),
                from_currency=row["from_currency"],
                to_currency=row["to_currency"],
                rate=_parse_float(row["rate"]),
            )
        )
    return rates


def load_requests(dataset_dir: Path) -> dict[str, Request]:
    by_id: dict[str, Request] = {}
    for row in _read_csv(dataset_dir / "requests.csv"):
        req = Request(
            request_id=row["request_id"],
            user_id=row["user_id"],
            request_date=_parse_date(row["request_date"]),
            request_type=row["request_type"],
            requested_amount=_parse_float(row["requested_amount"]),
            desired_completion_date=_parse_date(row["desired_completion_date"]),
            allows_partial_payment=_parse_bool(row["allows_partial_payment"]),
            request_text=row["request_text"],
        )
        by_id[req.request_id] = req
    return by_id


def load_sample_requests(dataset_dir: Path) -> dict[str, SampleRequest]:
    by_id: dict[str, SampleRequest] = {}
    path = dataset_dir / "sample_requests.csv"
    if not path.exists():
        return by_id
    for row in _read_csv(path):
        sample = SampleRequest(
            request_id=row["request_id"],
            user_id=row["user_id"],
            request_date=_parse_date(row["request_date"]),
            request_type=row["request_type"],
            requested_amount=_parse_float(row["requested_amount"]),
            desired_completion_date=_parse_date(row["desired_completion_date"]),
            allows_partial_payment=_parse_bool(row["allows_partial_payment"]),
            request_text=row["request_text"],
            amount_safe_to_pay=_parse_float(row["amount_safe_to_pay"]),
            affordability_status=row["affordability_status"],
            recommended_payment_method=row["recommended_payment_method"],
            payment_plan=row["payment_plan"],
            earliest_date_for_full_payment=_parse_date(row["earliest_date_for_full_payment"]),
            spending_changes_needed=row["spending_changes_needed"],
            decision_explanation=row["decision_explanation"],
        )
        by_id[sample.request_id] = sample
    return by_id


def load_payment_options(dataset_dir: Path) -> dict[str, list[PaymentOption]]:
    by_request: dict[str, list[PaymentOption]] = {}
    for row in _read_csv(dataset_dir / "request_payment_options.csv"):
        option = PaymentOption(
            payment_option_id=row["payment_option_id"],
            request_id=row["request_id"],
            payment_method=row["payment_method"],
            payment_amount=_parse_float(row["payment_amount"]),
            number_of_payments=_parse_int(row["number_of_payments"]),
            first_payment_date=_parse_date(row["first_payment_date"]),
            payment_frequency_days=_parse_int(row["payment_frequency_days"]),
            financing_fee=_parse_float(row["financing_fee"]),
            total_payable_amount=_parse_float(row["total_payable_amount"]),
        )
        by_request.setdefault(option.request_id, []).append(option)
    return by_request


def load_messages(dataset_dir: Path) -> list[Message]:
    messages: list[Message] = []
    for row in _read_csv(dataset_dir / "messages.csv"):
        messages.append(
            Message(
                message_id=row["message_id"],
                user_id=row["user_id"],
                request_id=row["request_id"] or None,
                related_event_id=row["related_event_id"] or None,
                sent_at=_parse_datetime(row["sent_at"]),
                source_type=row["source_type"],
                message_text=row["message_text"],
            )
        )
    return messages


def load_images(dataset_dir: Path) -> list[ImageRef]:
    images: list[ImageRef] = []
    for row in _read_csv(dataset_dir / "images.csv"):
        images.append(
            ImageRef(
                image_id=row["image_id"],
                user_id=row["user_id"],
                request_id=row["request_id"] or None,
                related_event_id=row["related_event_id"] or None,
            )
        )
    return images


@dataclass
class Dataset:
    dataset_dir: Path

    profiles_by_user: dict[str, FinancialProfile]

    events: list[FinancialEvent]
    events_by_id: dict[str, FinancialEvent]
    events_by_user: dict[str, list[FinancialEvent]]

    exchange_rates: list[ExchangeRate]
    rates_by_pair: dict[tuple[str, str], list[ExchangeRate]]

    requests_by_id: dict[str, Request]
    sample_requests_by_id: dict[str, SampleRequest]

    payment_options_by_request: dict[str, list[PaymentOption]]

    messages: list[Message]
    messages_by_user: dict[str, list[Message]]
    messages_by_request: dict[str, list[Message]]
    messages_by_event: dict[str, list[Message]]

    images: list[ImageRef]
    images_by_request: dict[str, list[ImageRef]]
    images_by_event: dict[str, ImageRef]


def load_dataset(dataset_dir: str | Path) -> Dataset:
    """Load and index every CSV under `dataset_dir` (module 1 entry point)."""
    dataset_dir = Path(dataset_dir)

    events = load_financial_events(dataset_dir)
    events_by_id: dict[str, FinancialEvent] = {}
    events_by_user: dict[str, list[FinancialEvent]] = {}
    for event in events:
        events_by_id[event.event_id] = event
        events_by_user.setdefault(event.user_id, []).append(event)

    exchange_rates = load_exchange_rates(dataset_dir)
    rates_by_pair: dict[tuple[str, str], list[ExchangeRate]] = {}
    for rate in exchange_rates:
        rates_by_pair.setdefault((rate.from_currency, rate.to_currency), []).append(rate)
    for pair_rates in rates_by_pair.values():
        pair_rates.sort(key=lambda r: r.rate_date)

    messages = load_messages(dataset_dir)
    messages_by_user: dict[str, list[Message]] = {}
    messages_by_request: dict[str, list[Message]] = {}
    messages_by_event: dict[str, list[Message]] = {}
    for message in messages:
        messages_by_user.setdefault(message.user_id, []).append(message)
        if message.request_id:
            messages_by_request.setdefault(message.request_id, []).append(message)
        if message.related_event_id:
            messages_by_event.setdefault(message.related_event_id, []).append(message)

    images = load_images(dataset_dir)
    images_by_request: dict[str, list[ImageRef]] = {}
    images_by_event: dict[str, ImageRef] = {}
    for image in images:
        if image.request_id:
            images_by_request.setdefault(image.request_id, []).append(image)
        if image.related_event_id:
            images_by_event[image.related_event_id] = image

    return Dataset(
        dataset_dir=dataset_dir,
        profiles_by_user=load_financial_profiles(dataset_dir),
        events=events,
        events_by_id=events_by_id,
        events_by_user=events_by_user,
        exchange_rates=exchange_rates,
        rates_by_pair=rates_by_pair,
        requests_by_id=load_requests(dataset_dir),
        sample_requests_by_id=load_sample_requests(dataset_dir),
        payment_options_by_request=load_payment_options(dataset_dir),
        messages=messages,
        messages_by_user=messages_by_user,
        messages_by_request=messages_by_request,
        messages_by_event=messages_by_event,
        images=images,
        images_by_request=images_by_request,
        images_by_event=images_by_event,
    )
