"""Candidate generation, eligibility, and ranking.

**M3 adds `partial_payment`, `installments`, and spending-change-augmented
`full_payment`** to the M1 `full_payment` / `wait` / `not_recommended` core.
The candidate and ranking machinery was already general enough that M3 only
adds generators, never rewrites selection.

Two separations carried deliberately through this module:

* **Capacity is not eligibility.** `earliest_date_for_full_payment` is a
  statement about the user's cash, computed in `forecast.py` without reference
  to what payment methods they accept. A user can have the money today and still
  receive `not_recommended` because the only method they accept is unsafe. The
  capacity date is still reported (`problem_statement.md:163`).
* **Safety is proved by replay, not by shape.** Every candidate is checked by
  re-walking the forecast (with any spending changes applied) with its
  payments injected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from . import spending
from .forecast import Forecast
from .money import ZERO
from .recurrence import Recurrence
from .schema import PaymentOption, RequestInput, Profile

#: Ranking order from `problem_statement.md` "Choosing Between Safe Plans".
RANKING_CRITERIA = (
    "completes by desired_completion_date",
    "requires no spending changes",
    "lowest total amount paid",
    "starts earlier",
    "fewer payments",
    "lowest payment_option_id",
)


@dataclass(frozen=True)
class Payment:
    on_date: date
    amount: Decimal


@dataclass(frozen=True)
class Candidate:
    """A proposed way to satisfy the request, with its proof of safety."""

    method: str
    status: str
    payments: tuple[Payment, ...]
    completes_request: bool
    payment_option_id: Optional[str] = None
    spending_changes: tuple[str, ...] = field(default_factory=tuple)
    #: Set only when this candidate's safety depends on spending changes that
    #: are not visible in `payments` alone -- the forecast the changes were
    #: verified against, for `choose()` to replay instead of the base forecast.
    replay_forecast: Optional[Forecast] = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def spending_change_count(self) -> int:
        return len(self.spending_changes)

    @property
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), ZERO)

    @property
    def first_payment_date(self) -> Optional[date]:
        return self.payments[0].on_date if self.payments else None

    @property
    def completion_date(self) -> Optional[date]:
        return self.payments[-1].on_date if self.payments else None

    def as_extra(self) -> list[tuple[date, Decimal]]:
        return [(p.on_date, p.amount) for p in self.payments]


@dataclass(frozen=True)
class Decision:
    """The engine's answer for one request, before rendering."""

    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payments: tuple[Payment, ...]
    earliest_date_for_full_payment: Optional[date]
    spending_changes: tuple[str, ...]
    # -- audit fields, never written to the CSV --
    degraded: bool
    degradation_reason: Optional[str]
    rejected: tuple[str, ...]
    chosen_payment_option_id: Optional[str]
    facts: tuple[str, ...]


def accepts(profile: Profile, method: str) -> bool:
    return method in profile.payment_methods_user_will_consider


#: An empty recurrence, for callers that have none to offer (keeps `generate`
#: and `choose` free of `Optional` branching for the common M1-only case).
_NO_RECURRENCE = Recurrence(fixed=(), rates=())


