#!/usr/bin/env python3
"""Generate conservative, deterministic Buy or Wait? predictions."""

from __future__ import annotations

import argparse
import csv
import itertools
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]
CENT = Decimal("0.01")
ZERO = Decimal("0")
MONEY_RE = re.compile(
    r"\b(?P<currency>IDR|INR|ZAR|EUR|USD)\s*(?P<amount>\d[\d,]*(?:\.\d+)?)\b",
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MONTH_NAMES = (
    "January February March April May June July August September October November December"
).split()


@dataclass(frozen=True)
class CashFlow:
    day: date
    amount: Decimal
    direction: str
    series_key: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class FlexibleChange:
    key: str
    event_id: str
    kind: str
    amount: Decimal = ZERO

    def render(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{format_money(self.amount)}"


def parse_decimal(value: str | Decimal | None, field: str) -> Decimal:
    if value is None or not str(value).strip():
        raise ValueError(f"Missing numeric value for {field}")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Non-finite numeric value for {field}: {value!r}")
    return result


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    return f"{cents(value):.2f}"


def format_number(value: Decimal) -> str:
    text = f"{cents(value):.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset file not found: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return [dict(row) for row in reader]


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, min(day.day, (next_month - timedelta(days=1)).day))


class ExchangeRates:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def convert(self, amount: Decimal, source: str, target: str, on_date: date) -> Decimal:
        if source == target:
            return cents(amount)

        graph: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
        for row in self.rows:
            if date.fromisoformat(row["rate_date"]) > on_date:
                continue
            rate = parse_decimal(row["rate"], "exchange rate")
            if rate <= 0:
                raise ValueError(f"Exchange rate must be positive: {row}")
            source_currency, target_currency = row["from_currency"], row["to_currency"]
            graph[source_currency].append((target_currency, rate))
            graph[target_currency].append((source_currency, Decimal(1) / rate))

        queue: deque[tuple[str, Decimal]] = deque([(source, Decimal(1))])
        seen = {source}
        while queue:
            currency, multiplier = queue.popleft()
            for next_currency, rate in graph[currency]:
                if next_currency in seen:
                    continue
                combined_rate = multiplier * rate
                if next_currency == target:
                    return cents(amount * combined_rate)
                seen.add(next_currency)
                queue.append((next_currency, combined_rate))
        raise ValueError(
            f"No dated exchange-rate path from {source} to {target} on or before {on_date}"
        )


def linked_image_amounts(image_rows: list[dict[str, str]]) -> dict[str, Decimal]:
    known_values = {
        "image_01": "4365000",
        "image_02": "100000",
        "image_03": "41272",
        "image_04": "2854",
        "image_05": "704.05",
        "image_06": "1995",
        "image_07": "8528.10",
        "image_08": "15339",
        "image_09": "723",
        "image_10": "79679.26",
        "image_11": "3650",
        "image_12": "33.50",
        "image_13": "2298",
        "image_14": "4543",
        "image_15": "9968",
        "image_16": "393.22",
    }
    result: dict[str, Decimal] = {}
    for row in image_rows:
        image_id = row["image_id"]
        if image_id not in known_values:
            raise ValueError(f"No extracted amount is available for linked image {image_id}")
        result[row["related_event_id"]] = Decimal(known_values[image_id])
    return result


def extract_date(text: str) -> date | None:
    match = ISO_DATE_RE.search(text)
    if match:
        return date.fromisoformat(match.group())
    for month_number, month_name in enumerate(MONTH_NAMES, start=1):
        match = re.search(
            rf"\b(\d{{1,2}})\s+{month_name}\s+(\d{{4}})\b",
            text,
            re.IGNORECASE,
        )
        if match:
            return date(int(match.group(2)), month_number, int(match.group(1)))
        match = re.search(
            rf"\b{month_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
            text,
            re.IGNORECASE,
        )
        if match:
            return date(int(match.group(2)), month_number, int(match.group(1)))
    return None


def apply_message_overrides(
    events: list[dict[str, str]],
    messages: list[dict[str, str]],
    rates: ExchangeRates,
    image_amounts: dict[str, Decimal],
) -> tuple[dict[str, Decimal], set[str], dict[str, date]]:
    amounts = {
        row["event_id"]: (
            parse_decimal(row["amount"], f"amount for {row['event_id']}")
            if row["amount"].strip()
            else image_amounts[row["event_id"]]
        )
        for row in events
        if row["amount"].strip() or row["event_id"] in image_amounts
    }
    cancelled: set[str] = set()
    settled_overrides: dict[str, date] = {}
    by_id = {row["event_id"]: row for row in events}

    for message in sorted(messages, key=lambda row: row["sent_at"]):
        event_id = message["related_event_id"]
        event = by_id.get(event_id)
        if event is None:
            continue
        text = message["message_text"]
        lowered = text.casefold()
        explicit_cancel = re.search(
            r"\b(cancelled|canceled|terminated|no longer payable|payment was stopped)\b",
            lowered,
        )
        if explicit_cancel:
            cancelled.add(event_id)
        elif re.search(r"\b(paid|settled|received)\b", lowered) and event["status"] in {
            "pending",
            "scheduled",
        }:
            message_date = extract_date(text)
            if message_date:
                settled_overrides[event_id] = message_date

        currency_amount = MONEY_RE.search(text)
        is_amendment = re.search(
            r"\b(now|updated|revised|increased|decreased|changed|new amount|amount is)\b",
            lowered,
        )
        if currency_amount and is_amendment:
            raw_amount = parse_decimal(currency_amount.group("amount"), "message amount")
            source_currency = currency_amount.group("currency").upper()
            event_date = date.fromisoformat(
                event["settlement_date"] or event["event_date"]
            )
            amounts[event_id] = rates.convert(
                raw_amount, source_currency, event["currency"], event_date
            )

    unresolved = [
        row["event_id"]
        for row in events
        if row["event_id"] not in amounts
    ]
    if unresolved:
        raise ValueError(
            "Could not resolve amounts for financial events: " + ", ".join(unresolved[:10])
        )
    return amounts, cancelled, settled_overrides


def payroll_message_facts(
    messages: list[dict[str, str]],
) -> dict[str, dict[str, object]]:
    facts: dict[str, dict[str, object]] = {}
    for message in sorted(messages, key=lambda row: row["sent_at"]):
        if message["related_event_id"]:
            continue
        text = message["message_text"]
        lowered = text.casefold()
        sent_day = date.fromisoformat(message["sent_at"][:10])
        fact = facts.setdefault(message["user_id"], {})
        fact["sent_at"] = message["sent_at"]
        if message["source_type"] == "bank" and re.search(
            r"matching debit and credit.*transfer between your two accounts|both accounts.*same account holder",
            lowered,
        ):
            fact["ignore_internal_transfers"] = True
        if re.search(r"\b(rent|lease|sewa)\b", lowered) and re.search(
            r"\b(increase|increases|increased|menaikkan|naikkan)\b", lowered
        ):
            increase = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if increase:
                fact["rent_increases"] = [
                    *fact.get("rent_increases", []),
                    {
                        "effective": sent_day,
                        "factor": Decimal(1) + parse_decimal(increase.group(1), "rent increase") / 100,
                    },
                ]
        if (
            message["source_type"] == "service_provider"
            and re.search(r"\bapproved\b", lowered)
            and re.search(r"\binvoice payment\b", lowered)
        ):
            match = MONEY_RE.search(text)
            payment_day = extract_date(text)
            if match and payment_day:
                fact["confirmed_payments"] = [
                    *fact.get("confirmed_payments", []),
                    {
                        "day": payment_day,
                        "amount": parse_decimal(match.group("amount"), "confirmed invoice amount"),
                        "currency": match.group("currency").upper(),
                    },
                ]

        if not re.search(r"\b(salary|payroll|gaji|monthly pay)\b", lowered):
            continue
        message_date = extract_date(text)
        if re.search(
            r"\b(employment has ended|current seasonal contract has ended|contract has ended|no off-season income|without renewal|regular salary payments.*after the final settlement)\b",
            lowered,
        ) and "remaining confirmed monthly salary" not in lowered:
            fact["ends"] = message_date or sent_day
            fact["sent_at"] = message["sent_at"]
            continue
        match = MONEY_RE.search(text)
        if match:
            amount = parse_decimal(match.group("amount"), "payroll message amount")
            currency = match.group("currency").upper()
            if re.search(r"\b(first salary|first salary from the new employer)\b", lowered) and message_date:
                fact["confirmed_payments"] = [
                    *fact.get("confirmed_payments", []),
                    {"day": message_date, "amount": amount, "currency": currency},
                ]
            elif re.search(r"\b(resumes on|salary resumes)\b", lowered) and message_date:
                fact["resume_salary"] = {
                    "day": message_date,
                    "amount": amount,
                    "currency": currency,
                }
                fact["amount"] = amount
                fact["currency"] = currency
                fact["effective"] = message_date
            else:
                fact["amount"] = amount
                fact["currency"] = currency
                fact["effective"] = message_date or sent_day + timedelta(days=30)
        elif message_date and re.search(
            r"\b(confirmed salary is now expected|revised payroll date|revised date)\b",
            lowered,
        ):
            fact["payroll_date"] = message_date
        fact["sent_at"] = message["sent_at"]
    return facts


def normalized_description(text: str) -> str:
    lowered = text.casefold()
    for month_name in MONTH_NAMES:
        lowered = re.sub(rf"\b{month_name.casefold()}\b", " ", lowered)
    lowered = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", lowered)
    lowered = re.sub(r"\b\d+(?:\.\d+)?\b", " ", lowered)
    return " ".join(re.findall(r"[a-z]+", lowered))


def event_series_key(event: dict[str, str]) -> str:
    parts = (
        event["user_id"],
        event["event_type"],
        event["category"],
        event["direction"],
        normalized_description(event["description"]),
        event["currency"],
    )
    return "\x1f".join(parts)


def detect_frequency(days: list[date]) -> tuple[str, int] | None:
    if len(days) < 3:
        return None
    gaps = [(right - left).days for left, right in zip(days, days[1:])]
    for name, low, high in (("weekly", 6, 8), ("fortnightly", 13, 16), ("monthly", 26, 32)):
        matching = [gap for gap in gaps if low <= gap <= high]
        if len(matching) >= 2 and len(matching) / len(gaps) >= 0.7:
            if name == "monthly":
                return name, 1
            return name, max(1, round(sum(matching) / len(matching)))
    return None


def percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def infer_series(
    events: list[dict[str, str]],
    amounts: dict[str, Decimal],
    request_date: date,
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    cutoff = request_date - timedelta(days=210)
    salary_history = [
        event
        for event in events
        if event["category"] == "salary"
        and event["direction"] == "credit"
        and event["status"] == "settled"
        and cutoff
        <= date.fromisoformat(event["settlement_date"] or event["event_date"])
        < request_date
    ]
    latest_salary = max(
        salary_history,
        key=lambda event: date.fromisoformat(event["settlement_date"] or event["event_date"]),
        default=None,
    )
    salary_ended = bool(
        latest_salary
        and re.search(
            r"\b(final|last|terminated|ended|non[- ]?renewal)\b",
            latest_salary["description"],
            re.IGNORECASE,
        )
    )
    for event in events:
        if (
            event["status"] != "settled"
            or event["direction"] not in {"debit", "credit"}
            or event["category"] in {"investment_valuation"}
        ):
            continue
        event_date = date.fromisoformat(event["settlement_date"] or event["event_date"])
        if cutoff <= event_date < request_date:
            grouped[event_series_key(event)].append(event)

    series: dict[str, dict[str, object]] = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda row: date.fromisoformat(row["settlement_date"] or row["event_date"]))
        days = [
            date.fromisoformat(row["settlement_date"] or row["event_date"])
            for row in rows
        ]
        frequency = detect_frequency(days)
        if (
            frequency is None
            and rows[-1]["category"] == "salary"
            and len(rows) >= 2
            and re.search(r"\b(after returning from leave|resumed payroll)\b", rows[-1]["description"], re.I)
        ):
            frequency = ("monthly", 1)
        if frequency is None:
            continue
        if rows[-1]["category"] == "salary" and salary_ended:
            continue
        direction = rows[-1]["direction"]
        sample = rows[-8:]
        sample_amounts = [amounts[row["event_id"]] for row in sample]
        typical_amount = (
            percentile(sample_amounts, Decimal("0.5"))
            if direction == "credit"
            else percentile(sample_amounts, Decimal("0.75"))
        )
        series[key] = {
            "key": key,
            "rows": rows,
            "latest": rows[-1],
            "last_day": days[-1],
            "frequency": frequency,
            "amount": typical_amount,
            "category": rows[-1]["category"],
            "direction": direction,
            "flexibility": rows[-1]["flexibility"],
            "minimum_allowed_amount": (
                parse_decimal(rows[-1]["minimum_allowed_amount"], "minimum allowed amount")
                if rows[-1]["minimum_allowed_amount"].strip()
                else None
            ),
        }
    if not any(inferred["category"] == "salary" for inferred in series.values()):
        salary_rows = [
            row
            for row in events
            if row["category"] == "salary"
            and row["direction"] == "credit"
            and row["event_type"] == "income"
            and row["status"] == "settled"
            and cutoff
            <= date.fromisoformat(row["settlement_date"] or row["event_date"])
            < request_date
        ]
        salary_rows.sort(
            key=lambda row: date.fromisoformat(row["settlement_date"] or row["event_date"])
        )
        if (
            len(salary_rows) >= 2
            and re.search(
                r"\b(after returning from leave|resumed payroll)\b",
                salary_rows[-1]["description"],
                re.IGNORECASE,
            )
        ):
            latest = salary_rows[-1]
            key = event_series_key(latest)
            series[key] = {
                "key": key,
                "rows": salary_rows,
                "latest": latest,
                "last_day": date.fromisoformat(
                    latest["settlement_date"] or latest["event_date"]
                ),
                "frequency": ("monthly", 1),
                "amount": amounts[latest["event_id"]],
                "category": latest["category"],
                "direction": latest["direction"],
                "flexibility": latest["flexibility"],
                "minimum_allowed_amount": None,
            }
    return series


def recurring_dates(
    last_day: date,
    frequency: tuple[str, int],
    start: date,
    end: date,
) -> Iterable[date]:
    name, interval = frequency
    day = last_day
    while day < start:
        day = add_months(day, interval) if name == "monthly" else day + timedelta(days=interval)
    while day <= end:
        yield day
        day = add_months(day, interval) if name == "monthly" else day + timedelta(days=interval)


def build_projection(
    request: dict[str, str],
    profile: dict[str, str],
    events: list[dict[str, str]],
    amounts: dict[str, Decimal],
    cancelled: set[str],
    settled_overrides: dict[str, date],
    series: dict[str, dict[str, object]],
    rates: ExchangeRates,
    payroll: dict[str, dict[str, object]],
    changes: tuple[FlexibleChange, ...] = (),
) -> tuple[list[date], list[Decimal]]:
    request_date = date.fromisoformat(request["request_date"])
    end_date = request_date + timedelta(days=90)
    home_currency = profile["home_currency"]
    changed_by_key = {change.key: change for change in changes}
    flows: list[CashFlow] = []
    explicit: list[tuple[dict[str, str], date, Decimal]] = []
    internal_transfer_ids: set[str] = set()
    event_by_id = {event["event_id"]: event for event in events}
    for user_id, fact in payroll.items():
        if not fact.get("ignore_internal_transfers"):
            continue
        for event in events:
            linked = event_by_id.get(event["linked_event_id"])
            if (
                event["user_id"] == user_id
                and linked is not None
                and linked["user_id"] == user_id
                and event["direction"] != linked["direction"]
                and "transfer" in event["description"].casefold()
                and "transfer" in linked["description"].casefold()
            ):
                internal_transfer_ids.update({event["event_id"], linked["event_id"]})

    latest_salary_by_user: dict[str, dict[str, str]] = {}
    for event in events:
        if event["category"] != "salary" or event["direction"] != "credit":
            continue
        if event["user_id"] not in latest_salary_by_user or date.fromisoformat(
            event["settlement_date"] or event["event_date"]
        ) > date.fromisoformat(
            latest_salary_by_user[event["user_id"]]["settlement_date"]
            or latest_salary_by_user[event["user_id"]]["event_date"]
        ):
            latest_salary_by_user[event["user_id"]] = event
    ended_salary_users = {
        user_id
        for user_id, event in latest_salary_by_user.items()
        if re.search(
            r"\b(final|last|terminated|ended|non[- ]?renewal)\b",
            event["description"],
            re.IGNORECASE,
        )
    }
    for event in events:
        if event["event_id"] in cancelled or event["event_id"] in internal_transfer_ids:
            continue
        status = event["status"]
        direction = event["direction"]
        if status in {"failed", "cancelled", "unrealized"} or direction == "non_cash":
            continue

        if event["event_id"] in settled_overrides:
            event_day = settled_overrides[event["event_id"]]
            status = "settled"
        else:
            event_day = date.fromisoformat(event["settlement_date"] or event["event_date"])

        salary_fact = payroll.get(event["user_id"], {})
        payroll_date = salary_fact.get("payroll_date")
        if (
            event["category"] == "salary"
            and status == "scheduled"
            and payroll_date
            and payroll_date >= request_date
        ):
            event_day = payroll_date

        if status == "pending":
            if direction == "debit":
                event_day = request_date
            elif direction == "credit":
                continue
        elif status == "settled":
            if event_day < request_date:
                continue
            if event_day > request_date:
                continue
        elif status == "scheduled":
            if direction == "credit" and event["event_type"] not in {"income"}:
                continue
        else:
            continue

        if event_day > end_date:
            continue
        amount = rates.convert(
            amounts[event["event_id"]], event["currency"], home_currency, event_day
        )
        if event["category"] == "salary":
            ends = salary_fact.get("ends")
            if ends and event_day > ends:
                continue
            effective = salary_fact.get("effective")
            if effective and event_day >= effective and "amount" in salary_fact:
                amount = rates.convert(
                    salary_fact["amount"],
                    str(salary_fact["currency"]),
                    home_currency,
                    event_day,
                )
        if event["category"] == "rent":
            for increase in salary_fact.get("rent_increases", []):
                if event_day >= increase["effective"]:
                    amount = cents(amount * increase["factor"])
        key = event_series_key(event)
        change = changed_by_key.get(key)
        if change:
            if change.kind == "stop":
                continue
            amount = rates.convert(
                change.amount, event["currency"], home_currency, event_day
            )
        explicit.append((event, event_day, amount))

    for event, event_day, amount in explicit:
        flows.append(
            CashFlow(
                event_day,
                amount,
                event["direction"],
                event_series_key(event),
                event["event_id"],
            )
        )

    explicit_days = [
        (event["category"], event["direction"], event_day)
        for event, event_day, _ in explicit
    ]
    for key, inferred in series.items():
        for event_day in recurring_dates(
            inferred["last_day"], inferred["frequency"], request_date, end_date
        ):
            category = str(inferred["category"])
            direction = str(inferred["direction"])
            if any(
                existing_category == category
                and existing_direction == direction
                and abs((existing_day - event_day).days) <= 2
                for existing_category, existing_direction, existing_day in explicit_days
            ):
                continue
            event = inferred["latest"]
            change = changed_by_key.get(key)
            if change and change.kind == "stop":
                continue
            amount = change.amount if change else inferred["amount"]
            salary_fact = payroll.get(event["user_id"], {})
            ends = salary_fact.get("ends")
            if event["category"] == "salary" and ends and event_day > ends:
                continue
            resume = salary_fact.get("resume_salary")
            if (
                event["category"] == "salary"
                and resume
                and event_day < resume["day"]
            ):
                continue
            effective = salary_fact.get("effective")
            if (
                event["category"] == "salary"
                and effective
                and event_day >= effective
                and "amount" in salary_fact
            ):
                converted = rates.convert(
                    salary_fact["amount"],
                    str(salary_fact["currency"]),
                    home_currency,
                    event_day,
                )
                if event["category"] == "rent":
                    for increase in salary_fact.get("rent_increases", []):
                        if event_day >= increase["effective"]:
                            converted = cents(converted * increase["factor"])
                flows.append(CashFlow(event_day, converted, direction, key, event["event_id"]))
                continue
            converted = rates.convert(
                amount, event["currency"], home_currency, event_day
            )
            if event["category"] == "rent":
                for increase in salary_fact.get("rent_increases", []):
                    if event_day >= increase["effective"]:
                        converted = cents(converted * increase["factor"])
            flows.append(CashFlow(event_day, converted, direction, key, event["event_id"]))

    for user_id, fact in payroll.items():
        if user_id != request["user_id"]:
            continue
        for payment in fact.get("confirmed_payments", []):
            payment_day = payment["day"]
            if request_date <= payment_day <= end_date:
                converted = rates.convert(
                    payment["amount"],
                    payment["currency"],
                    home_currency,
                    payment_day,
                )
                if not any(
                    flow.day == payment_day
                    and flow.direction == "credit"
                    and flow.amount == converted
                    for flow in flows
                ):
                    flows.append(CashFlow(payment_day, converted, "credit"))
        resume = fact.get("resume_salary")
        if resume and not any(
            inferred["category"] == "salary"
            and inferred["latest"]["user_id"] == user_id
            for inferred in series.values()
        ):
            payment_day = resume["day"]
            while payment_day <= end_date:
                if payment_day >= request_date:
                    flows.append(
                        CashFlow(
                            payment_day,
                            rates.convert(
                                resume["amount"],
                                resume["currency"],
                                home_currency,
                                payment_day,
                            ),
                            "credit",
                        )
                    )
                payment_day = add_months(payment_day, 1)

    for event, event_day, amount in explicit:
        if (
            event["status"] != "scheduled"
            or event["event_type"] != "income"
            or event["direction"] != "credit"
            or event["category"] != "salary"
            or re.search(r"\b(final|last|terminated|ended)\b", event["description"], re.I)
        ):
            continue
        user_history = [
            row
            for row in events
            if row["user_id"] == event["user_id"]
            and row["category"] == "salary"
            and row["direction"] == "credit"
            and row["status"] == "settled"
            and date.fromisoformat(row["settlement_date"] or row["event_date"]) < event_day
        ]
        if not user_history:
            continue
        scheduled_dates = [
            event_day + timedelta(days=30 * month)
            for month in range(1, 4)
        ]
        salary_fact = payroll.get(event["user_id"], {})
        for scheduled_day in scheduled_dates:
            if scheduled_day > end_date:
                continue
            if any(
                row["category"] == "salary"
                and row["direction"] == "credit"
                and abs((other_day - scheduled_day).days) <= 2
                for row, other_day, _ in explicit
            ):
                continue
            ends = salary_fact.get("ends")
            if ends and scheduled_day > ends:
                continue
            effective = salary_fact.get("effective")
            future_amount = amount
            if effective and scheduled_day >= effective and "amount" in salary_fact:
                future_amount = rates.convert(
                    salary_fact["amount"],
                    str(salary_fact["currency"]),
                    home_currency,
                    scheduled_day,
                )
            flows.append(CashFlow(scheduled_day, future_amount, "credit"))

    recurring_event_ids = {
        row["event_id"]
        for inferred in series.values()
        for row in inferred["rows"]
    }
    weekly_totals: dict[tuple[str, str, str, str], dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: ZERO)
    )
    weekly_event_days: dict[tuple[str, str, str, str], list[date]] = defaultdict(list)
    for event in events:
        if (
            event["event_id"] in recurring_event_ids
            or event["event_id"] in internal_transfer_ids
            or event["status"] != "settled"
            or event["direction"] not in {"debit", "credit"}
            or event["event_type"] not in {"expense", "income"}
        ):
            continue
        if event["direction"] == "credit" and (
            event["category"] != "salary"
            or event["event_type"] != "income"
            or event["user_id"] in ended_salary_users
            or re.search(
                r"\b(final|last|terminated|ended|bonus|commission|refund|lottery|investment|pending|unapproved)\b",
                event["description"],
                re.IGNORECASE,
            )
            or re.search(
                r"\b(bonus|commission|refund|lottery|investment|pending|unapproved)\b",
                event["description"],
                re.IGNORECASE,
            )
        ):
            continue
        event_day = date.fromisoformat(event["settlement_date"] or event["event_date"])
        if not request_date - timedelta(days=210) <= event_day < request_date:
            continue
        key = (
            event["category"],
            event["direction"],
            event["currency"],
            event["event_type"],
        )
        week = event_day - timedelta(days=event_day.weekday())
        weekly_totals[key][week] += amounts[event["event_id"]]
        weekly_event_days[key].append(event_day)

    for (category, direction, currency, event_type), buckets in weekly_totals.items():
        if len(buckets) < 3:
            continue
        first_week = min(buckets)
        last_week = max(buckets)
        all_weeks = []
        week = first_week
        while week <= last_week:
            all_weeks.append(week)
            week += timedelta(days=7)
        active_weeks = sum(buckets.get(week, ZERO) > 0 for week in all_weeks)
        if len(all_weeks) < 12 or active_weeks < 6 or active_weeks / len(all_weeks) < 0.35:
            continue
        expected_weekly_amount = cents(
            sum((buckets.get(week, ZERO) for week in all_weeks), ZERO)
            / len(all_weeks)
        )
        if expected_weekly_amount <= ZERO:
            continue
        weekday_counts: dict[int, int] = defaultdict(int)
        for event_day in weekly_event_days[(category, direction, currency, event_type)]:
            weekday_counts[event_day.weekday()] += 1
        target_weekday = min(
            weekday_counts, key=lambda weekday: (-weekday_counts[weekday], weekday)
        )
        first_day = request_date + timedelta(
            days=(target_weekday - request_date.weekday()) % 7
        )
        for event_day in recurring_dates(
            first_day - timedelta(days=7),
            ("weekly", 7),
            request_date,
            end_date,
        ):
            week_start = event_day - timedelta(days=event_day.weekday())
            scheduled_amount = sum(
                (
                    amount
                    for event, scheduled_day, amount in explicit
                    if event["category"] == category
                    and event["direction"] == direction
                    and week_start <= scheduled_day < week_start + timedelta(days=7)
                ),
                ZERO,
            )
            native_amount = max(ZERO, expected_weekly_amount - scheduled_amount)
            converted = rates.convert(native_amount, currency, home_currency, event_day)
            if converted:
                flows.append(CashFlow(event_day, converted, direction))

    balances: list[Decimal] = []
    dates = [request_date + timedelta(days=offset) for offset in range(91)]
    flow_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for flow in flows:
        flow_by_day[flow.day] += flow.amount if flow.direction == "credit" else -flow.amount

    balance = parse_decimal(profile["current_available_balance"], "current balance")
    for day in dates:
        balance += flow_by_day[day]
        balances.append(cents(balance))
    return dates, balances


