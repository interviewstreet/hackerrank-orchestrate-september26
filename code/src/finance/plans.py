from datetime import date, timedelta
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    PaymentOption,
    PaymentPlan,
    PaymentItem,
    PlanEvaluation,
    NormalizedFinancialEvent,
)
from code.src.finance.simulator import simulate_plan


def generate_candidate_plans(
    request: RequestContext,
    profile: UserFinancialProfile,
    options: list[PaymentOption],
    baseline_safe_amount: float,
    earliest_full_payment_date: date | None,
) -> list[PaymentPlan]:
    """
    Generates candidate payment plans based on:
    - Available options in request_payment_options.csv
    - Partial payment option if allowed and eligible
    - Wait option if full payment becomes safe later
    """
    plans: list[PaymentPlan] = []

    # 1. Full payment option(s) from options or default
    full_opts = [o for o in options if o.payment_method == "full_payment"]
    if full_opts:
        for opt in full_opts:
            plan = PaymentPlan(
                plan_id=opt.payment_option_id,
                method="full_payment",
                payments=[PaymentItem(payment_date=opt.first_payment_date, amount=opt.payment_amount)],
                total_amount=opt.total_payable_amount,
                financing_fee=opt.financing_fee,
                completion_date=opt.first_payment_date,
                payment_option_id=opt.payment_option_id,
            )
            plans.append(plan)
    else:
        # Default full payment today
        plans.append(
            PaymentPlan(
                plan_id="full_default",
                method="full_payment",
                payments=[PaymentItem(payment_date=request.request_date, amount=request.requested_amount)],
                total_amount=request.requested_amount,
                financing_fee=0.0,
                completion_date=request.request_date,
            )
        )

    # 2. Installment options from request_payment_options.csv
    inst_opts = [o for o in options if o.payment_method == "installments"]
    for opt in inst_opts:
        payments = []
        curr_d = opt.first_payment_date
        freq = opt.payment_frequency_days or 30
        for i in range(opt.number_of_payments):
            payments.append(PaymentItem(payment_date=curr_d, amount=opt.payment_amount))
            curr_d += timedelta(days=freq)

        last_payment_date = payments[-1].payment_date
        plan = PaymentPlan(
            plan_id=opt.payment_option_id,
            method="installments",
            payments=payments,
            total_amount=opt.total_payable_amount,
            financing_fee=opt.financing_fee,
            completion_date=last_payment_date,
            payment_option_id=opt.payment_option_id,
        )
        plans.append(plan)

    # 3. Partial payment (if request allows it and safe amount > 0 and < requested_amount)
    if (
        request.allows_partial_payment
        and "partial_payment" in profile.payment_methods_user_will_consider
        and 0 < baseline_safe_amount < request.requested_amount
        and earliest_full_payment_date is not None
        and earliest_full_payment_date <= request.desired_completion_date
    ):
        p1 = PaymentItem(payment_date=request.request_date, amount=baseline_safe_amount)
        p2 = PaymentItem(
            payment_date=earliest_full_payment_date,
            amount=round(request.requested_amount - baseline_safe_amount, 2),
        )
        plans.append(
            PaymentPlan(
                plan_id="partial_schedule",
                method="partial_payment",
                payments=[p1, p2],
                total_amount=request.requested_amount,
                financing_fee=0.0,
                completion_date=earliest_full_payment_date,
            )
        )

    # 4. Wait plan (if full payment becomes safe later)
    if earliest_full_payment_date is not None and earliest_full_payment_date > request.request_date:
        plans.append(
            PaymentPlan(
                plan_id=f"wait_{earliest_full_payment_date.isoformat()}",
                method="wait",
                payments=[PaymentItem(payment_date=earliest_full_payment_date, amount=request.requested_amount)],
                total_amount=request.requested_amount,
                financing_fee=0.0,
                completion_date=earliest_full_payment_date,
            )
        )

    return plans


def evaluate_plan(
    plan: PaymentPlan,
    request: RequestContext,
    profile: UserFinancialProfile,
    base_events: list[NormalizedFinancialEvent],
    horizon_days: int = 90,
) -> PlanEvaluation:
    """
    Evaluates a candidate plan across:
    1. Financial safety (simulation)
    2. Deadline feasibility (completion_date <= desired_completion_date)
    3. Payment method eligibility (allowed in user profile)
    4. Request satisfaction (total paid == requested_amount)
    """
    # 1. Financial simulation
    days_to_dl = (request.desired_completion_date - request.request_date).days + 1
    eval_horizon = min(horizon_days, max(30, days_to_dl))
    if plan.completion_date:
        days_to_comp = (plan.completion_date - request.request_date).days + 1
        eval_horizon = min(horizon_days, max(eval_horizon, days_to_comp))

    sim_res = simulate_plan(
        starting_balance=profile.current_available_balance,
        base_events=base_events,
        payment_plan=plan,
        minimum_balance=profile.minimum_balance_to_keep,
        start_date=request.request_date,
        horizon_days=eval_horizon,
    )

    financially_safe = sim_res["safe"]
    violations = sim_res["violations"]
    violation_codes = []
    violation_date = None
    if violations:
        violation_codes.append("BELOW_MINIMUM_BALANCE")
        violation_date = violations[0]["date"]

    # 2. Deadline check (HARD CONSTRAINT - Issue 2)
    deadline_ok = True
    if plan.completion_date and plan.completion_date > request.desired_completion_date:
        deadline_ok = False
        violation_codes.append("DEADLINE_EXCEEDED")

    # 3. Method allowed check (HARD CONSTRAINT)
    method_allowed = True
    if plan.method in ("full_payment", "partial_payment", "installments"):
        if plan.method not in profile.payment_methods_user_will_consider:
            method_allowed = False
            violation_codes.append("PAYMENT_METHOD_NOT_CONSIDERED")

    if plan.method == "installments":
        if profile.max_installment_months is not None and plan.payments:
            first_d = plan.payments[0].payment_date
            last_d = plan.payments[-1].payment_date
            duration_months = round((last_d - first_d).days / 30.0)
            if duration_months > profile.max_installment_months:
                method_allowed = False
                violation_codes.append("INSTALLMENT_TENOR_EXCEEDED")

    if plan.method == "wait":
        # User must accept full_payment to wait for full payment
        if "full_payment" not in profile.payment_methods_user_will_consider:
            method_allowed = False
            violation_codes.append("FULL_PAYMENT_NOT_CONSIDERED")

    # 4. Request satisfaction
    request_satisfied = True
    if plan.method != "not_recommended":
        total_principal = sum(p.amount for p in plan.payments) - plan.financing_fee
        if abs(total_principal - request.requested_amount) > 1.0:
            request_satisfied = False
            violation_codes.append("INCOMPLETE_REQUEST_AMOUNT")

    # Overall eligibility
    eligible = financially_safe and deadline_ok and method_allowed and request_satisfied

    return PlanEvaluation(
        plan_id=plan.plan_id,
        plan=plan,
        financially_safe=financially_safe,
        deadline_ok=deadline_ok,
        method_allowed=method_allowed,
        request_satisfied=request_satisfied,
        eligible=eligible,
        lowest_balance=sim_res["lowest_balance"],
        lowest_balance_date=sim_res["lowest_balance_date"],
        ending_balance=sim_res["ending_balance"],
        violation_codes=violation_codes,
        violation_date=violation_date,
        timeline=sim_res["timeline"],
    )
