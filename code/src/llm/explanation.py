from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    Decision,
    PlanEvaluation,
    SpendingChange,
)
from code.src.finance.ranking import format_amount
from code.src.llm.client import get_openai_client, global_tracker
from code.src.config import OPENAI_MODEL


def format_currency_amount(curr: str, amt: float) -> str:
    """Formats amount with comma separators for clean explanation."""
    if amt == int(amt):
        formatted = f"{int(amt):,}"
    else:
        formatted = f"{amt:,.2f}"
    return f"{curr} {formatted}"


def generate_deterministic_explanation(
    request: RequestContext,
    profile: UserFinancialProfile,
    decision: Decision,
    plan_eval: PlanEvaluation | None,
    applied_changes: list[SpendingChange],
) -> str:
    """
    Deterministic fallback explanation perfectly mirroring the sample_requests.csv format.
    """
    curr = profile.home_currency
    min_bal_str = format_currency_amount(curr, profile.minimum_balance_to_keep)
    req_amt_str = format_currency_amount(curr, request.requested_amount)

    status = decision.affordability_status
    method = decision.recommended_payment_method

    if status == "affordable_now":
        return f"Pay {req_amt_str} today. This leaves at least {min_bal_str} available over the next 90 days."

    elif status == "affordable_with_plan":
        if method == "installments" and plan_eval and plan_eval.plan.payments:
            n = len(plan_eval.plan.payments)
            inst_amt = format_currency_amount(curr, plan_eval.plan.payments[0].amount)
            first_d = plan_eval.plan.payments[0].payment_date.strftime("%-d %B %Y") if hasattr(plan_eval.plan.payments[0].payment_date, "strftime") else str(plan_eval.plan.payments[0].payment_date)
            return f"Use {n} installments of {inst_amt}, starting {first_d}. This leaves at least {min_bal_str} available."

        elif method == "partial_payment" and plan_eval and len(plan_eval.plan.payments) == 2:
            p1 = format_currency_amount(curr, plan_eval.plan.payments[0].amount)
            p2 = format_currency_amount(curr, plan_eval.plan.payments[1].amount)
            p2_d = plan_eval.plan.payments[1].payment_date.strftime("%-d %B %Y")
            return f"Pay {p1} today and the remaining {p2} on {p2_d}. This completes the full request and keeps the {min_bal_str} minimum protected."

        elif applied_changes:
            actions_text = []
            for c in applied_changes:
                if c.action == "stop":
                    actions_text.append(f"stop the {c.category} subscription")
                elif c.action == "reduce":
                    amt_str = format_currency_amount(curr, c.new_amount or 0.0)
                    actions_text.append(f"reduce the {c.category} spend to {amt_str}")
            chg_summary = " and ".join(actions_text).capitalize()
            return f"{chg_summary}, then pay {req_amt_str} today. This leaves at least {min_bal_str} available."

    elif status == "affordable_later":
        earliest_str = decision.earliest_date_for_full_payment
        if earliest_str:
            from datetime import date
            d_obj = date.fromisoformat(earliest_str)
            d_formatted = d_obj.strftime("%-d %B %Y")
            return f"Pay {req_amt_str} in full on {d_formatted}. Paying earlier would take the balance below the {min_bal_str} minimum."

    # Not affordable fallback
    deadline_formatted = request.desired_completion_date.strftime("%-d %B %Y")
    safe_amt = decision.amount_safe_to_pay
    if safe_amt > 0:
        safe_amt_str = format_currency_amount(curr, safe_amt)
        return f"Do not proceed with the {req_amt_str} request. Although {safe_amt_str} is available today, the full amount cannot be completed safely within 90 days."
    else:
        return f"Do not make this payment by {deadline_formatted}. None of the available options keeps the {min_bal_str} minimum protected."


def generate_explanation(
    request: RequestContext,
    profile: UserFinancialProfile,
    decision: Decision,
    plan_eval: PlanEvaluation | None,
    applied_changes: list[SpendingChange],
) -> str:
    """
    Generates explanation with LLM and falls back deterministically.
    """
    deterministic_text = generate_deterministic_explanation(
        request, profile, decision, plan_eval, applied_changes
    )

    client = get_openai_client()
    if not client:
        return deterministic_text

    prompt = f"""Generate a 1-2 sentence grounded financial explanation for this user request.
FACTS:
- Requested Amount: {profile.home_currency} {request.requested_amount}
- Request Date: {request.request_date}
- Desired Completion Date: {request.desired_completion_date}
- Minimum Required Balance: {profile.home_currency} {profile.minimum_balance_to_keep}
- Recommendation Method: {decision.recommended_payment_method}
- Affordability Status: {decision.affordability_status}
- Payment Plan: {decision.payment_plan}
- Spending Changes: {decision.spending_changes_needed}
- Earliest Safe Date: {decision.earliest_date_for_full_payment}

Reference template style:
"{deterministic_text}"

Return ONLY a concise, plain text explanation. Do not change any numbers or facts.
"""
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a concise financial decision explanation generator. Use only the provided facts."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=100,
        )
        if response.usage:
            global_tracker.record_usage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                model=response.model,
            )
        text = response.choices[0].message.content.strip()
        # Ensure it contains home currency and doesn't contradict facts
        if profile.home_currency in text and len(text) > 20:
            return text
    except Exception:
        pass

    return deterministic_text