def safe_with_payments(
    balances: list[Decimal],
    dates: list[date],
    minimum: Decimal,
    payments: list[tuple[date, Decimal]],
) -> bool:
    payment_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for day, amount in payments:
        if day not in dates:
            return False
        payment_by_day[day] += amount
    balance = ZERO
    remaining = ZERO
    for day, projected in zip(dates, balances):
        remaining += payment_by_day[day]
        if projected - remaining < minimum:
            return False
        balance = projected
    return True


def max_safe_today(balances: list[Decimal], minimum: Decimal, requested: Decimal) -> Decimal:
    return cents(max(ZERO, min(requested, min(balance - minimum for balance in balances))))


def earliest_safe_date(
    balances: list[Decimal],
    dates: list[date],
    minimum: Decimal,
    requested: Decimal,
) -> date | None:
    for payment_day in dates:
        if safe_with_payments(balances, dates, minimum, [(payment_day, requested)]):
            return payment_day
    return None


def flexible_candidates(
    series: dict[str, dict[str, object]],
    profile: dict[str, str],
) -> list[FlexibleChange]:
    protected = set(filter(None, profile["expense_categories_to_protect"].split("|")))
    reducible = set(
        filter(None, profile["expense_categories_user_is_willing_to_reduce"].split("|"))
    )
    stoppable = set(
        filter(None, profile["expense_categories_user_is_willing_to_stop"].split("|"))
    )
    candidates: list[FlexibleChange] = []
    for key, inferred in series.items():
        category = str(inferred["category"])
        flexibility = str(inferred["flexibility"])
        latest = inferred["latest"]
        if (
            inferred["direction"] != "debit"
            or category in protected
            or len(inferred["rows"]) < 3
        ):
            continue
        event_id = latest["event_id"]
        if category in stoppable and flexibility in {"stoppable", "reducible_or_stoppable"}:
            candidates.append(FlexibleChange(key, event_id, "stop"))
        if category in reducible and flexibility in {"reducible", "reducible_or_stoppable"}:
            minimum = inferred["minimum_allowed_amount"]
            amount = minimum if minimum is not None else cents(inferred["amount"] / 2)
            if ZERO <= amount < inferred["amount"]:
                candidates.append(FlexibleChange(key, event_id, "reduce", amount))
    return candidates


