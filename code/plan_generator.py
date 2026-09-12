"""Build every spec-allowed payment candidate. Never invent a payment option."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from forecast import (
    RecurringStream,
    amount_safe_to_pay,
    earliest_full_payment_date,
    forecast_90_days,
    parse_date,
    split_categories,
    to_number,
)
from models import CandidatePlan, Payment, SpendingChange, option_id_sort_key


IMMEDIATE_METHODS = frozenset({"full_payment", "partial_payment", "installments"})
FLEXIBLE = frozenset({"reducible", "stoppable", "reducible_or_stoppable"})
MAX_SPENDING_CHANGES = 3


def parse_methods(raw: Any) -> set[str]:
    return split_categories(raw)


def parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    return text in {"true", "1", "yes"}


def extra_payments_from(payments: list[Payment]) -> dict[date, float]:
    extras: dict[date, float] = {}
    for payment in payments:
        extras[payment.pay_date] = extras.get(payment.pay_date, 0.0) + payment.amount
    return extras


def plan_is_safe(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    payments: list[Payment],
    spending_changes: list[SpendingChange],
    exchange_rates: pd.DataFrame | None,
) -> bool:
    result = forecast_90_days(
        request,
        profile,
        events,
        extra_payments=extra_payments_from(payments),
        spending_changes=spending_changes,
        exchange_rates=exchange_rates,
    )
    return result.is_safe


def installment_schedule(option: pd.Series) -> list[Payment]:
    first = parse_date(option["first_payment_date"])
    if first is None:
        return []
    count = int(to_number(option["number_of_payments"], "number_of_payments"))
    amount = to_number(option["payment_amount"], "payment_amount")
    freq_raw = option["payment_frequency_days"]
    freq = 0 if pd.isna(freq_raw) else int(to_number(freq_raw, "payment_frequency_days"))
    payments = []
    for index in range(count):
        pay_date = first if freq == 0 else first + timedelta(days=index * freq)
        payments.append(Payment(pay_date, amount))
    return payments


def installment_span_months(option: pd.Series) -> float:
    count = int(to_number(option["number_of_payments"], "number_of_payments"))
    freq_raw = option["payment_frequency_days"]
    if pd.isna(freq_raw) or count <= 1:
        return 1.0
    freq = to_number(freq_raw, "payment_frequency_days")
    return ((count - 1) * freq) / 30.0


def user_max_installment_months(profile: pd.Series) -> float | None:
    raw = profile.get("max_installment_months")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text:
        return None
    return to_number(raw, "max_installment_months")


def eligible_spending_actions(
    streams: list[RecurringStream],
    profile: pd.Series,
) -> list[SpendingChange]:
    """Flexible recurring debits the user is willing to change. Max 3 later."""
    protected = split_categories(profile.get("expense_categories_to_protect"))
    can_stop = split_categories(profile.get("expense_categories_user_is_willing_to_stop"))
    can_reduce = split_categories(
        profile.get("expense_categories_user_is_willing_to_reduce")
    )
    actions: list[SpendingChange] = []
    seen_event_ids: set[str] = set()
    for stream in streams:
        if stream.direction != "debit":
            continue
        if stream.flexibility not in FLEXIBLE:
            continue
        if stream.category in protected:
            continue
        if not stream.source_event_id or stream.source_event_id in seen_event_ids:
            continue
        seen_event_ids.add(stream.source_event_id)

        if stream.flexibility in {"stoppable", "reducible_or_stoppable"} and stream.category in can_stop:
            actions.append(SpendingChange("stop", stream.source_event_id))
        if (
            stream.flexibility in {"reducible", "reducible_or_stoppable"}
            and stream.category in can_reduce
            and stream.minimum_allowed_amount is not None
            and stream.minimum_allowed_amount < stream.amount
        ):
            actions.append(
                SpendingChange(
                    "reduce",
                    stream.source_event_id,
                    new_amount=stream.minimum_allowed_amount,
                )
            )
    return actions


def spending_change_sets(actions: list[SpendingChange]) -> list[list[SpendingChange]]:
    """Empty set plus greedy 1–3 actions. Stop and reduce of the same event stay exclusive."""
    sets: list[list[SpendingChange]] = [[]]
    used_events: set[str] = set()
    greedy: list[SpendingChange] = []
    # Prefer a stop over a reduce of the same event; keep first occurrence of each event.
    for action in actions:
        if action.event_id in used_events:
            continue
        if len(greedy) >= MAX_SPENDING_CHANGES:
            break
        greedy.append(action)
        used_events.add(action.event_id)
        sets.append(list(greedy))

    for action in actions:
        singleton = [action]
        if singleton not in sets:
            sets.append(singleton)
    return sets


def _evaluate(
    method: str,
    payments: list[Payment],
    spending_changes: list[SpendingChange],
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    exchange_rates: pd.DataFrame | None,
    deadline: date,
    accepted_methods: set[str],
    payment_option_id: str | None = None,
    total_paid: float | None = None,
    notes: str = "",
) -> CandidatePlan:
    last = max((payment.pay_date for payment in payments), default=None)
    meets_deadline = last is not None and last <= deadline
    if method in IMMEDIATE_METHODS:
        eligible_method = method in accepted_methods
    elif method == "wait":
        eligible_method = "full_payment" in accepted_methods
    else:
        eligible_method = True

    safe = False
    if payments:
        safe = plan_is_safe(
            request, profile, events, payments, spending_changes, exchange_rates
        )
    eligible = eligible_method and safe and bool(payments)
    return CandidatePlan(
        method=method,
        payments=payments,
        spending_changes=list(spending_changes),
        payment_option_id=payment_option_id,
        total_paid=sum(payment.amount for payment in payments) if total_paid is None else total_paid,
        meets_deadline=meets_deadline,
        is_safe=safe,
        eligible=eligible,
        notes=notes,
    )


def generate_candidates(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    payment_options: pd.DataFrame,
    exchange_rates: pd.DataFrame | None = None,
) -> tuple[list[CandidatePlan], float, date | None]:
    request_date = parse_date(request["request_date"])
    deadline = parse_date(request["desired_completion_date"])
    if request_date is None or deadline is None:
        raise ValueError("request_date or desired_completion_date is missing")

    requested = to_number(request["requested_amount"], "requested_amount")
    accepted = parse_methods(profile.get("payment_methods_user_will_consider"))
    allows_partial = parse_bool(request.get("allows_partial_payment"))
    max_months = user_max_installment_months(profile)

    safe_today, unpaid_forecast = amount_safe_to_pay(
        request, profile, events, exchange_rates=exchange_rates
    )
    earliest = earliest_full_payment_date(
        request, profile, events, exchange_rates=exchange_rates
    )
    change_sets = spending_change_sets(
        eligible_spending_actions(unpaid_forecast.recurring_streams, profile)
    )

    candidates: list[CandidatePlan] = []

    # 1. Full payment today, with and without permitted spending changes.
    full_payments = [Payment(request_date, requested)]
    for changes in change_sets:
        candidates.append(
            _evaluate(
                "full_payment",
                full_payments,
                changes,
                request,
                profile,
                events,
                exchange_rates,
                deadline,
                accepted,
                notes="full payment on request_date",
            )
        )

    # 2. Partial payment: exact spec rules. amount_safe_to_pay is before spending changes.
    if (
        allows_partial
        and "partial_payment" in accepted
        and 0 < safe_today < requested
        and earliest is not None
        and earliest <= deadline
    ):
        remainder = requested - safe_today
        partial_payments = [
            Payment(request_date, safe_today),
            Payment(earliest, remainder),
        ]
        candidates.append(
            _evaluate(
                "partial_payment",
                partial_payments,
                [],
                request,
                profile,
                events,
                exchange_rates,
                deadline,
                accepted,
                total_paid=requested,
                notes="two-part plan using amount_safe_to_pay",
            )
        )

    # 3. Every supplied installment option. Do not invent dates, fees, or counts.
    request_id = str(request["request_id"])
    matching_options = payment_options[payment_options["request_id"] == request_id]
    for option in matching_options.itertuples(index=False):
        option_series = pd.Series(option._asdict()) if hasattr(option, "_asdict") else pd.Series(option)
        method = str(option_series["payment_method"])
        if method != "installments":
            continue
        if "installments" not in accepted:
            continue
        if max_months is None:
            continue
        if installment_span_months(option_series) > max_months + 0.01:
            continue
        schedule = installment_schedule(option_series)
        if not schedule:
            continue
        total_payable = to_number(
            option_series["total_payable_amount"], "total_payable_amount"
        )
        option_id = str(option_series["payment_option_id"])
        for changes in change_sets:
            candidates.append(
                _evaluate(
                    "installments",
                    schedule,
                    changes,
                    request,
                    profile,
                    events,
                    exchange_rates,
                    deadline,
                    accepted,
                    payment_option_id=option_id,
                    total_paid=total_payable,
                    notes=f"supplied option {option_id}",
                )
            )

    # 4. Wait until the earliest safe full-payment date (later than today).
    if earliest is not None and earliest > request_date:
        wait_payments = [Payment(earliest, requested)]
        for changes in change_sets:
            # Wait capacity is measured without spending changes; only the empty
            # change-set is a true wait. Extra change-sets still tested if they help.
            candidates.append(
                _evaluate(
                    "wait",
                    wait_payments,
                    changes,
                    request,
                    profile,
                    events,
                    exchange_rates,
                    deadline,
                    accepted,
                    total_paid=requested,
                    notes="wait for earliest safe full payment",
                )
            )

    # 6. Not recommended fallback (never eligible as a chosen payment).
    candidates.append(
        CandidatePlan(
            method="not_recommended",
            payments=[],
            spending_changes=[],
            payment_option_id=None,
            total_paid=float("inf"),
            meets_deadline=False,
            is_safe=False,
            eligible=False,
            notes="fallback when no safe eligible plan exists",
        )
    )
    return candidates, safe_today, earliest


def rank_key(plan: CandidatePlan) -> tuple:
    """Exact ranking from the problem statement."""
    return (
        0 if plan.meets_deadline else 1,
        0 if not plan.spending_changes else 1,
        plan.total_paid,
        plan.start_date or date.max,
        plan.payment_count,
        option_id_sort_key(plan.payment_option_id),
    )
