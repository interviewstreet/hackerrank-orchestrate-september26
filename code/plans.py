"""Candidate payment plan generation, ranking, explanation, and decision engine."""

from __future__ import annotations

import math
from datetime import date, timedelta
from itertools import combinations
from typing import Any

import pandas as pd

from data import parse_date, to_number
from forecast import (
    amount_safe_to_pay,
    earliest_full_payment_date,
    forecast_90_days,
)
from models import (
    CandidatePlan,
    Decision,
    Payment,
    SpendingChange,
    _format_money,
    format_payment_plan,
    format_spending_changes,
    option_id_sort_key,
)


def parse_methods(raw: Any) -> set[str]:
    """Parse comma-separated accepted payment methods into lowercase tokens."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return set()
    return {part.strip().lower() for part in str(raw).split(",") if part.strip()}


def parse_bool(raw: Any) -> bool:
    """Parse boolean flag from dataset."""
    if isinstance(raw, bool):
        return raw
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    return str(raw).strip().lower() in {"true", "1", "yes", "t"}


def user_max_installment_months(profile: pd.Series) -> float | None:
    """Read max_installment_months; None if blank (meaning user will not consider installments)."""
    raw = profile.get("max_installment_months")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        val = float(text)
        return val if val > 0 else None
    except ValueError:
        return None


def installment_schedule(option: pd.Series) -> list[Payment]:
    """Build payment schedule from option fields without inventing dates or amounts."""
    raw_start = option.get("first_payment_date")
    start = parse_date(raw_start)
    if start is None:
        return []
    raw_count = option.get("number_of_payments")
    if raw_count is None or (isinstance(raw_count, float) and pd.isna(raw_count)):
        raw_count = option.get("installment_count", 0)
    count = int(round(to_number(raw_count, "number_of_payments")))

    raw_interval = option.get("payment_frequency_days")
    if raw_interval is None or (isinstance(raw_interval, float) and pd.isna(raw_interval)):
        raw_interval = option.get("installment_interval_days", 0)
    interval_days = int(round(to_number(raw_interval, "payment_frequency_days")))

    raw_amt = option.get("payment_amount")
    if raw_amt is None or (isinstance(raw_amt, float) and pd.isna(raw_amt)):
        raw_amt = option.get("installment_amount", 0.0)
    each_amt = to_number(raw_amt, "payment_amount")

    payments: list[Payment] = []
    current = start
    for _ in range(count):
        payments.append(Payment(current, each_amt))
        current = current + timedelta(days=interval_days)
    return payments


def installment_span_months(option: pd.Series) -> float:
    """Effective span in months of an installment schedule."""
    raw_count = option.get("number_of_payments")
    if raw_count is None or (isinstance(raw_count, float) and pd.isna(raw_count)):
        raw_count = option.get("installment_count", 0)
    count = int(round(to_number(raw_count, "number_of_payments")))

    raw_interval = option.get("payment_frequency_days")
    if raw_interval is None or (isinstance(raw_interval, float) and pd.isna(raw_interval)):
        raw_interval = option.get("installment_interval_days", 0)
    interval_days = int(round(to_number(raw_interval, "payment_frequency_days")))

    total_days = max(0, (count - 1) * interval_days)
    return total_days / 30.0


def eligible_spending_actions(
    streams: list[Any], profile: pd.Series
) -> list[SpendingChange]:
    """Find stopping/reducing actions permitted by user preferences."""
    user_reductions = parse_methods(
        profile.get("spending_categories_user_will_reduce")
    )
    protected = parse_methods(profile.get("protected_spending_categories"))
    actions: list[SpendingChange] = []
    seen: set[str] = set()

    for stream in streams:
        if stream.direction != "debit":
            continue
        if not stream.source_event_id:
            continue
        if stream.source_event_id in seen:
            continue
        cat = stream.category.lower()
        if cat in protected:
            continue
        if cat not in user_reductions:
            continue

        if stream.flexibility == "stoppable":
            seen.add(stream.source_event_id)
            actions.append(SpendingChange("stop", stream.source_event_id))
        elif stream.flexibility == "reducible":
            min_allowed = stream.minimum_allowed_amount
            if min_allowed is not None and min_allowed < stream.amount:
                seen.add(stream.source_event_id)
                actions.append(
                    SpendingChange("reduce", stream.source_event_id, min_allowed)
                )
    return actions


def spending_change_sets(
    actions: list[SpendingChange],
) -> list[list[SpendingChange]]:
    """Generate combinations of up to 3 eligible spending changes."""
    combos: list[list[SpendingChange]] = [[]]
    max_k = min(3, len(actions))
    for k in range(1, max_k + 1):
        for subset in combinations(actions, k):
            combos.append(list(subset))
    return combos


def _evaluate(
    method: str,
    payments: list[Payment],
    spending_changes: list[SpendingChange],
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    exchange_rates: pd.DataFrame | None,
    deadline: date,
    accepted: set[str],
    option_id: str | None = None,
    total_paid: float | None = None,
    notes: str = "",
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> CandidatePlan:
    """Simulate a candidate plan across 90 days and verify safety and deadline constraints."""
    if total_paid is None:
        total_paid = sum(p.amount for p in payments)

    eligible = method in accepted
    if not payments:
        return CandidatePlan(
            method=method,
            payments=[],
            spending_changes=spending_changes,
            payment_option_id=option_id,
            total_paid=0.0,
            meets_deadline=False,
            is_safe=False,
            eligible=eligible,
            notes=notes,
        )

    last_payment_date = max(p.pay_date for p in payments)
    meets_deadline = last_payment_date <= deadline

    extra: dict[date, float] = {}
    for p in payments:
        extra[p.pay_date] = extra.get(p.pay_date, 0.0) + p.amount
    forecast = forecast_90_days(
        request,
        profile,
        events,
        spending_changes=spending_changes or None,
        exchange_rates=exchange_rates,
        extra_payments=extra,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )

    return CandidatePlan(
        method=method,
        payments=payments,
        spending_changes=spending_changes,
        payment_option_id=option_id,
        total_paid=total_paid,
        meets_deadline=meets_deadline,
        is_safe=forecast.is_safe,
        eligible=eligible,
        notes=notes,
    )


def generate_candidates(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    payment_options: pd.DataFrame,
    exchange_rates: pd.DataFrame | None = None,
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[CandidatePlan], float, date | None]:
    """Generate all candidate plans for a request."""
    request_date = parse_date(request["request_date"])
    deadline = parse_date(request["desired_completion_date"])
    if request_date is None or deadline is None:
        raise ValueError("request_date or desired_completion_date is missing")

    requested = to_number(request["requested_amount"], "requested_amount")
    accepted = parse_methods(profile.get("payment_methods_user_will_consider"))
    allows_partial = parse_bool(request.get("allows_partial_payment"))
    max_months = user_max_installment_months(profile)

    safe_today, unpaid_forecast = amount_safe_to_pay(
        request,
        profile,
        events,
        exchange_rates=exchange_rates,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )
    earliest = earliest_full_payment_date(
        request,
        profile,
        events,
        exchange_rates=exchange_rates,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )
    change_sets = spending_change_sets(
        eligible_spending_actions(unpaid_forecast.recurring_streams, profile)
    )

    candidates: list[CandidatePlan] = []

    # 1. Full payment today
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
                blank_amounts=blank_amounts,
                confirmed_incomes=confirmed_incomes,
                cancelled_events=cancelled_events,
                amended_events=amended_events,
            )
        )

    # 2. Partial payment
    if (
        allows_partial
        and "partial_payment" in accepted
        and 0 < safe_today < requested
        and earliest is not None
        and earliest <= deadline
    ):
        remainder = round(requested - safe_today, 2)
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
                blank_amounts=blank_amounts,
                confirmed_incomes=confirmed_incomes,
                cancelled_events=cancelled_events,
                amended_events=amended_events,
            )
        )

    # 3. Supplied installment options
    request_id = str(request["request_id"])
    if payment_options is not None and not payment_options.empty and "request_id" in payment_options.columns:
        matching_options = payment_options[payment_options["request_id"] == request_id]
    else:
        matching_options = pd.DataFrame()

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
                    option_id=option_id,
                    total_paid=total_payable,
                    notes=f"option {option_id}",
                    blank_amounts=blank_amounts,
                    confirmed_incomes=confirmed_incomes,
                    cancelled_events=cancelled_events,
                    amended_events=amended_events,
                )
            )

    # 4. Wait until earliest safe date
    if earliest is not None and "wait" in accepted:
        wait_payments = [Payment(earliest, requested)]
        candidates.append(
            _evaluate(
                "wait",
                wait_payments,
                [],
                request,
                profile,
                events,
                exchange_rates,
                deadline,
                accepted,
                total_paid=requested,
                notes=f"wait until {earliest.isoformat()}",
                blank_amounts=blank_amounts,
                confirmed_incomes=confirmed_incomes,
                cancelled_events=cancelled_events,
                amended_events=amended_events,
            )
        )

    # 5. Not recommended fallback
    candidates.append(
        CandidatePlan(
            method="not_recommended",
            payments=[],
            spending_changes=[],
            payment_option_id=None,
            total_paid=0.0,
            meets_deadline=False,
            is_safe=False,
            eligible=True,
            notes="fallback",
        )
    )

    return candidates, safe_today, earliest


def rank_key(plan: CandidatePlan) -> tuple[int, int, float, date, int, tuple[int, str]]:
    """
    Candidate ranking key per problem_statement.md:
    1. Complete full request by desired_completion_date (0 = meets deadline, 1 = misses)
    2. Require no spending changes (0 = none, 1 = requires changes)
    3. Minimize total amount paid
    4. Start payment earlier (earliest start_date)
    5. Use fewer payments (payment_count)
    6. Lowest payment_option_id
    """
    deadline_penalty = 0 if plan.meets_deadline else 1
    spending_penalty = 0 if not plan.spending_changes else 1
    total_paid = plan.total_paid
    start_date = plan.start_date or date.max
    count = plan.payment_count
    option_key = option_id_sort_key(plan.payment_option_id)
    return (
        deadline_penalty,
        spending_penalty,
        round(total_paid, 2),
        start_date,
        count,
        option_key,
    )


def _format_date(d: date) -> str:
    months = [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    return f"{d.day} {months[d.month]} {d.year}"


def generate_explanation(
    decision: Decision,
    request: pd.Series,
    profile: pd.Series,
    selected_plan: CandidatePlan,
    earliest: date | None,
) -> str:
    """Produce grounded, professional explanations matching challenge contract."""
    currency = str(profile.get("home_currency", ""))
    req_amt = to_number(request["requested_amount"], "requested_amount")
    req_str = f"{currency} {_format_money(req_amt)}"
    min_bal = to_number(profile["minimum_balance_to_keep"], "minimum_balance_to_keep")
    min_str = f"{currency} {_format_money(min_bal)}"
    method = selected_plan.method
    deadline = parse_date(request["desired_completion_date"])

    if method == "full_payment":
        if not selected_plan.spending_changes:
            return f"Pay {req_str} today. This leaves at least {min_str} available over the next 90 days."
        changes_desc = []
        for ch in selected_plan.spending_changes:
            if ch.action == "stop":
                changes_desc.append(f"stop {ch.event_id}")
            else:
                changes_desc.append(f"reduce {ch.event_id} to {currency} {_format_money(ch.new_amount or 0)}")
        action_text = " and ".join(changes_desc).capitalize()
        return f"{action_text}, then pay {req_str} today. This leaves at least {min_str} available."

    if method == "partial_payment":
        p1 = selected_plan.payments[0]
        p2 = selected_plan.payments[1]
        p1_str = f"{currency} {_format_money(p1.amount)}"
        p2_str = f"{currency} {_format_money(p2.amount)}"
        p2_date_str = _format_date(p2.pay_date)
        return (
            f"Pay {p1_str} today and the remaining {p2_str} on {p2_date_str}. "
            f"This completes the full request and keeps the {min_str} minimum protected."
        )

    if method == "installments":
        n = len(selected_plan.payments)
        installment_amt = selected_plan.payments[0].amount if selected_plan.payments else 0
        inst_str = f"{currency} {_format_money(installment_amt)}"
        start_date_str = _format_date(selected_plan.payments[0].pay_date) if selected_plan.payments else ""
        return (
            f"Use {n} installments of {inst_str}, starting {start_date_str}. "
            f"This leaves at least {min_str} available."
        )

    if method == "wait":
        wait_date = earliest or (selected_plan.payments[0].pay_date if selected_plan.payments else None)
        date_str = _format_date(wait_date) if wait_date else "a later date"
        return (
            f"Pay {req_str} in full on {date_str}. "
            f"Paying earlier would take the balance below the {min_str} minimum."
        )

    deadline_str = _format_date(deadline) if deadline else "the deadline"
    safe_amt = decision.amount_safe_to_pay
    if safe_amt > 0:
        safe_str = f"{currency} {_format_money(safe_amt)}"
        return (
            f"Do not proceed with the {req_str} request. "
            f"Although {safe_str} is available today, the full amount cannot be completed safely within 90 days."
        )
    return f"Do not make this payment by {deadline_str}. None of the available options keeps the {min_str} minimum protected."


def make_decision(
    request: pd.Series,
    profile: pd.Series,
    events: pd.DataFrame,
    payment_options: pd.DataFrame,
    exchange_rates: pd.DataFrame | None = None,
    blank_amounts: dict[str, float] | None = None,
    confirmed_incomes: list[dict[str, Any]] | None = None,
    cancelled_events: set[str] | None = None,
    amended_events: dict[str, dict[str, Any]] | None = None,
) -> Decision:
    """Generate all candidates, rank them deterministically, and construct the Decision."""
    request_id = str(request["request_id"])
    request_date = parse_date(request["request_date"])
    if request_date is None:
        raise ValueError("request_date is missing")

    candidates, safe_today, earliest = generate_candidates(
        request,
        profile,
        events,
        payment_options,
        exchange_rates=exchange_rates,
        blank_amounts=blank_amounts,
        confirmed_incomes=confirmed_incomes,
        cancelled_events=cancelled_events,
        amended_events=amended_events,
    )

    eligible_plans = [p for p in candidates if p.eligible and p.is_safe]

    if eligible_plans:
        ranked = sorted(eligible_plans, key=rank_key)
        best_plan = ranked[0]
    else:
        best_plan = next((p for p in candidates if p.method == "not_recommended"), CandidatePlan(
            method="not_recommended",
            payments=[],
            spending_changes=[],
            meets_deadline=False,
            is_safe=False,
            eligible=False,
        ))

    # Determine affordability_status
    if best_plan.method == "full_payment" and not best_plan.spending_changes:
        status = "affordable_now"
    elif best_plan.method in {"partial_payment", "installments"} or (best_plan.method == "full_payment" and best_plan.spending_changes):
        status = "affordable_with_plan"
    elif best_plan.method == "wait":
        status = "affordable_later"
    else:
        status = "not_affordable"

    # Earliest date for full payment
    if status == "affordable_now":
        earliest_str = request_date.isoformat()
    elif status in {"affordable_with_plan", "affordable_later"} and earliest is not None:
        earliest_str = earliest.isoformat()
    else:
        earliest_str = ""

    decision = Decision(
        request_id=request_id,
        amount_safe_to_pay=round(safe_today, 2),
        affordability_status=status,
        recommended_payment_method=best_plan.method,
        payment_plan=format_payment_plan(best_plan.payments) if best_plan.method != "not_recommended" else "none",
        earliest_date_for_full_payment=earliest_str,
        spending_changes_needed=format_spending_changes(best_plan.spending_changes) if best_plan.spending_changes else "none",
        decision_explanation="",
        selected_plan=best_plan,
        candidates=candidates,
    )

    decision.decision_explanation = generate_explanation(
        decision, request, profile, best_plan, earliest
    )

    return decision