def best_full_payment_changes(
    request: dict[str, str],
    profile: dict[str, str],
    events: list[dict[str, str]],
    amounts: dict[str, Decimal],
    cancelled: set[str],
    settled_overrides: dict[str, date],
    series: dict[str, dict[str, object]],
    rates: ExchangeRates,
    payroll: dict[str, dict[str, object]],
    minimum: Decimal,
    requested: Decimal,
) -> tuple[FlexibleChange, ...] | None:
    candidates = flexible_candidates(series, profile)
    if not candidates:
        return None
    request_date = date.fromisoformat(request["request_date"])
    for count in range(1, min(3, len(candidates)) + 1):
        feasible: list[tuple[tuple[str, ...], tuple[FlexibleChange, ...]]] = []
        for combination in itertools.combinations(candidates, count):
            if len({change.key for change in combination}) != len(combination):
                continue
            if len({change.event_id for change in combination}) != len(combination):
                continue
            dates, balances = build_projection(
                request,
                profile,
                events,
                amounts,
                cancelled,
                settled_overrides,
                series,
                rates,
                payroll,
                combination,
            )
            if safe_with_payments(
                balances, dates, minimum, [(request_date, requested)]
            ):
                feasible.append(
                    (tuple(sorted(change.event_id for change in combination)), combination)
                )
        if feasible:
            return min(feasible, key=lambda item: item[0])[1]
    return None


