"""Decision Engine for Buy or Wait?

Ranks candidate plans according to exact problem_statement.md rules:
1. Complete the full request by desired_completion_date
2. Require no spending changes
3. Minimize the total amount paid
4. Start payment earlier
5. Use fewer payments
6. Use the lowest payment_option_id as the final tie-breaker
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from forecast import parse_date, to_number
from models import (
    CandidatePlan,
    Decision,
    format_payment_plan,
    format_spending_changes,
    _format_money,
)
from plan_generator import generate_candidates, rank_key


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
    """Produce grounded, professional explanations matching sample_requests.csv style."""
    currency = str(profile.get("home_currency", ""))
    req_amt = to_number(request["requested_amount"], "requested_amount")
    req_str = f"{currency} {_format_money(req_amt)}"
    min_bal = to_number(profile["minimum_balance_to_keep"], "minimum_balance_to_keep")
    min_str = f"{currency} {_format_money(min_bal)}"
    method = selected_plan.method
    deadline = parse_date(request["desired_completion_date"])
    req_date = parse_date(request["request_date"])

    if method == "full_payment":
        if not selected_plan.spending_changes:
            return f"Pay {req_str} today. This leaves at least {min_str} available over the next 90 days."
        else:
            changes_desc = []
            for ch in selected_plan.spending_changes:
                if ch.action == "stop":
                    changes_desc.append(f"stop {ch.event_id}")
                else:
                    changes_desc.append(f"reduce {ch.event_id} to {currency} {_format_money(ch.new_amount or 0)}")
            action_text = " and ".join(changes_desc).capitalize()
            return f"{action_text}, then pay {req_str} today. This leaves at least {min_str} available."

    elif method == "partial_payment":
        p1 = selected_plan.payments[0]
        p2 = selected_plan.payments[1]
        p1_str = f"{currency} {_format_money(p1.amount)}"
        p2_str = f"{currency} {_format_money(p2.amount)}"
        p2_date_str = _format_date(p2.pay_date)
        return (
            f"Pay {p1_str} today and the remaining {p2_str} on {p2_date_str}. "
            f"This completes the full request and keeps the {min_str} minimum protected."
        )

    elif method == "installments":
        n = len(selected_plan.payments)
        installment_amt = selected_plan.payments[0].amount if selected_plan.payments else 0
        inst_str = f"{currency} {_format_money(installment_amt)}"
        start_date_str = _format_date(selected_plan.payments[0].pay_date) if selected_plan.payments else ""
        return (
            f"Use {n} installments of {inst_str}, starting {start_date_str}. "
            f"This leaves at least {min_str} available."
        )

    elif method == "wait":
        wait_date = earliest or (selected_plan.payments[0].pay_date if selected_plan.payments else None)
        date_str = _format_date(wait_date) if wait_date else "a later date"
        return (
            f"Pay {req_str} in full on {date_str}. "
            f"Paying earlier would take the balance below the {min_str} minimum."
        )

    else:  # not_recommended
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