def generate(
    request: RequestInput,
    profile: Profile,
    forecast: Forecast,
    recurrence: Recurrence = _NO_RECURRENCE,
    payment_options: Sequence[PaymentOption] = (),
) -> tuple[list[Candidate], list[str]]:
    """Build every eligible, *safe* candidate. Returns (candidates, rejections)."""
    candidates: list[Candidate] = []
    rejected: list[str] = []
    requested = request.requested_amount

    # An unquantified obligation makes every safety result an upper bound rather
    # than a proof, so nothing may be recommended (review finding R01). Checked
    # here as well as in `Forecast.amount_safe_to_pay` because `is_safe()` alone
    # cannot know the timeline is incomplete.
    if not forecast.certifiable:
        return [], [f"all methods: {'; '.join(forecast.uncertainty)}"]

    earliest = forecast.earliest_full_payment_date(requested)
    safe_today = forecast.amount_safe_to_pay(requested)

    # --- full payment today -------------------------------------------------
    if not accepts(profile, "full_payment"):
        rejected.append("full_payment: not in payment_methods_user_will_consider")
    elif forecast.is_safe([(request.request_date, requested)]):
        candidates.append(Candidate(
            method="full_payment",
            status="affordable_now",
            payments=(Payment(request.request_date, requested),),
            completes_request=True,
        ))
    else:
        breach = forecast.breach_date([(request.request_date, requested)])
        rejected.append(f"full_payment today: balance would fall below the minimum by {breach}")

        # --- full payment, after cutting recurring flexible spending --------
        actions = spending.eligible_actions(recurrence, profile)
        for combo in spending.combos(actions):
            adjusted = spending.apply(forecast, combo)
            if adjusted.is_safe([(request.request_date, requested)]):
                candidates.append(Candidate(
                    method="full_payment",
                    status="affordable_with_plan",
                    payments=(Payment(request.request_date, requested),),
                    completes_request=True,
                    spending_changes=tuple(a.as_literal() for a in combo),
                    replay_forecast=adjusted,
                ))
                break
        else:
            if actions:
                rejected.append(
                    "full_payment with spending changes: no combination of up to "
                    f"{spending.MAX_ACTIONS} eligible actions restores safety by {breach}"
                )

    # --- wait for the first safe date ---------------------------------------
    if accepts(profile, "full_payment") and earliest is not None and earliest > request.request_date:
        if earliest <= request.desired_completion_date:
            candidates.append(Candidate(
                method="wait",
                status="affordable_later",
                payments=(Payment(earliest, requested),),
                completes_request=True,
            ))
        else:
            rejected.append(
                f"wait: full payment first becomes safe on {earliest}, after the "
                f"{request.desired_completion_date} deadline"
            )

    # --- partial payment -----------------------------------------------------
    if not request.allows_partial_payment:
        if accepts(profile, "partial_payment"):
            rejected.append("partial_payment: request does not allow partial payment")
    elif not accepts(profile, "partial_payment"):
        rejected.append("partial_payment: not in payment_methods_user_will_consider")
    elif not (ZERO < safe_today < requested):
        rejected.append(
            f"partial_payment: amount_safe_to_pay {safe_today} is not strictly "
            f"between 0 and requested_amount {requested}"
        )
    elif earliest is None:
        rejected.append("partial_payment: the remainder never becomes safe within the forecast window")
    elif earliest > request.desired_completion_date:
        rejected.append(
            f"partial_payment: the remainder first becomes safe on {earliest}, after the "
            f"{request.desired_completion_date} deadline"
        )
    else:
        candidates.append(Candidate(
            method="partial_payment",
            status="affordable_with_plan",
            payments=(
                Payment(request.request_date, safe_today),
                Payment(earliest, requested - safe_today),
            ),
            completes_request=True,
        ))

    # --- installments: must exactly match a supplied option -------------------
    installment_options = [o for o in payment_options if o.payment_method == "installments"]
    if not accepts(profile, "installments"):
        if installment_options:
            rejected.append("installments: not in payment_methods_user_will_consider")
    elif profile.max_installment_months is None:
        if installment_options:
            rejected.append(
                "installments: user's max_installment_months is blank; no term is accepted"
            )
    else:
        for option in sorted(installment_options, key=lambda o: o.payment_option_id):
            dates = [
                option.first_payment_date + timedelta(days=option.payment_frequency_days * i)
                for i in range(option.number_of_payments)
            ]
            if dates[0] < request.request_date:
                rejected.append(
                    f"installments {option.payment_option_id}: first payment {dates[0]} "
                    f"precedes request_date {request.request_date}"
                )
                continue
            if dates[-1] > request.desired_completion_date:
                rejected.append(
                    f"installments {option.payment_option_id}: completes {dates[-1]}, after "
                    f"{request.desired_completion_date}"
                )
                continue
            term_months = Decimal((dates[-1] - dates[0]).days) / Decimal(30)
            if term_months > Decimal(profile.max_installment_months):
                rejected.append(
                    f"installments {option.payment_option_id}: term ~{term_months} months "
                    f"exceeds max_installment_months {profile.max_installment_months}"
                )
                continue
            candidates.append(Candidate(
                method="installments",
                status="affordable_with_plan",
                payments=tuple(Payment(d, option.payment_amount) for d in dates),
                completes_request=True,
                payment_option_id=option.payment_option_id,
            ))

    return candidates, rejected


