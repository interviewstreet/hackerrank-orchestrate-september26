from datetime import date, timedelta
from code.src.models import NormalizedFinancialEvent, PaymentPlan, PaymentItem
from code.src.finance.simulator import simulate_plan


def calculate_baseline_amount_safe_to_pay(
    starting_balance: float,
    base_events: list[NormalizedFinancialEvent],
    minimum_balance: float,
    request_date: date,
    requested_amount: float,
    horizon_days: int = 90,
) -> float:
    """
    Calculates the maximum amount safe to pay today (request_date)
    BEFORE optional spending changes, maintaining minimum_balance until replenishment.
    Capped at [0, requested_amount].
    """
    # Find next confirmed credit/replenishment date
    fut_credits = [
        e for e in base_events
        if e.direction == "credit" and e.settlement_date > request_date and e.status != "pending"
    ]
    if fut_credits:
        h = max(1, (fut_credits[0].settlement_date - request_date).days)
    else:
        h = horizon_days

    res = simulate_plan(
        starting_balance=starting_balance,
        base_events=base_events,
        payment_plan=None,
        minimum_balance=minimum_balance,
        start_date=request_date,
        horizon_days=h,
    )

    lowest_balance = res["lowest_balance"]
    headroom = lowest_balance - minimum_balance

    if headroom <= 0:
        return 0.0

    safe_amount = min(requested_amount, headroom)
    return round(safe_amount, 2)


def calculate_earliest_full_payment_date(
    starting_balance: float,
    base_events: list[NormalizedFinancialEvent],
    minimum_balance: float,
    request_date: date,
    requested_amount: float,
    desired_completion_date: date | None = None,
    horizon_days: int = 90,
) -> date | None:
    """
    Finds the earliest date d in [request_date, request_date + horizon_days]
    where paying requested_amount in full on date d keeps the balance
    above minimum_balance for every day in the horizon.
    """
    horizon_end = request_date + timedelta(days=horizon_days)

    # 1. Check request_date first
    today_horizon = min(
        horizon_days,
        max(30, (desired_completion_date - request_date).days + 1 if desired_completion_date else 30),
    )
    plan_today = PaymentPlan(
        plan_id="full_today",
        method="full_payment",
        payments=[PaymentItem(payment_date=request_date, amount=requested_amount)],
        total_amount=requested_amount,
        completion_date=request_date,
    )
    res_today = simulate_plan(
        starting_balance=starting_balance,
        base_events=base_events,
        payment_plan=plan_today,
        minimum_balance=minimum_balance,
        start_date=request_date,
        horizon_days=today_horizon,
    )
    if res_today["safe"]:
        return request_date

    # 2. Check candidate dates: dates where income arrives (credits) or completion date
    credit_dates = set()
    for e in base_events:
        if e.direction == "credit" and request_date <= e.settlement_date <= horizon_end:
            credit_dates.add(e.settlement_date)

    if desired_completion_date and request_date <= desired_completion_date <= horizon_end:
        credit_dates.add(desired_completion_date)

    candidate_dates = sorted(list(credit_dates))

    for cand_date in candidate_dates:
        if cand_date < request_date:
            continue
        plan_cand = PaymentPlan(
            plan_id=f"full_{cand_date.isoformat()}",
            method="full_payment",
            payments=[PaymentItem(payment_date=cand_date, amount=requested_amount)],
            total_amount=requested_amount,
            completion_date=cand_date,
        )
        if desired_completion_date and cand_date == desired_completion_date:
            cand_horizon = (desired_completion_date - request_date).days + 1
        elif desired_completion_date:
            cand_horizon = min(
                horizon_days,
                max((cand_date - request_date).days + 30, (desired_completion_date - request_date).days),
            )
        else:
            cand_horizon = min(horizon_days, (cand_date - request_date).days + 30)

        res_cand = simulate_plan(
            starting_balance=starting_balance,
            base_events=base_events,
            payment_plan=plan_cand,
            minimum_balance=minimum_balance,
            start_date=request_date,
            horizon_days=cand_horizon,
        )
        if res_cand["safe"]:
            return cand_date

    return None