def payment_option_rows(
    request_id: str,
    options: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [row for row in options if row["request_id"] == request_id]


def option_schedule(option: dict[str, str]) -> list[tuple[date, Decimal]]:
    count = int(option["number_of_payments"])
    first_day = date.fromisoformat(option["first_payment_date"])
    frequency = int(option["payment_frequency_days"] or "0")
    amount = cents(parse_decimal(option["payment_amount"], "payment option amount"))
    return [
        (first_day + timedelta(days=index * frequency), amount)
        for index in range(count)
    ]


def minimum_after_plan(
    balances: list[Decimal],
    dates: list[date],
    payments: list[tuple[date, Decimal]],
) -> Decimal:
    payment_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for day, amount in payments:
        payment_by_day[day] += amount
    cumulative = ZERO
    minimum = min(balances)
    for day, balance in zip(dates, balances):
        cumulative += payment_by_day[day]
        minimum = min(minimum, balance - cumulative)
    return cents(minimum)


def decision_explanation(
    currency: str,
    requested: Decimal,
    minimum: Decimal,
    method: str,
    schedule: list[tuple[date, Decimal]],
    changes: tuple[FlexibleChange, ...],
    amount_safe: Decimal,
    full_date: date | None,
    observed_minimum: Decimal,
) -> str:
    if method == "not_recommended":
        if full_date is None:
            return (
                f"Do not proceed with the {currency} {format_number(requested)} request. "
                f"Although {currency} {format_number(amount_safe)} is available today, "
                f"the full amount cannot be completed safely within 90 days."
            )
        return (
            f"Do not make this payment by {schedule[0][0].strftime('%d %B %Y') if schedule else 'the deadline'}. "
            f"None of the available options keeps the {currency} {format_number(minimum)} minimum protected."
        )
    if changes:
        actions = []
        for change in changes:
            if change.kind == "stop":
                actions.append(f"stop {change.event_id}")
            else:
                actions.append(
                    f"reduce {change.event_id} to {currency} {format_number(change.amount)}"
                )
        return (
            f"{' and '.join(actions).capitalize()}, then pay {currency} "
            f"{format_number(requested)} today. This leaves at least {currency} "
            f"{format_number(observed_minimum)} available."
        )
    if method == "full_payment":
        return (
            f"Pay {currency} {format_number(requested)} today. This leaves at least "
            f"{currency} {format_number(observed_minimum)} available over the next 90 days."
        )
    if method == "partial_payment":
        first_amount = schedule[0][1]
        remainder = schedule[1][1]
        return (
            f"Pay {currency} {format_number(first_amount)} today and the remaining "
            f"{currency} {format_number(remainder)} on {schedule[1][0].strftime('%d %B %Y')}. "
            f"This completes the full request and keeps the {currency} "
            f"{format_number(minimum)} minimum protected."
        )
    if method == "installments":
        return (
            f"Use {len(schedule)} installments of {currency} "
            f"{format_number(schedule[0][1])}, starting "
            f"{schedule[0][0].strftime('%d %B %Y')}. This leaves at least {currency} "
            f"{format_number(observed_minimum)} available."
        )
    payment_day = schedule[0][0]
    return (
        f"Pay {currency} {format_number(requested)} in full on "
        f"{payment_day.strftime('%d %B %Y')}. Paying earlier would take the balance "
        f"below the {currency} {format_number(minimum)} minimum."
    )


def solve_request(
    request: dict[str, str],
    profile: dict[str, str],
    all_events: list[dict[str, str]],
    all_options: list[dict[str, str]],
    amounts: dict[str, Decimal],
    cancelled: set[str],
    settled_overrides: dict[str, date],
    rates: ExchangeRates,
    payroll: dict[str, dict[str, object]],
) -> dict[str, str]:
    request_date = date.fromisoformat(request["request_date"])
    due_date = date.fromisoformat(request["desired_completion_date"])
    requested = cents(parse_decimal(request["requested_amount"], "requested amount"))
    minimum = cents(parse_decimal(profile["minimum_balance_to_keep"], "minimum balance"))
    events = [row for row in all_events if row["user_id"] == request["user_id"]]
    series = infer_series(events, amounts, request_date)
    dates, balances = build_projection(
        request,
        profile,
        events,
        amounts,
        cancelled,
        settled_overrides,
        series,
        rates,
        payroll,
    )
    amount_safe = max_safe_today(balances, minimum, requested)
    full_date = earliest_safe_date(balances, dates, minimum, requested)
    acceptable = set(filter(None, profile["payment_methods_user_will_consider"].split("|")))

    candidates: list[
        tuple[tuple[object, ...], str, list[tuple[date, Decimal]], tuple[FlexibleChange, ...], Decimal]
    ] = []
    if "full_payment" in acceptable and safe_with_payments(
        balances, dates, minimum, [(request_date, requested)]
    ):
        schedule = [(request_date, requested)]
        minimum_after = minimum_after_plan(balances, dates, schedule)
        candidates.append(
            (
                (0, 0, requested, request_date, 1, ""),
                "full_payment",
                schedule,
                (),
                minimum_after,
            )
        )
    elif "full_payment" in acceptable:
        changes = best_full_payment_changes(
            request,
            profile,
            events,
            amounts,
            cancelled,
            settled_overrides,
            series,
            rates,
            payroll,
            minimum,
            requested,
        )
        if changes:
            changed_dates, changed_balances = build_projection(
                request,
                profile,
                events,
                amounts,
                cancelled,
                settled_overrides,
                series,
                rates,
                payroll,
                changes,
            )
            schedule = [(request_date, requested)]
            minimum_after = minimum_after_plan(changed_balances, changed_dates, schedule)
            candidates.append(
                (
                    (0, 1, requested, request_date, 1, ""),
                    "full_payment",
                    schedule,
                    changes,
                    minimum_after,
                )
            )

    if (
        "partial_payment" in acceptable
        and request["allows_partial_payment"].strip().casefold() == "true"
        and ZERO < amount_safe < requested
        and full_date is not None
        and request_date < full_date <= due_date
    ):
        schedule = [(request_date, amount_safe), (full_date, cents(requested - amount_safe))]
        if safe_with_payments(balances, dates, minimum, schedule):
            candidates.append(
                (
                    (0, 0, requested, request_date, 2, ""),
                    "partial_payment",
                    schedule,
                    (),
                    minimum_after_plan(balances, dates, schedule),
                )
            )

    if (
        "full_payment" in acceptable
        and full_date is not None
        and request_date < full_date <= due_date
    ):
        schedule = [(full_date, requested)]
        candidates.append(
            (
                (0, 0, requested, full_date, 1, ""),
                "wait",
                schedule,
                (),
                minimum_after_plan(balances, dates, schedule),
            )
        )

    if "installments" in acceptable:
        max_months = (
            int(profile["max_installment_months"])
            if profile["max_installment_months"].strip()
            else 0
        )
        for option in payment_option_rows(request["request_id"], all_options):
            if option["payment_method"] != "installments":
                continue
            schedule = option_schedule(option)
            if not schedule or schedule[0][0] < request_date:
                continue
            if schedule[-1][0] > due_date or schedule[-1][0] > dates[-1]:
                continue
            duration_months = (schedule[-1][0] - schedule[0][0]).days / 30.4375
            if max_months <= 0 or duration_months > max_months:
                continue
            if not safe_with_payments(balances, dates, minimum, schedule):
                continue
            total = cents(
                parse_decimal(option["total_payable_amount"], "total payable amount")
            )
            candidates.append(
                (
                    (
                        0,
                        0,
                        total,
                        schedule[0][0],
                        len(schedule),
                        option["payment_option_id"],
                    ),
                    "installments",
                    schedule,
                    (),
                    minimum_after_plan(balances, dates, schedule),
                )
            )

    if candidates:
        _, method, schedule, changes, min_after = min(candidates, key=lambda item: item[0])
        status = (
            "affordable_later"
            if method == "wait"
            else "affordable_now"
            if method == "full_payment" and not changes
            else "affordable_with_plan"
        )
        payment_plan = "|".join(
            f"{day.isoformat()}:{format_money(amount)}" for day, amount in schedule
        )
        change_text = "|".join(change.render() for change in changes) or "none"
        explanation = decision_explanation(
            profile["home_currency"],
            requested,
            minimum,
            method,
            schedule,
            changes,
            amount_safe,
            full_date,
            min_after,
        )
    else:
        method = "not_recommended"
        status = "not_affordable"
        schedule = []
        payment_plan = "none"
        change_text = "none"
        explanation = decision_explanation(
            profile["home_currency"],
            requested,
            minimum,
            method,
            schedule,
            (),
            amount_safe,
            full_date,
            minimum,
        )

    earliest = full_date.isoformat() if full_date else ""
    return {
        "request_id": request["request_id"],
        "amount_safe_to_pay": format_number(amount_safe),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": payment_plan,
        "earliest_date_for_full_payment": earliest,
        "spending_changes_needed": change_text,
        "decision_explanation": explanation,
    }


def validate_predictions(
    predictions: list[dict[str, str]],
    requests: list[dict[str, str]],
    profiles: dict[str, dict[str, str]],
    options: list[dict[str, str]],
) -> None:
    if [row["request_id"] for row in predictions] != [
        row["request_id"] for row in requests
    ]:
        raise ValueError("Output request IDs do not match the input requests in order")
    request_by_id = {row["request_id"]: row for row in requests}
    allowed_statuses = {
        "affordable_now",
        "affordable_with_plan",
        "affordable_later",
        "not_affordable",
    }
    allowed_methods = {
        "full_payment",
        "partial_payment",
        "installments",
        "wait",
        "not_recommended",
    }
    for row in predictions:
        request = request_by_id[row["request_id"]]
        amount = parse_decimal(row["amount_safe_to_pay"], "amount_safe_to_pay")
        requested = parse_decimal(request["requested_amount"], "requested_amount")
        if not ZERO <= amount <= requested:
            raise ValueError(f"Invalid safe amount for {row['request_id']}")
        if row["affordability_status"] not in allowed_statuses:
            raise ValueError(f"Invalid affordability status for {row['request_id']}")
        if row["recommended_payment_method"] not in allowed_methods:
            raise ValueError(f"Invalid payment method for {row['request_id']}")
        if row["recommended_payment_method"] == "not_recommended":
            if row["payment_plan"] != "none":
                raise ValueError(f"Rejected request has a payment plan: {row['request_id']}")
            continue
        if row["payment_plan"] == "none":
            raise ValueError(f"Recommended plan is missing: {row['request_id']}")
        plan = []
        for item in row["payment_plan"].split("|"):
            try:
                day_text, amount_text = item.split(":", 1)
                plan.append((date.fromisoformat(day_text), parse_decimal(amount_text, "plan amount")))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Malformed plan for {row['request_id']}: {item}") from exc
        if plan != sorted(plan, key=lambda payment: payment[0]):
            raise ValueError(f"Plan is not chronological for {row['request_id']}")
        if plan[-1][0] > date.fromisoformat(request["desired_completion_date"]):
            raise ValueError(f"Plan misses the deadline for {row['request_id']}")
        if row["recommended_payment_method"] in {"full_payment", "wait"}:
            if len(plan) != 1 or plan[0][1] != cents(requested):
                raise ValueError(f"Invalid single-payment plan for {row['request_id']}")
        if row["recommended_payment_method"] == "partial_payment":
            if (
                len(plan) != 2
                or plan[0][0] != date.fromisoformat(request["request_date"])
                or plan[0][1] != cents(amount)
                or sum((payment[1] for payment in plan), ZERO) != cents(requested)
                or row["affordability_status"] != "affordable_with_plan"
                or request["allows_partial_payment"].casefold() != "true"
                or row["earliest_date_for_full_payment"] != plan[1][0].isoformat()
            ):
                raise ValueError(f"Invalid partial-payment plan for {row['request_id']}")
        if row["recommended_payment_method"] == "installments":
            matching = False
            for option in payment_option_rows(request["request_id"], options):
                if option["payment_method"] == "installments":
                    if option_schedule(option) == plan:
                        matching = True
                        break
            if not matching:
                raise ValueError(f"Installment plan does not match an offer: {row['request_id']}")
        if row["spending_changes_needed"] != "none":
            changes = row["spending_changes_needed"].split("|")
            if len(changes) > 3 or len(changes) != len(set(changes)):
                raise ValueError(f"Invalid spending-change list for {row['request_id']}")
            for change in changes:
                if not (
                    re.fullmatch(r"stop:event_\d+", change)
                    or re.fullmatch(r"reduce_to:event_\d+:\d+(?:\.\d+)?", change)
                ):
                    raise ValueError(f"Malformed spending change for {row['request_id']}")
        if (
            row["affordability_status"] == "affordable_now"
            and row["earliest_date_for_full_payment"] != request["request_date"]
        ):
            raise ValueError(f"Affordable-now date mismatch for {row['request_id']}")
    if any(list(row) != OUTPUT_COLUMNS for row in predictions):
        raise ValueError("Output columns do not match the required schema")


def run(data_dir: Path, output_path: Path) -> list[dict[str, str]]:
    requests = read_csv(data_dir / "requests.csv")
    profiles_rows = read_csv(data_dir / "financial_profiles.csv")
    events = read_csv(data_dir / "financial_events.csv")
    options = read_csv(data_dir / "request_payment_options.csv")
    messages = read_csv(data_dir / "messages.csv")
    images = read_csv(data_dir / "images.csv")
    rates = ExchangeRates(read_csv(data_dir / "exchange_rates.csv"))
    profiles = {row["user_id"]: row for row in profiles_rows}
    if len(profiles) != len(profiles_rows):
        raise ValueError("Duplicate user IDs in financial_profiles.csv")
    if not requests:
        raise ValueError("requests.csv contains no evaluation requests")

    image_amounts = linked_image_amounts(images)
    amounts, cancelled, settled_overrides = apply_message_overrides(
        events, messages, rates, image_amounts
    )
    payroll = payroll_message_facts(messages)
    predictions = []
    for request in requests:
        profile = profiles.get(request["user_id"])
        if profile is None:
            raise ValueError(f"No financial profile for {request['user_id']}")
        predictions.append(
            solve_request(
                request,
                profile,
                events,
                options,
                amounts,
                cancelled,
                settled_overrides,
                rates,
                payroll,
            )
        )

    validate_predictions(predictions, requests, profiles, options)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(predictions)
    return predictions


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=repository / "dataset")
    parser.add_argument("--output", type=Path, default=repository / "output.csv")
    args = parser.parse_args()
    try:
        predictions = run(args.data_dir.resolve(), args.output.resolve())
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {len(predictions)} predictions to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())