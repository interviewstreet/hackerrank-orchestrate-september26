#!/usr/bin/env python3
"""Deterministic Buy or Wait? financial-planning agent.

The program intentionally uses only the participant-facing dataset and the
standard library.  It treats profiles as the balance at each request date,
then tests every eligible provider plan against a conservative 90-day cash
forecast.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path
from statistics import median
from typing import Iterable


OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]
DAY_ZERO = Decimal("0")
NINETY_DAYS = 90
CASH_STATUSES = {"settled", "pending", "scheduled"}
MONEY_RE = re.compile(r"(?:INR|IDR|ZAR|USD|EUR|Rp|Rs\.?)[\s:]*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value.replace(",", "").strip())


def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def csv_money(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rendered = f"{value:f}".rstrip("0").rstrip(".")
    return rendered or "0"


def currencies_in_text(text: str) -> list[Decimal]:
    return [Decimal(match.replace(",", "")) for match in MONEY_RE.findall(text)]


@dataclass(frozen=True)
class Flow:
    when: date
    amount: Decimal
    category: str
    direction: str
    source: str
    series_key: tuple[str, str, str] | None = None


@dataclass
class Series:
    key: tuple[str, str, str]
    category: str
    direction: str
    amount: Decimal
    interval_days: int
    next_date: date
    representative_event: dict[str, str]


@dataclass
class Candidate:
    method: str
    payments: list[tuple[date, Decimal]]
    changes: list[str]
    option_id: str
    total: Decimal
    status: str

    @property
    def completion(self) -> date:
        return self.payments[-1][0]


class FinancialAgent:
    def __init__(self, dataset: Path):
        self.dataset = dataset
        self.profiles = {row["user_id"]: row for row in read_rows(dataset / "financial_profiles.csv")}
        self.events = read_rows(dataset / "financial_events.csv")
        self.messages = read_rows(dataset / "messages.csv")
        self.options = read_rows(dataset / "request_payment_options.csv")
        self.images = read_rows(dataset / "images.csv")
        self.rates = read_rows(dataset / "exchange_rates.csv")
        self.events_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.options_by_request: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.messages_by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.images_by_event = {row["related_event_id"]: row["image_id"] for row in self.images if row["related_event_id"]}
        self.amount_cache: dict[str, Decimal | None] = {}
        self.rate_map = {(row["rate_date"], row["from_currency"], row["to_currency"]): decimal(row["rate"]) for row in self.rates}
        for event in self.events:
            self.events_by_user[event["user_id"]].append(event)
        for option in self.options:
            self.options_by_request[option["request_id"]].append(option)
        for message in self.messages:
            self.messages_by_user[message["user_id"]].append(message)

    def image_amount(self, event: dict[str, str]) -> Decimal | None:
        """Extract a blank event amount from its supplied PNG without treating it as zero."""
        event_id = event["event_id"]
        if event_id in self.amount_cache:
            return self.amount_cache[event_id]
        image_id = self.images_by_event.get(event_id)
        if not image_id:
            self.amount_cache[event_id] = None
            return None
        image_path = self.dataset / "media" / "images" / f"{image_id}.png"
        try:
            text = subprocess.run(
                ["tesseract", str(image_path), "stdout"], check=True, text=True,
                capture_output=True, timeout=20,
            ).stdout
            totals = re.findall(r"(?:grand\s+total|total\s+(?:paid|due)?|amount\s+due)[^0-9]{0,35}([0-9][0-9,]*(?:\.\d{1,2})?)", text, re.I)
            values = totals or re.findall(r"\b([0-9][0-9,]{2,}(?:\.\d{1,2})?)\b", text)
            result = Decimal(values[-1].replace(",", "")) if values else None
        except (OSError, subprocess.SubprocessError, DecimalException):
            result = None
        self.amount_cache[event_id] = result
        return result

    def convert(self, amount: Decimal, from_currency: str, to_currency: str, on: date) -> Decimal:
        if from_currency == to_currency:
            return amount
        candidates = [(parse_date(key[0]), rate) for key, rate in self.rate_map.items()
                      if key[1] == from_currency and key[2] == to_currency and parse_date(key[0]) <= on]
        if candidates:
            return amount * max(candidates, key=lambda item: item[0])[1]
        inverse = [(parse_date(key[0]), rate) for key, rate in self.rate_map.items()
                   if key[1] == to_currency and key[2] == from_currency and parse_date(key[0]) <= on]
        if inverse:
            return amount / max(inverse, key=lambda item: item[0])[1]
        raise ValueError(f"No exchange rate for {from_currency}->{to_currency} on {on}")

    def event_amount(self, event: dict[str, str], home_currency: str, on: date) -> Decimal | None:
        raw = decimal(event.get("amount")) or self.image_amount(event)
        if raw is None:
            return None
        return self.convert(raw, event["currency"], home_currency, on)

    @staticmethod
    def cash_effect(event: dict[str, str]) -> bool:
        return event["status"] in CASH_STATUSES and event["event_type"] != "investment_valuation"

    def relevant_events(self, user_id: str, home_currency: str, horizon: date) -> list[dict[str, str]]:
        result = []
        for event in self.events_by_user[user_id]:
            if not self.cash_effect(event):
                continue
            if event["status"] == "pending" and event["direction"] == "credit":
                continue
            if event["status"] == "scheduled" and event["direction"] == "credit" and event["event_type"] not in {"income"}:
                continue
            if parse_date(event["settlement_date"] or event["event_date"]) <= horizon:
                result.append(event)
        return result

    def salary_overrides(self, user_id: str, request_date: date, home_currency: str) -> dict[str, object]:
        messages = sorted(self.messages_by_user[user_id], key=lambda row: row["sent_at"])
        outcome: dict[str, object] = {"ended": False, "amount": None, "effective": None, "one_time": False}
        for message in messages:
            if parse_date(message["sent_at"]) > request_date:
                continue
            text = message["message_text"].lower()
            if any(term in text for term in ("employment has ended", "contract has ended", "no off-season", "has ended")):
                outcome["ended"] = True
            if not any(term in text for term in ("salary", "payroll", "gaji", "penggajian")):
                continue
            amounts = currencies_in_text(message["message_text"])
            dates = [parse_date(found) for found in DATE_RE.findall(message["message_text"])]
            if amounts:
                outcome["amount"] = self.convert(amounts[0], home_currency, home_currency, request_date)
            if dates:
                outcome["effective"] = dates[-1]
            elif "next payroll" in text or "berikutnya" in text:
                outcome["one_time"] = "temporary" in text or "reduced" in text or "sementara" in text
        return outcome

    def build_series(self, user_id: str, request_date: date, home_currency: str) -> list[Series]:
        historical: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        protected_categories = set(filter(None, self.profiles[user_id]["expense_categories_to_protect"].split("|")))
        for event in self.relevant_events(user_id, home_currency, request_date):
            settled = parse_date(event["settlement_date"] or event["event_date"])
            if settled <= request_date and event["status"] == "settled":
                historical[(event["event_type"], event["category"], event["direction"])].append(event)
        result: list[Series] = []
        overrides = self.salary_overrides(user_id, request_date, home_currency)
        for key, rows in historical.items():
            # A repeated card purchase is not automatically a future obligation.
            # Infer variable expense recurrence only for categories the user has
            # explicitly protected; subscriptions and debt commitments remain
            # recurring regardless of their category.
            if key[0] == "expense" and key[1] not in protected_categories:
                continue
            rows.sort(key=lambda item: item["settlement_date"] or item["event_date"])
            dates = [parse_date(item["settlement_date"] or item["event_date"]) for item in rows]
            if len(dates) < 2:
                continue
            gaps = [(right - left).days for left, right in zip(dates, dates[1:]) if 3 <= (right - left).days <= 45]
            if not gaps:
                continue
            interval = int(round(median(gaps)))
            if interval > 45:
                continue
            amounts = [self.event_amount(item, home_currency, dates[index]) for index, item in enumerate(rows[-4:], len(rows) - min(4, len(rows)))]
            known_amounts = [amount for amount in amounts if amount is not None]
            if not known_amounts:
                continue
            direction = key[2]
            amount = min(known_amounts[-3:]) if direction == "credit" else max(known_amounts[-3:])
            last_date = dates[-1]
            next_date = last_date + timedelta(days=interval)
            if key[0] == "income" and key[1] == "salary":
                if overrides["ended"]:
                    continue
                if overrides["amount"] is not None:
                    amount = overrides["amount"]  # type: ignore[assignment]
                if overrides["effective"] is not None:
                    next_date = overrides["effective"]  # type: ignore[assignment]
                    while next_date <= request_date:
                        next_date += timedelta(days=interval)
            result.append(Series(key, key[1], direction, amount, interval, next_date, rows[-1]))
        return result

    def forecast(self, request: dict[str, str], changes: Iterable[str] = ()) -> tuple[dict[date, Decimal], list[Series]]:
        profile = self.profiles[request["user_id"]]
        home = profile["home_currency"]
        start = parse_date(request["request_date"])
        end = start + timedelta(days=NINETY_DAYS)
        flows: dict[date, Decimal] = defaultdict(lambda: DAY_ZERO)
        series = self.build_series(request["user_id"], start, home)
        altered = set(changes)
        recurring_dates: set[tuple[date, tuple[str, str, str]]] = set()
        for current in series:
            next_date = current.next_date
            action = next((item for item in altered if item.split(":")[1] == current.representative_event["event_id"]), None)
            while next_date <= end:
                recurring_dates.add((next_date, current.key))
                amount = current.amount
                if action and action.startswith("stop:"):
                    amount = DAY_ZERO
                elif action and action.startswith("reduce_to:"):
                    amount = decimal(action.rsplit(":", 1)[1]) or DAY_ZERO
                flows[next_date] += amount if current.direction == "credit" else -amount
                next_date += timedelta(days=current.interval_days)
        for event in self.relevant_events(request["user_id"], home, end):
            when = parse_date(event["settlement_date"] or event["event_date"])
            if when < start:
                continue
            key = (event["event_type"], event["category"], event["direction"])
            if event["status"] == "settled" and (when, key) in recurring_dates:
                continue
            amount = self.event_amount(event, home, when)
            if amount is None:
                continue
            flows[when] += amount if event["direction"] == "credit" else -amount
        return flows, series

    @staticmethod
    def timeline(balance: Decimal, start: date, flows: dict[date, Decimal], payments: list[tuple[date, Decimal]]) -> dict[date, Decimal]:
        payment_map: dict[date, Decimal] = defaultdict(lambda: DAY_ZERO)
        for when, amount in payments:
            payment_map[when] += amount
        result: dict[date, Decimal] = {}
        current = balance
        end = start + timedelta(days=NINETY_DAYS)
        for offset in range(NINETY_DAYS + 1):
            current_day = start + timedelta(days=offset)
            current += flows.get(current_day, DAY_ZERO) - payment_map[current_day]
            result[current_day] = current
        return result

    def safe(self, request: dict[str, str], payments: list[tuple[date, Decimal]], changes: Iterable[str] = ()) -> bool:
        profile = self.profiles[request["user_id"]]
        start = parse_date(request["request_date"])
        timeline = self.timeline(decimal(profile["current_available_balance"]) or DAY_ZERO, start, self.forecast(request, changes)[0], payments)
        return min(timeline.values()) >= (decimal(profile["minimum_balance_to_keep"]) or DAY_ZERO)

    def safe_today_amount(self, request: dict[str, str]) -> Decimal:
        profile = self.profiles[request["user_id"]]
        start = parse_date(request["request_date"])
        baseline = self.timeline(decimal(profile["current_available_balance"]) or DAY_ZERO, start, self.forecast(request)[0], [])
        capacity = min(baseline.values()) - (decimal(profile["minimum_balance_to_keep"]) or DAY_ZERO)
        return max(DAY_ZERO, min(capacity, decimal(request["requested_amount"]) or DAY_ZERO))

    def earliest_full_date(self, request: dict[str, str]) -> date | None:
        amount = decimal(request["requested_amount"]) or DAY_ZERO
        start = parse_date(request["request_date"])
        for offset in range(NINETY_DAYS + 1):
            candidate = start + timedelta(days=offset)
            if self.safe(request, [(candidate, amount)]):
                return candidate
        return None

    def permitted_changes(self, request: dict[str, str], series: list[Series]) -> list[str]:
        profile = self.profiles[request["user_id"]]
        permitted_reduce = set(filter(None, profile["expense_categories_user_is_willing_to_reduce"].split("|")))
        permitted_stop = set(filter(None, profile["expense_categories_user_is_willing_to_stop"].split("|")))
        choices: list[tuple[Decimal, str]] = []
        for current in series:
            event = current.representative_event
            if current.direction != "debit" or event["category"] in set(profile["expense_categories_to_protect"].split("|")):
                continue
            flexibility = event["flexibility"]
            if flexibility in {"stoppable", "reducible_or_stoppable"} and current.category in permitted_stop:
                choices.append((current.amount, f"stop:{event['event_id']}"))
            minimum = decimal(event.get("minimum_allowed_amount"))
            if flexibility in {"reducible", "reducible_or_stoppable"} and minimum is not None and current.category in permitted_reduce:
                choices.append((current.amount - minimum, f"reduce_to:{event['event_id']}:{csv_money(minimum)}"))
        choices.sort(key=lambda item: (-item[0], item[1]))
        return [change for _, change in choices]

    def payment_options(self, request: dict[str, str]) -> list[tuple[str, list[tuple[date, Decimal]], str, Decimal]]:
        profile = self.profiles[request["user_id"]]
        accepted = set(profile["payment_methods_user_will_consider"].split("|"))
        max_months = decimal(profile["max_installment_months"])
        plans = []
        for option in self.options_by_request[request["request_id"]]:
            method = option["payment_method"]
            if method not in accepted:
                continue
            count = int(option["number_of_payments"])
            if method == "installments" and max_months is not None and count > int(max_months):
                continue
            first = parse_date(option["first_payment_date"])
            frequency = int(option["payment_frequency_days"] or 0)
            amount = decimal(option["payment_amount"]) or DAY_ZERO
            payments = [(first + timedelta(days=frequency * index), amount) for index in range(count)]
            total = decimal(option["total_payable_amount"]) or sum((item[1] for item in payments), DAY_ZERO)
            plans.append((method, payments, option["payment_option_id"], total))
        return plans

    def choose(self, request: dict[str, str]) -> dict[str, str]:
        profile = self.profiles[request["user_id"]]
        home = profile["home_currency"]
        start = parse_date(request["request_date"])
        deadline = parse_date(request["desired_completion_date"])
        requested = decimal(request["requested_amount"]) or DAY_ZERO
        safe_today = self.safe_today_amount(request)
        earliest = self.earliest_full_date(request)
        candidates: list[Candidate] = []
        for method, payments, option_id, total in self.payment_options(request):
            if payments[-1][0] <= deadline and self.safe(request, payments):
                status = "affordable_now" if method == "full_payment" and payments[0][0] == start else "affordable_with_plan"
                candidates.append(Candidate(method, payments, [], option_id, total, status))
        accepted = set(profile["payment_methods_user_will_consider"].split("|"))
        if (request["allows_partial_payment"].lower() == "true" and "partial_payment" in accepted and
                DAY_ZERO < safe_today < requested and earliest is not None and earliest <= deadline):
            payments = [(start, safe_today), (earliest, requested - safe_today)]
            if self.safe(request, payments):
                candidates.append(Candidate("partial_payment", payments, [], "", requested, "affordable_with_plan"))
        if "full_payment" in accepted and earliest is not None and earliest > start and earliest <= deadline:
            candidates.append(Candidate("wait", [(earliest, requested)], [], "", requested, "affordable_later"))

        flows, series = self.forecast(request)
        changes = self.permitted_changes(request, series)
        for size in range(1, min(3, len(changes)) + 1):
            for set_of_changes in combinations(changes, size):
                if len({item.split(":")[1] for item in set_of_changes}) != len(set_of_changes):
                    continue
                for method, payments, option_id, total in self.payment_options(request):
                    if payments[-1][0] <= deadline and self.safe(request, payments, set_of_changes):
                        candidates.append(Candidate(method, payments, list(set_of_changes), option_id, total, "affordable_with_plan"))
                if "full_payment" in accepted and self.safe(request, [(start, requested)], set_of_changes):
                    candidates.append(Candidate("full_payment", [(start, requested)], list(set_of_changes), "", requested, "affordable_with_plan"))

        if candidates:
            candidates.sort(key=lambda plan: (
                0 if plan.completion <= deadline else 1, len(plan.changes), plan.total,
                plan.payments[0][0], len(plan.payments), plan.option_id or "~",
            ))
            choice = candidates[0]
            plan_text = "|".join(f"{when.isoformat()}:{csv_money(amount)}" for when, amount in choice.payments)
            change_text = "|".join(choice.changes) if choice.changes else "none"
            earliest_text = earliest.isoformat() if earliest else ""
            explanation = self.explain(choice, home, requested, profile, earliest)
            return {
                "request_id": request["request_id"], "amount_safe_to_pay": csv_money(safe_today),
                "affordability_status": choice.status, "recommended_payment_method": choice.method,
                "payment_plan": plan_text, "earliest_date_for_full_payment": earliest_text,
                "spending_changes_needed": change_text, "decision_explanation": explanation,
            }
        explanation = f"Do not proceed by {deadline.isoformat()}. No eligible option keeps the {home} {csv_money(decimal(profile['minimum_balance_to_keep']) or DAY_ZERO)} minimum protected."
        return {
            "request_id": request["request_id"], "amount_safe_to_pay": csv_money(safe_today),
            "affordability_status": "not_affordable", "recommended_payment_method": "not_recommended",
            "payment_plan": "none", "earliest_date_for_full_payment": "", "spending_changes_needed": "none",
            "decision_explanation": explanation,
        }

    @staticmethod
    def explain(choice: Candidate, currency: str, requested: Decimal, profile: dict[str, str], earliest: date | None) -> str:
        minimum = csv_money(decimal(profile["minimum_balance_to_keep"]) or DAY_ZERO)
        if choice.method == "wait":
            return f"Wait until {choice.payments[0][0].isoformat()} to pay {currency} {csv_money(requested)} while preserving the {currency} {minimum} minimum."
        if choice.method == "installments":
            return f"Use {len(choice.payments)} installments starting {choice.payments[0][0].isoformat()}; the 90-day forecast preserves the {currency} {minimum} minimum."
        if choice.method == "partial_payment":
            return f"Pay {currency} {csv_money(choice.payments[0][1])} today and the remainder on {choice.payments[-1][0].isoformat()}, preserving the minimum balance."
        if choice.changes:
            return f"Apply the permitted flexible-spending changes, then pay {currency} {csv_money(requested)} while preserving the {currency} {minimum} minimum."
        return f"Pay {currency} {csv_money(requested)} as scheduled; the 90-day forecast preserves the {currency} {minimum} minimum."


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Buy or Wait? predictions.")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[1] / "dataset")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "output.csv")
    parser.add_argument("--requests", type=Path, help="Override the requests CSV (used by evaluation).")
    args = parser.parse_args()
    agent = FinancialAgent(args.dataset)
    requests = read_rows(args.requests or args.dataset / "requests.csv")
    rows = [agent.choose(request) for request in requests]
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
