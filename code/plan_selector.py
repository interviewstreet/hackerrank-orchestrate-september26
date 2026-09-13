"""Module 5: plan_selector.

Turns Module 4's forecast into the final decision fields (problem_statement.md
"Choosing Between Safe Plans", AGENTS.md §6.2-6.3). Deterministic, stdlib +
python-dateutil only — no LLM calls.

- `amount_safe_to_pay` and `earliest_date_for_full_payment` are always the raw
  Module 4 numbers — "before optional spending changes" per problem_statement.md,
  independent of whichever method ends up recommended.
- Every other field comes from ranking the *safe, eligible* candidate plans:
  `full_payment`, `partial_payment`, and one candidate per matching
  `installments` payment option, each checked against the forecast. A method is
  only eligible when it is in `payment_methods_user_will_consider` (installments
  also need a non-blank `max_installment_months`, checked against the option's
  calendar-month span via `dateutil.relativedelta`, PLAN.md §9.3).
- If none of those are both safe and complete the request by
  `desired_completion_date`, a minimal set of permitted spending changes
  (largest freed cash first, capped at 3, never mixing stop+reduce on the same
  event) is tried to rescue one — this is the only path to `spending_changes_needed`.
- If nothing completes the request by the deadline even so, `wait` (paying the
  full amount on `earliest_date_for_full_payment`) is offered when the user
  accepts `full_payment`; otherwise the fallback is `not_recommended`.
- Safe eligible candidates are ranked by problem_statement.md's 6 tie-breakers:
  complete by deadline > no spending changes > lowest total paid > starts
  earlier > fewer payments > lowest `payment_option_id`.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta

from forecast_engine import Forecast, ForecastPoint
from fx import FxConverter
from loaders import FinancialProfile, PaymentOption, Request

logger = logging.getLogger(__name__)

MAX_SPENDING_CHANGES = 3


@dataclass
class SpendingChange:
    kind: str  # "stop" | "reduce"
    event_id: str
    category: str
    settlement_date: date
    freed_home_amount: float  # headroom gained, in home currency
    new_amount: Optional[float] = None  # event's own currency, for "reduce"

    def to_action_str(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{_fmt_plain(self.new_amount)}"


@dataclass
class Candidate:
    method: str  # "full_payment" | "partial_payment" | "installments" | "wait"
    completes_by_deadline: bool
    total_paid: float
    start_date: date
    num_payments: int
    payment_plan: list[tuple[date, float]]
    payment_option_id: Optional[str] = None
    spending_changes: tuple[SpendingChange, ...] = ()

    def rank_key(self):
        option_num = _option_number(self.payment_option_id)
        return (
            0 if self.completes_by_deadline else 1,
            1 if self.spending_changes else 0,
            round(self.total_paid, 2),
            self.start_date,
            self.num_payments,
            option_num,
        )


@dataclass
class PlanResult:
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str


def _option_number(payment_option_id: Optional[str]) -> float:
    if not payment_option_id:
        return float("inf")
    digits = "".join(ch for ch in payment_option_id if ch.isdigit())
    return int(digits) if digits else float("inf")


def _fmt_plain(amount: float) -> str:
    if amount == round(amount):
        return str(int(round(amount)))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _fmt_money(currency: str, amount: float) -> str:
    if amount == round(amount):
        return f"{currency} {amount:,.0f}"
    return f"{currency} {amount:,.2f}"


def _installment_month_span(first_payment_date: date, last_payment_date: date) -> int:
    """PLAN.md §9.3 [CONFIRMED]: real calendar months via relativedelta, rounded
    up — a schedule that spills into a partial month still needs that month."""
    rd = relativedelta(last_payment_date, first_payment_date)
    months = rd.years * 12 + rd.months
    if rd.days > 0:
        months += 1
    return max(months, 1)


def apply_spending_changes(forecast: Forecast, changes: list[SpendingChange]) -> Forecast:
    """Return a new Forecast with each change's freed cash added from its
    settlement date onward (a permanent step up in the balance trajectory)."""
    freed = [(c.settlement_date, c.freed_home_amount) for c in changes]
    if not freed:
        return forecast

    checkpoint_dates = sorted({p.on_date for p in forecast.trajectory} | {d for d, _ in freed})

    def baseline_at(d: date) -> float:
        dates = [p.on_date for p in forecast.trajectory]
        idx = bisect.bisect_right(dates, d) - 1
        idx = max(idx, 0)
        return forecast.trajectory[idx].balance

    new_points = [
        ForecastPoint(
            on_date=d,
            balance=baseline_at(d) + sum(amt for fd, amt in freed if fd <= d),
        )
        for d in checkpoint_dates
    ]
    return Forecast(
        user_id=forecast.user_id,
        request_date=forecast.request_date,
        horizon_end=forecast.horizon_end,
        minimum_balance_to_keep=forecast.minimum_balance_to_keep,
        trajectory=new_points,
        recurring_series=forecast.recurring_series,
        future_known_events=forecast.future_known_events,
    )


def _validate_schedule(forecast: Forecast, payments: list[tuple[date, float]]) -> bool:
    """A multi-payment schedule is safe iff, after each payment, the worst
    baseline balance from that date onward still clears the minimum once every
    payment made so far (cumulative) is subtracted."""
    cumulative = 0.0
    for pay_date, amount in sorted(payments, key=lambda p: p[0]):
        cumulative += amount
        if forecast.suffix_min_from(pay_date) - cumulative < forecast.minimum_balance_to_keep:
            return False
    return True


def _full_payment_candidate(
    request: Request, forecast: Forecast, payment_options: list[PaymentOption]
) -> Optional[Candidate]:
    if forecast.earliest_date_for_full_payment(request.requested_amount) != request.request_date:
        return None
    option = next((o for o in payment_options if o.payment_method == "full_payment"), None)
    total_paid = option.total_payable_amount if option else request.requested_amount
    option_id = option.payment_option_id if option else None
    return Candidate(
        method="full_payment",
        completes_by_deadline=request.request_date <= request.desired_completion_date,
        total_paid=total_paid,
        start_date=request.request_date,
        num_payments=1,
        payment_plan=[(request.request_date, request.requested_amount)],
        payment_option_id=option_id,
    )


def _partial_payment_candidate(request: Request, forecast: Forecast) -> Optional[Candidate]:
    if not request.allows_partial_payment:
        return None
    safe_now = forecast.amount_safe_to_pay_now(request.requested_amount)
    if not (0 < safe_now < request.requested_amount):
        return None
    earliest_full = forecast.earliest_date_for_full_payment(request.requested_amount)
    if earliest_full is None or earliest_full > request.desired_completion_date:
        return None
    remainder = request.requested_amount - safe_now
    return Candidate(
        method="partial_payment",
        completes_by_deadline=True,
        total_paid=request.requested_amount,
        start_date=request.request_date,
        num_payments=2,
        payment_plan=[(request.request_date, safe_now), (earliest_full, remainder)],
    )


def _installment_candidates(
    request: Request,
    forecast: Forecast,
    profile: FinancialProfile,
    payment_options: list[PaymentOption],
) -> list[Candidate]:
    if profile.max_installment_months is None:
        return []
    candidates = []
    for option in payment_options:
        if option.payment_method != "installments" or not option.number_of_payments:
            continue
        n = option.number_of_payments
        first_date = option.first_payment_date
        freq = option.payment_frequency_days or 0
        if first_date is None or n < 1:
            continue
        dates = [first_date + timedelta(days=freq * i) for i in range(n)]
        if _installment_month_span(dates[0], dates[-1]) > profile.max_installment_months:
            continue
        payments = [(d, option.payment_amount) for d in dates]
        if not _validate_schedule(forecast, payments):
            continue
        candidates.append(
            Candidate(
                method="installments",
                completes_by_deadline=dates[-1] <= request.desired_completion_date,
                total_paid=option.total_payable_amount,
                start_date=dates[0],
                num_payments=n,
                payment_plan=payments,
                payment_option_id=option.payment_option_id,
            )
        )
    return candidates


def _wait_candidate(request: Request, forecast: Forecast) -> Optional[Candidate]:
    earliest = forecast.earliest_date_for_full_payment(request.requested_amount)
    if earliest is None or earliest == request.request_date:
        return None
    return Candidate(
        method="wait",
        completes_by_deadline=earliest <= request.desired_completion_date,
        total_paid=request.requested_amount,
        start_date=earliest,
        num_payments=1,
        payment_plan=[(earliest, request.requested_amount)],
    )


def _spending_change_for(
    *,
    event_id: str,
    category: str,
    flexibility: str,
    amount: float,
    currency: str,
    minimum_allowed_amount: Optional[float],
    settlement_date: date,
    profile: FinancialProfile,
    fx: FxConverter,
) -> Optional[SpendingChange]:
    if category in profile.expense_categories_to_protect:
        return None
    can_stop = (
        flexibility in ("stoppable", "reducible_or_stoppable")
        and category in profile.expense_categories_user_is_willing_to_stop
    )
    can_reduce = (
        flexibility in ("reducible", "reducible_or_stoppable")
        and category in profile.expense_categories_user_is_willing_to_reduce
        and minimum_allowed_amount is not None
        and minimum_allowed_amount < amount
    )
    if can_stop:
        freed = fx.convert(amount, currency, profile.home_currency, settlement_date)
        if freed is None:
            return None
        return SpendingChange(
            kind="stop", event_id=event_id, category=category,
            settlement_date=settlement_date, freed_home_amount=freed,
        )
    if can_reduce:
        saved = amount - minimum_allowed_amount
        freed = fx.convert(saved, currency, profile.home_currency, settlement_date)
        if freed is None:
            return None
        return SpendingChange(
            kind="reduce", event_id=event_id, category=category,
            settlement_date=settlement_date, freed_home_amount=freed,
            new_amount=minimum_allowed_amount,
        )
    return None


def _gather_spending_change_options(
    forecast: Forecast, profile: FinancialProfile, request: Request, fx: FxConverter
) -> list[SpendingChange]:
    options: list[SpendingChange] = []
    for event in forecast.future_known_events:
        if event.settlement_date is None or not (
            request.request_date < event.settlement_date <= forecast.horizon_end
        ):
            continue
        change = _spending_change_for(
            event_id=event.event_id, category=event.category, flexibility=event.flexibility,
            amount=event.amount, currency=event.currency,
            minimum_allowed_amount=event.minimum_allowed_amount,
            settlement_date=event.settlement_date, profile=profile, fx=fx,
        )
        if change is not None:
            options.append(change)

    # A future occurrence of a recurring debit series has no event_id of its
    # own (nothing has actually happened yet) — cite the series' last real
    # occurrence as the handle for "stop/reduce this recurring expense going
    # forward" instead. Matches how dataset/sample_requests.csv's own
    # spending_changes_needed answers cite an already-settled event_id.
    already_cited = {c.event_id for c in options}
    for series in forecast.recurring_series:
        if series.direction != "debit" or series.next_occurrence_date is None:
            continue
        if series.last_occurrence_event_id in already_cited:
            continue
        change = _spending_change_for(
            event_id=series.last_occurrence_event_id, category=series.category,
            flexibility=series.flexibility, amount=series.per_occurrence_amount,
            currency=series.currency, minimum_allowed_amount=series.minimum_allowed_amount,
            settlement_date=series.next_occurrence_date, profile=profile, fx=fx,
        )
        if change is not None:
            options.append(change)

    options.sort(key=lambda c: c.freed_home_amount, reverse=True)
    return options


def _rescue_with_spending_changes(
    request: Request,
    forecast: Forecast,
    profile: FinancialProfile,
    payment_options: list[PaymentOption],
    fx: FxConverter,
    accepted: set[str],
) -> Optional[Candidate]:
    pool = _gather_spending_change_options(forecast, profile, request, fx)
    for count in range(1, min(MAX_SPENDING_CHANGES, len(pool)) + 1):
        chosen = pool[:count]
        adjusted = apply_spending_changes(forecast, chosen)
        rescued = None
        if "full_payment" in accepted:
            rescued = _full_payment_candidate(request, adjusted, payment_options)
        if rescued is None and "partial_payment" in accepted:
            rescued = _partial_payment_candidate(request, adjusted)
        if rescued is None and "installments" in accepted:
            for candidate in _installment_candidates(request, adjusted, profile, payment_options):
                if candidate.completes_by_deadline:
                    rescued = candidate
                    break
        if rescued is not None and rescued.completes_by_deadline:
            rescued.spending_changes = tuple(chosen)
            return rescued
    return None


def _explain(
    request: Request,
    profile: FinancialProfile,
    status: str,
    method: str,
    candidate: Optional[Candidate],
    earliest_date_for_full_payment: Optional[date],
) -> str:
    currency = profile.home_currency
    min_bal = _fmt_money(currency, profile.minimum_balance_to_keep)
    if method == "full_payment" and candidate:
        return (
            f"Pay {_fmt_money(currency, request.requested_amount)} today. "
            f"This leaves at least {min_bal} available over the next 90 days."
        )
    if method == "partial_payment" and candidate:
        first_date, first_amt = candidate.payment_plan[0]
        second_date, second_amt = candidate.payment_plan[1]
        return (
            f"Pay {_fmt_money(currency, first_amt)} today and the remaining "
            f"{_fmt_money(currency, second_amt)} on {second_date.isoformat()}. "
            f"This completes the {_fmt_money(currency, request.requested_amount)} request "
            f"while keeping at least {min_bal} available."
        )
    if method == "installments" and candidate:
        _, first_amt = candidate.payment_plan[0]
        extra = ""
        if candidate.spending_changes:
            extra = " " + _spending_change_note(candidate.spending_changes)
        return (
            f"Use {candidate.num_payments} installments of {_fmt_money(currency, first_amt)} "
            f"starting {candidate.start_date.isoformat()}. This leaves at least {min_bal} "
            f"available.{extra}"
        )
    if method == "wait" and candidate:
        return (
            f"Wait until {candidate.start_date.isoformat()} to pay the full "
            f"{_fmt_money(currency, request.requested_amount)} safely. Paying now would risk "
            f"dropping below the {min_bal} minimum."
        )
    if earliest_date_for_full_payment is not None:
        return (
            f"The full {_fmt_money(currency, request.requested_amount)} request is not safe "
            f"within the next 90 days under the accepted payment methods, and the earliest "
            f"projected safe date ({earliest_date_for_full_payment.isoformat()}) is beyond what "
            f"can be recommended here."
        )
    return (
        f"The full {_fmt_money(currency, request.requested_amount)} request is not expected to "
        f"become safe within the next 90 days while keeping at least {min_bal} available."
    )


def _spending_change_note(changes: tuple[SpendingChange, ...]) -> str:
    parts = []
    for c in changes:
        if c.kind == "stop":
            parts.append(f"stopping {c.category} ({c.event_id})")
        else:
            parts.append(f"reducing {c.category} ({c.event_id}) to {_fmt_plain(c.new_amount)}")
    return "Requires " + ", ".join(parts) + "."


def _format_plan(payments: list[tuple[date, float]]) -> str:
    if not payments:
        return "none"
    return "|".join(f"{d.isoformat()}:{_fmt_plain(a)}" for d, a in sorted(payments))


def _format_spending_changes(changes: tuple[SpendingChange, ...]) -> str:
    if not changes:
        return "none"
    return "|".join(c.to_action_str() for c in changes)


def select_plan(
    request: Request,
    forecast: Forecast,
    profile: FinancialProfile,
    payment_options: list[PaymentOption],
    fx: FxConverter,
) -> PlanResult:
    amount_safe = forecast.amount_safe_to_pay_now(request.requested_amount)
    earliest_full = forecast.earliest_date_for_full_payment(request.requested_amount)

    accepted = set(profile.payment_methods_user_will_consider)
    candidates: list[Candidate] = []

    if "full_payment" in accepted:
        c = _full_payment_candidate(request, forecast, payment_options)
        if c:
            candidates.append(c)
    if "partial_payment" in accepted:
        c = _partial_payment_candidate(request, forecast)
        if c:
            candidates.append(c)
    if "installments" in accepted:
        candidates.extend(_installment_candidates(request, forecast, profile, payment_options))
    if "full_payment" in accepted:
        wait_candidate = _wait_candidate(request, forecast)
        if wait_candidate is not None:
            candidates.append(wait_candidate)

    on_time = [c for c in candidates if c.completes_by_deadline]
    if not on_time:
        rescued = _rescue_with_spending_changes(request, forecast, profile, payment_options, fx, accepted)
        if rescued is not None:
            candidates.append(rescued)
            on_time = [rescued]

    chosen: Optional[Candidate]
    if on_time:
        chosen = min(on_time, key=lambda c: c.rank_key())
    elif candidates:
        chosen = min(candidates, key=lambda c: c.rank_key())
    else:
        chosen = None

    if chosen is None:
        return PlanResult(
            amount_safe_to_pay=amount_safe,
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            payment_plan="none",
            earliest_date_for_full_payment=earliest_full,
            spending_changes_needed="none",
            decision_explanation=_explain(request, profile, "not_affordable", "not_recommended", None, earliest_full),
        )

    if chosen.method == "full_payment" and not chosen.spending_changes:
        status = "affordable_now"
    elif chosen.method == "wait":
        status = "affordable_later"
    else:
        status = "affordable_with_plan"

    return PlanResult(
        amount_safe_to_pay=amount_safe,
        affordability_status=status,
        recommended_payment_method=chosen.method,
        payment_plan=_format_plan(chosen.payment_plan),
        earliest_date_for_full_payment=earliest_full,
        spending_changes_needed=_format_spending_changes(chosen.spending_changes),
        decision_explanation=_explain(request, profile, status, chosen.method, chosen, earliest_full),
    )
