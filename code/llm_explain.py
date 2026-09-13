"""Module 7: llm_explain.

The second and last place the pipeline touches an LLM. Turns Module 5's
already-finalized decision (PlanResult) into a short, natural-language
`decision_explanation` — it never decides amounts, dates, or methods, and it
never sees raw messages/images (that's Module 6's job). Deterministic
Modules 2/4/5 are untouched by anything this module does.

Guard (PLAN.md §5.2 CONFIRMED): the model is not trusted to freely invent
numbers. It is instructed to use ONLY the amounts and ISO dates given to it
verbatim, and its output is validated after the fact — every number and every
YYYY-MM-DD date in the generated text must match one already present in the
decision data. If validation fails, or no API key/SDK is available, or the
call errors, callers keep plan_selector's own deterministic template
(fill-in-template) instead. Nothing here can make an explanation *wrong* in
a way that mismatches the numbers already committed to output.csv.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from loaders import FinancialProfile, Request
from plan_selector import PlanResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5")
MAX_OUTPUT_TOKENS = 256

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_AMOUNT_TOLERANCE = 0.5

SYSTEM_PROMPT = """You are the writing step of a personal-finance planning system. A \
deterministic engine has already decided every number, date, and recommendation below - \
your ONLY job is to phrase it as 1-2 short, plain sentences a user would read, in the style \
of these examples:

- "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days."
- "Use 3 installments of IDR 15,952,906.67, starting 2025-08-08. This leaves at least IDR \
29,158,400 available."
- "Stop the family streaming plan, then pay EUR 620.40 today. This leaves at least EUR 800 \
available."
- "Wait until 2026-01-15 to pay the full amount safely. Paying now would risk dropping below \
the minimum balance."
- "This request cannot be completed safely within the next 90 days while keeping the minimum \
balance protected."

Strict rules:
- Use ONLY the amounts, currency, and dates given to you below. Never introduce a number or \
date that is not explicitly present in the input.
- Always write dates as YYYY-MM-DD exactly as given - never spell them out in prose (no \
"12 January 2026"). This keeps the explanation checkable against the source data.
- Do not invent reasons, events, or facts not present in the input.
- Do not mention that you are an AI, a model, or that a system generated this.
- Call the write_explanation tool exactly once with your final text."""

EXPLAIN_TOOL = {
    "name": "write_explanation",
    "description": "Record the final 1-2 sentence explanation text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "explanation": {"type": "string"},
        },
        "required": ["explanation"],
    },
}


@dataclass(frozen=True)
class UsageRecord:
    request_id: str
    model: str
    input_tokens: int
    output_tokens: int


def _get_api_key() -> Optional[str]:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")


def _extract_amount_numbers(text: str) -> list[float]:
    text_without_dates = _ISO_DATE_RE.sub(" ", text)
    numbers = []
    for match in _NUMBER_RE.finditer(text_without_dates):
        try:
            numbers.append(float(match.group().replace(",", "")))
        except ValueError:
            continue
    return numbers


def _allowed_amounts(request: Request, profile: FinancialProfile, result: PlanResult) -> set[float]:
    amounts = {
        round(result.amount_safe_to_pay, 2),
        round(request.requested_amount, 2),
        round(profile.minimum_balance_to_keep, 2),
    }
    if result.payment_plan != "none":
        for part in result.payment_plan.split("|"):
            if ":" not in part:
                continue
            _, amt = part.rsplit(":", 1)
            try:
                amounts.add(round(float(amt), 2))
            except ValueError:
                pass
    if result.spending_changes_needed != "none":
        for action in result.spending_changes_needed.split("|"):
            if action.startswith("reduce_to:"):
                parts = action.split(":")
                if len(parts) == 3:
                    try:
                        amounts.add(round(float(parts[2]), 2))
                    except ValueError:
                        pass
    # allow the whole-number rendering too (e.g. "620" for 620.0)
    amounts |= {round(a) for a in amounts}
    # non-financial numbers the fixed phrasing is allowed to mention
    amounts.add(90)  # the 90-day forecast horizon
    if result.payment_plan != "none":
        amounts.add(len(result.payment_plan.split("|")))  # e.g. "3 installments"
    return amounts


def _allowed_dates(request: Request, result: PlanResult) -> set[str]:
    dates = {request.request_date.isoformat(), request.desired_completion_date.isoformat()}
    if result.earliest_date_for_full_payment is not None:
        dates.add(result.earliest_date_for_full_payment.isoformat())
    if result.payment_plan != "none":
        for part in result.payment_plan.split("|"):
            if ":" in part:
                dates.add(part.split(":", 1)[0])
    return dates


def _validate(text: str, request: Request, profile: FinancialProfile, result: PlanResult) -> bool:
    if not text or not text.strip():
        return False
    allowed_dates = _allowed_dates(request, result)
    for found in _ISO_DATE_RE.findall(text):
        if found not in allowed_dates:
            logger.warning("llm_explain: rejecting explanation — date %s not in allowed set %s", found, allowed_dates)
            return False
    allowed_amounts = _allowed_amounts(request, profile, result)
    for number in _extract_amount_numbers(text):
        if not any(abs(number - allowed) <= _AMOUNT_TOLERANCE for allowed in allowed_amounts):
            logger.warning(
                "llm_explain: rejecting explanation — number %s not in allowed set %s", number, allowed_amounts
            )
            return False
    return True


def _build_prompt(request: Request, profile: FinancialProfile, result: PlanResult) -> str:
    return f"""Decision data (use ONLY these values):
- currency: {profile.home_currency}
- requested_amount: {request.requested_amount}
- amount_safe_to_pay: {result.amount_safe_to_pay}
- minimum_balance_to_keep: {profile.minimum_balance_to_keep}
- affordability_status: {result.affordability_status}
- recommended_payment_method: {result.recommended_payment_method}
- payment_plan: {result.payment_plan}
- earliest_date_for_full_payment: {result.earliest_date_for_full_payment.isoformat() if result.earliest_date_for_full_payment else 'none'}
- desired_completion_date: {request.desired_completion_date.isoformat()}
- spending_changes_needed: {result.spending_changes_needed}

Write the explanation now."""


def explain_decision(
    request: Request,
    profile: FinancialProfile,
    result: PlanResult,
    model: str = DEFAULT_MODEL,
) -> tuple[str, Optional[UsageRecord]]:
    """Return `(explanation_text, usage)`. Falls back to `result.decision_explanation`
    (plan_selector's deterministic template) untouched whenever the LLM path is
    unavailable, errors, or produces text that fails number/date validation."""
    fallback = result.decision_explanation

    api_key = _get_api_key()
    if not api_key:
        return fallback, None

    try:
        import anthropic
    except ImportError:
        logger.warning("llm_explain: `anthropic` package not installed — using deterministic template")
        return fallback, None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[EXPLAIN_TOOL],
            tool_choice={"type": "tool", "name": "write_explanation"},
            messages=[{"role": "user", "content": _build_prompt(request, profile, result)}],
        )
    except Exception:
        logger.exception("llm_explain: API call failed for request %s — using deterministic template", request.request_id)
        return fallback, None

    usage = UsageRecord(
        request_id=request.request_id,
        model=model,
        input_tokens=getattr(response.usage, "input_tokens", 0),
        output_tokens=getattr(response.usage, "output_tokens", 0),
    )

    tool_use = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_use is None:
        logger.warning("llm_explain: no tool_use block in response for request %s", request.request_id)
        return fallback, usage

    text = tool_use.input.get("explanation", "")
    if not _validate(text, request, profile, result):
        return fallback, usage
    return text.strip(), usage
