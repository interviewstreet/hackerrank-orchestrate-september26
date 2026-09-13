"""Strict CSV loader for every participant-facing dataset file."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, cast

from .images import IMAGE_EVIDENCE_AMOUNTS
from .models import Event, ImageLink, Message, PaymentOption, Profile, Request

VALID_CURRENCIES = {"EUR", "IDR", "INR", "USD", "ZAR"}
VALID_EVENT_TYPES = {"expense", "debt_payment", "subscription", "income", "refund", "investment_purchase", "investment_valuation", "investment_sale"}
VALID_DIRECTIONS = {"debit", "credit", "non_cash"}
VALID_EVENT_STATUSES = {"settled", "cancelled", "pending", "scheduled", "failed", "unrealized"}
VALID_FLEXIBILITY = {"fixed", "stoppable", "reducible", "reducible_or_stoppable"}
VALID_REQUEST_TYPES = {"purchase", "travel", "education", "family_transfer", "debt_repayment", "investment", "housing", "emergency_expense", "other"}
VALID_PAYMENT_METHODS = {"full_payment", "partial_payment", "installments"}
VALID_OPTION_METHODS = {"full_payment", "installments"}
VALID_MESSAGE_SOURCES = {"employer", "service_provider", "bank", "merchant", "financial_service"}

HEADERS = {
    "requests.csv": ("request_id", "user_id", "request_date", "request_type", "requested_amount", "desired_completion_date", "allows_partial_payment", "request_text"),
    "sample_requests.csv": ("request_id", "user_id", "request_date", "request_type", "requested_amount", "desired_completion_date", "allows_partial_payment", "request_text", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"),
    "financial_profiles.csv": ("user_id", "home_currency", "current_available_balance", "minimum_balance_to_keep", "financial_priorities", "expense_categories_to_protect", "expense_categories_user_is_willing_to_reduce", "expense_categories_user_is_willing_to_stop", "payment_methods_user_will_consider", "max_installment_months"),
    "financial_events.csv": ("event_id", "user_id", "event_type", "description", "category", "direction", "amount", "currency", "event_date", "settlement_date", "status", "linked_event_id", "flexibility", "minimum_allowed_amount"),
    "exchange_rates.csv": ("rate_date", "from_currency", "to_currency", "rate"),
    "request_payment_options.csv": ("payment_option_id", "request_id", "payment_method", "payment_amount", "number_of_payments", "first_payment_date", "payment_frequency_days", "financing_fee", "total_payable_amount"),
    "messages.csv": ("message_id", "user_id", "request_id", "related_event_id", "sent_at", "source_type", "message_text"),
    "images.csv": ("image_id", "user_id", "request_id", "related_event_id"),
    "output.csv": ("request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"),
}


class DatasetValidationError(ValueError):
    """Raised with a complete, human-readable list of dataset validation errors."""


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class LoadedDataset:
    requests: tuple[Request, ...]
    sample_requests: tuple[Request, ...]
    profiles: tuple[Profile, ...]
    events: tuple[Event, ...]
    exchange_rates: tuple[ExchangeRate, ...]
    payment_options: tuple[PaymentOption, ...]
    messages: tuple[Message, ...]
    images: tuple[ImageLink, ...]
    output_template_request_ids: tuple[str, ...]

    def row_counts(self) -> dict[str, int]:
        return {
            "requests.csv": len(self.requests), "sample_requests.csv": len(self.sample_requests),
            "financial_profiles.csv": len(self.profiles), "financial_events.csv": len(self.events),
            "exchange_rates.csv": len(self.exchange_rates), "request_payment_options.csv": len(self.payment_options),
            "messages.csv": len(self.messages), "images.csv": len(self.images),
            "output.csv": len(self.output_template_request_ids),
        }


class DatasetLoader:
    def __init__(self, dataset_dir: Path | str) -> None:
        self.dataset_dir = Path(dataset_dir)
        self.errors: list[str] = []

    def load(self) -> LoadedDataset:
        self.errors = []
        tables = {name: self._read_table(name) for name in HEADERS}
        profiles = tuple(self._parse_profiles(tables["financial_profiles.csv"]))
        requests = tuple(self._parse_requests(tables["requests.csv"], "requests.csv"))
        samples = tuple(self._parse_requests(tables["sample_requests.csv"], "sample_requests.csv"))
        self._validate_sample_outputs(tables["sample_requests.csv"])
        images = tuple(self._parse_images(tables["images.csv"]))
        image_event_ids = {image.related_event_id for image in images}
        events = tuple(self._parse_events(tables["financial_events.csv"], image_event_ids))
        rates = tuple(self._parse_rates(tables["exchange_rates.csv"]))
        options = tuple(self._parse_options(tables["request_payment_options.csv"]))
        messages = tuple(self._parse_messages(tables["messages.csv"]))
        output_ids = tuple(row["request_id"] for row in tables["output.csv"])
        self._validate_relationships(profiles, requests, samples, events, options, messages, images, output_ids)
        if self.errors:
            raise DatasetValidationError("Dataset validation failed:\n- " + "\n- ".join(self.errors))
        return LoadedDataset(requests, samples, profiles, events, rates, options, messages, images, output_ids)

    def _read_table(self, filename: str) -> list[dict[str, str]]:
        path = self.dataset_dir / filename
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != HEADERS[filename]:
                    self.errors.append(f"{filename}: header must exactly equal {HEADERS[filename]!r}; got {tuple(reader.fieldnames or ())!r}")
                return list(reader)
        except OSError as exc:
            self.errors.append(f"{filename}: cannot read file: {exc}")
            return []

    def _id(self, row: dict[str, str], field: str, context: str) -> str:
        value = row.get(field, "").strip()
        if not value:
            self.errors.append(f"{context}: required {field} is blank")
        return value

    def _date(self, value: str, context: str, *, required: bool = True) -> date | None:
        value = value.strip()
        if not value:
            if required: self.errors.append(f"{context}: required date is blank")
            return None
        try: return date.fromisoformat(value)
        except ValueError:
            self.errors.append(f"{context}: invalid YYYY-MM-DD date {value!r}")
            return None

    def _decimal(self, value: str, context: str, *, required: bool = True) -> Decimal | None:
        value = value.strip()
        if not value:
            if required: self.errors.append(f"{context}: required monetary value is blank")
            return None
        try:
            amount = Decimal(value)
            if not amount.is_finite(): raise InvalidOperation
            return amount
        except InvalidOperation:
            self.errors.append(f"{context}: invalid Decimal value {value!r}")
            return None

    def _currency(self, value: str, context: str) -> str:
        value = value.strip()
        if value not in VALID_CURRENCIES: self.errors.append(f"{context}: invalid currency {value!r}")
        return value

    def _unique(self, rows: Iterable[object], attribute: str, name: str) -> None:
        seen: set[str] = set()
        for row in rows:
            value = getattr(row, attribute)
            if value in seen: self.errors.append(f"{name}: duplicate {attribute} {value!r}")
            seen.add(value)

    def _parts(self, value: str) -> tuple[str, ...]:
        return tuple(part for part in value.split("|") if part)

    def _parse_profiles(self, rows: list[dict[str, str]]) -> Iterable[Profile]:
        result = []
        for number, row in enumerate(rows, 2):
            c = f"financial_profiles.csv:{number}"
            methods = self._parts(row["payment_methods_user_will_consider"])
            if not methods or set(methods) - VALID_PAYMENT_METHODS: self.errors.append(f"{c}: invalid payment method preferences {methods!r}")
            months = row["max_installment_months"].strip()
            max_months = None
            if months:
                try:
                    max_months = int(months)
                    if max_months <= 0: raise ValueError
                except ValueError: self.errors.append(f"{c}: max_installment_months must be a positive integer or blank")
            result.append(Profile(self._id(row,"user_id",c), cast(str,self._currency(row["home_currency"],c)), self._decimal(row["current_available_balance"],c) or Decimal(0), self._decimal(row["minimum_balance_to_keep"],c) or Decimal(0), self._parts(row["financial_priorities"]), self._parts(row["expense_categories_to_protect"]), self._parts(row["expense_categories_user_is_willing_to_reduce"]), self._parts(row["expense_categories_user_is_willing_to_stop"]), cast(tuple,methods), max_months))
        self._unique(result, "user_id", "financial_profiles.csv")
        return result

    def _parse_requests(self, rows: list[dict[str, str]], filename: str) -> Iterable[Request]:
        result=[]
        for number,row in enumerate(rows,2):
            c=f"{filename}:{number}"; raw=row["allows_partial_payment"].strip()
            if raw not in {"true", "false"}: self.errors.append(f"{c}: allows_partial_payment must be true or false")
            if row["request_type"] not in VALID_REQUEST_TYPES: self.errors.append(f"{c}: invalid request_type {row['request_type']!r}")
            result.append(Request(self._id(row,"request_id",c),self._id(row,"user_id",c),self._date(row["request_date"],c) or date.min,row["request_type"],self._decimal(row["requested_amount"],c) or Decimal(0),self._date(row["desired_completion_date"],c) or date.min,raw == "true",row["request_text"]))
        self._unique(result,"request_id",filename); return result

    def _parse_images(self, rows: list[dict[str, str]]) -> Iterable[ImageLink]:
        result=[ImageLink(self._id(r,"image_id",f"images.csv:{n}"),self._id(r,"user_id",f"images.csv:{n}"),self._id(r,"request_id",f"images.csv:{n}"),self._id(r,"related_event_id",f"images.csv:{n}")) for n,r in enumerate(rows,2)]
        self._unique(result,"image_id","images.csv"); return result

    def _validate_sample_outputs(self, rows: list[dict[str, str]]) -> None:
        """Validate solved-output syntax without treating examples as decision labels."""
        valid_statuses = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
        valid_methods = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
        for number, row in enumerate(rows, 2):
            context = f"sample_requests.csv:{number}"
            self._decimal(row["amount_safe_to_pay"], context)
            if row["affordability_status"] not in valid_statuses:
                self.errors.append(f"{context}: invalid affordability_status {row['affordability_status']!r}")
            if row["recommended_payment_method"] not in valid_methods:
                self.errors.append(f"{context}: invalid recommended_payment_method {row['recommended_payment_method']!r}")
            if row["earliest_date_for_full_payment"].strip():
                self._date(row["earliest_date_for_full_payment"], context)

    def _parse_events(self, rows: list[dict[str, str]], image_event_ids: set[str]) -> Iterable[Event]:
        result=[]
        for number,row in enumerate(rows,2):
            c=f"financial_events.csv:{number}"; event_id=self._id(row,"event_id",c); currency=self._currency(row["currency"],c)
            for field,allowed in (("event_type",VALID_EVENT_TYPES),("direction",VALID_DIRECTIONS),("status",VALID_EVENT_STATUSES),("flexibility",VALID_FLEXIBILITY)):
                if row[field] not in allowed: self.errors.append(f"{c}: invalid {field} {row[field]!r}")
            amount_from_image=False
            if not row["amount"].strip():
                evidence=IMAGE_EVIDENCE_AMOUNTS.get(event_id)
                if evidence is None: self.errors.append(f"{c}: blank amount has no reviewed image evidence mapping"); amount=Decimal(0)
                else:
                    amount,evidence_currency=evidence; amount_from_image=True
                    if event_id not in image_event_ids: self.errors.append(f"{c}: blank amount mapping has no images.csv link")
                    if evidence_currency != currency: self.errors.append(f"{c}: image evidence currency {evidence_currency} does not match event currency {currency}")
            else: amount=self._decimal(row["amount"],c) or Decimal(0)
            result.append(Event(event_id,self._id(row,"user_id",c),cast(str,row["event_type"]),row["description"],row["category"],cast(str,row["direction"]),amount,cast(str,currency),self._date(row["event_date"],c) or date.min,self._date(row["settlement_date"],c,required=False),cast(str,row["status"]),row["linked_event_id"].strip() or None,cast(str,row["flexibility"]),self._decimal(row["minimum_allowed_amount"],c,required=False),amount_from_image))
        self._unique(result,"event_id","financial_events.csv")
        blank_mapped=set(IMAGE_EVIDENCE_AMOUNTS) - {event.event_id for event in result if event.amount_from_image_evidence}
        if blank_mapped: self.errors.append(f"financial_events.csv: reviewed image evidence maps unknown/nonblank events {sorted(blank_mapped)!r}")
        return result

    def _parse_rates(self, rows: list[dict[str,str]]) -> Iterable[ExchangeRate]:
        result=[]; seen=set()
        for n,row in enumerate(rows,2):
            c=f"exchange_rates.csv:{n}"; rate_date=self._date(row["rate_date"],c) or date.min; frm=self._currency(row["from_currency"],c); to=self._currency(row["to_currency"],c); rate=self._decimal(row["rate"],c) or Decimal(0)
            if rate <= 0: self.errors.append(f"{c}: rate must be positive")
            key=(rate_date,frm,to)
            if key in seen: self.errors.append(f"{c}: duplicate rate key {key!r}")
            seen.add(key); result.append(ExchangeRate(rate_date,frm,to,rate))
        return result

    def _parse_options(self, rows: list[dict[str,str]]) -> Iterable[PaymentOption]:
        result=[]
        for n,row in enumerate(rows,2):
            c=f"request_payment_options.csv:{n}"; method=row["payment_method"]
            if method not in VALID_OPTION_METHODS: self.errors.append(f"{c}: invalid payment_method {method!r}")
            try: count=int(row["number_of_payments"]); assert count > 0
            except (ValueError,AssertionError): self.errors.append(f"{c}: number_of_payments must be positive integer"); count=0
            frequency=None; raw_frequency=row["payment_frequency_days"].strip()
            if raw_frequency:
                try: frequency=int(raw_frequency); assert frequency > 0
                except (ValueError,AssertionError): self.errors.append(f"{c}: payment_frequency_days must be positive integer or blank")
            if method == "full_payment" and (count != 1 or frequency is not None): self.errors.append(f"{c}: full payment option must have one payment and blank frequency")
            if method == "installments" and (count < 2 or frequency is None): self.errors.append(f"{c}: installment option must have >=2 payments and frequency")
            result.append(PaymentOption(self._id(row,"payment_option_id",c),self._id(row,"request_id",c),cast(str,method),self._decimal(row["payment_amount"],c) or Decimal(0),count,self._date(row["first_payment_date"],c) or date.min,frequency,self._decimal(row["financing_fee"],c) or Decimal(0),self._decimal(row["total_payable_amount"],c) or Decimal(0)))
        self._unique(result,"payment_option_id","request_payment_options.csv"); return result

    def _parse_messages(self, rows: list[dict[str,str]]) -> Iterable[Message]:
        result=[]
        for n,row in enumerate(rows,2):
            c=f"messages.csv:{n}"; source=row["source_type"]
            if source not in VALID_MESSAGE_SOURCES: self.errors.append(f"{c}: invalid source_type {source!r}")
            try: sent_at=datetime.fromisoformat(row["sent_at"].replace("Z","+00:00"))
            except ValueError: self.errors.append(f"{c}: invalid ISO-8601 sent_at {row['sent_at']!r}"); sent_at=datetime.min
            result.append(Message(self._id(row,"message_id",c),self._id(row,"user_id",c),row["request_id"].strip() or None,row["related_event_id"].strip() or None,sent_at,cast(str,source),row["message_text"]))
        self._unique(result,"message_id","messages.csv"); return result

    def _validate_relationships(self, profiles: tuple[Profile,...], requests: tuple[Request,...], samples: tuple[Request,...], events: tuple[Event,...], options: tuple[PaymentOption,...], messages: tuple[Message,...], images: tuple[ImageLink,...], output_ids: tuple[str,...]) -> None:
        user_ids={p.user_id for p in profiles}; event_ids={e.event_id for e in events}; request_ids={r.request_id for r in requests}; all_request_ids=request_ids | {r.request_id for r in samples}
        if len(set(output_ids)) != len(output_ids): self.errors.append("output.csv: duplicate request_id")
        if set(output_ids) != request_ids: self.errors.append("output.csv: request IDs must exactly match requests.csv")
        for name,items,field,allowed in (("requests.csv",requests,"user_id",user_ids),("sample_requests.csv",samples,"user_id",user_ids),("financial_events.csv",events,"user_id",user_ids),("request_payment_options.csv",options,"request_id",all_request_ids),("messages.csv",messages,"user_id",user_ids),("images.csv",images,"user_id",user_ids)):
            for item in items:
                if getattr(item,field) not in allowed: self.errors.append(f"{name}: unknown {field} {getattr(item,field)!r}")
        for message in messages:
            if message.request_id and message.request_id not in all_request_ids: self.errors.append(f"messages.csv: unknown request_id {message.request_id!r}")
            if message.related_event_id and message.related_event_id not in event_ids: self.errors.append(f"messages.csv: unknown related_event_id {message.related_event_id!r}")
        for image in images:
            if image.request_id not in all_request_ids: self.errors.append(f"images.csv: unknown request_id {image.request_id!r}")
            if image.related_event_id not in event_ids: self.errors.append(f"images.csv: unknown related_event_id {image.related_event_id!r}")
        for event in events:
            if event.linked_event_id and event.linked_event_id not in event_ids: self.errors.append(f"financial_events.csv: unknown linked_event_id {event.linked_event_id!r}")