def choose(
    request: RequestInput,
    profile: Profile,
    forecast: Forecast,
    recurrence: Recurrence = _NO_RECURRENCE,
    payment_options: Sequence[PaymentOption] = (),
) -> Decision:
    """Generate, verify, rank, and settle on one answer."""
    requested = request.requested_amount
    safe_today = forecast.amount_safe_to_pay(requested)
    earliest = forecast.earliest_full_payment_date(requested)

    candidates, rejected = generate(request, profile, forecast, recurrence, payment_options)

    # Verify every candidate by replay before it is allowed to compete. A
    # candidate that cannot survive its own schedule is removed here, not ranked.
    # A candidate with spending changes replays against its own adjusted
    # forecast (`replay_forecast`), never the unmodified one.
    verified: list[Candidate] = []
    for candidate in candidates:
        replay_against = candidate.replay_forecast or forecast
        if replay_against.is_safe(candidate.as_extra()):
            verified.append(candidate)
        else:
            rejected.append(f"{candidate.method}: failed independent replay of its own schedule")

    facts = _facts(forecast, safe_today, earliest)

    if not verified:
        return Decision(
            request_id=request.request_id,
            amount_safe_to_pay=safe_today,
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            payments=(),
            # Capacity is reported even when no method is eligible.
            earliest_date_for_full_payment=earliest,
            spending_changes=(),
            degraded=not forecast.certifiable,
            degradation_reason=_degradation_reason(forecast),
            rejected=tuple(rejected),
            chosen_payment_option_id=None,
            facts=facts,
        )

    best = min(verified, key=lambda c: _rank(c, request))
    return Decision(
        request_id=request.request_id,
        amount_safe_to_pay=safe_today,
        affordability_status=best.status,
        recommended_payment_method=best.method,
        payments=best.payments,
        earliest_date_for_full_payment=earliest,
        spending_changes=best.spending_changes,
        degraded=False,
        degradation_reason=None,
        rejected=tuple(rejected),
        chosen_payment_option_id=best.payment_option_id,
        facts=facts,
    )


def _rank(candidate: Candidate, request: RequestInput) -> tuple:
    """The documented ranking order, lowest tuple wins.

    Booleans are inverted (`not x`) so that "better" sorts first.
    """
    completes_by_deadline = (
        candidate.completes_request
        and candidate.completion_date is not None
        and candidate.completion_date <= request.desired_completion_date
    )
    return (
        not completes_by_deadline,               # 1. complete by the deadline
        candidate.spending_change_count > 0,     # 2. no spending changes
        candidate.total_paid,                    # 3. minimize total paid
        candidate.first_payment_date or date.max,  # 4. start earlier
        len(candidate.payments),                 # 5. fewer payments
        candidate.payment_option_id or "",       # 6. lowest option id
    )


def _facts(forecast: Forecast, safe_today: Decimal, earliest: Optional[date]) -> tuple[str, ...]:
    """Structured claims an explanation may draw on. No prose is invented later
    that is not grounded in one of these."""
    facts = [
        f"minimum_balance={forecast.minimum_balance}",
        f"opening_balance={forecast.opening_balance}",
        f"amount_safe_to_pay={safe_today}",
        f"forecast_window={forecast.request_date}..{forecast.horizon}",
        f"movements={len(forecast.movements)}",
    ]
    if earliest is not None:
        facts.append(f"earliest_full_payment={earliest}")
    facts.extend(f"uncertainty:{item}" for item in forecast.uncertainty)
    return tuple(facts)


def _degradation_reason(forecast: Forecast) -> Optional[str]:
    if forecast.certifiable:
        return None
    return (
        "unquantified obligation(s) remain, so no positive safe amount can be "
        "certified: " + "; ".join(forecast.uncertainty)
    )
