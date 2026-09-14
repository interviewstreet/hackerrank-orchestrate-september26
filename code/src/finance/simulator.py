from datetime import date, timedelta
from collections import defaultdict
from code.src.models import (
    NormalizedFinancialEvent,
    PaymentPlan,
    PaymentItem,
    DailyBalanceCheckpoint,
    PlanEvaluation,
)


def simulate_plan(
    starting_balance: float,
    base_events: list[NormalizedFinancialEvent],
    payment_plan: PaymentPlan | None,
    minimum_balance: float,
    start_date: date,
    horizon_days: int = 90,
) -> dict:
    """
    Simulates cash flow day by day over the horizon.
    CRITICAL FINANCIAL RULE:
    minimum_projected_balance >= minimum_balance must hold for EVERY day in the horizon.
    """
    horizon_end = start_date + timedelta(days=horizon_days)

    # Collect cash flows by date: date -> list of (amount, direction, description)
    daily_credits = defaultdict(float)
    daily_debits = defaultdict(float)
    daily_event_descs = defaultdict(list)

    # 1. Base events
    for e in base_events:
        if e.settlement_date < start_date or e.settlement_date > horizon_end:
            continue
        amt = e.converted_amount
        if e.direction == "credit":
            # Exclude pending credits
            if e.status != "pending":
                daily_credits[e.settlement_date] += amt
                daily_event_descs[e.settlement_date].append(f"+{amt} ({e.description})")
        elif e.direction == "debit":
            # Debits include settled, scheduled, and pending debits
            daily_debits[e.settlement_date] += amt
            daily_event_descs[e.settlement_date].append(f"-{amt} ({e.description})")

    # 2. Candidate plan payments
    if payment_plan and payment_plan.payments:
        for p in payment_plan.payments:
            if p.payment_date < start_date or p.payment_date > horizon_end:
                continue
            daily_debits[p.payment_date] += p.amount
            daily_event_descs[p.payment_date].append(f"-{p.amount} (Plan payment {payment_plan.plan_id})")

    # Collect all dates with transactions
    all_dates = set(daily_credits.keys()) | set(daily_debits.keys())
    all_dates.add(start_date)
    all_dates.add(horizon_end)
    sorted_dates = sorted(all_dates)

    current_balance = starting_balance
    lowest_balance = starting_balance
    lowest_balance_date = start_date
    violations = []
    timeline = []

    # Check start balance
    if current_balance < minimum_balance:
        violations.append({
            "date": start_date,
            "balance": current_balance,
            "minimum_balance": minimum_balance,
            "deficit": minimum_balance - current_balance,
        })

    for d in sorted_dates:
        cr = daily_credits.get(d, 0.0)
        db = daily_debits.get(d, 0.0)
        new_balance = round(current_balance + cr - db, 4)

        if new_balance < lowest_balance:
            lowest_balance = new_balance
            lowest_balance_date = d

        if new_balance < minimum_balance:
            violations.append({
                "date": d,
                "balance": new_balance,
                "minimum_balance": minimum_balance,
                "deficit": round(minimum_balance - new_balance, 4),
            })

        timeline.append({
            "date": d.isoformat(),
            "starting_balance": current_balance,
            "credits": cr,
            "debits": db,
            "ending_balance": new_balance,
            "events": daily_event_descs.get(d, []),
        })
        current_balance = new_balance

    is_safe = len(violations) == 0

    return {
        "safe": is_safe,
        "lowest_balance": lowest_balance,
        "lowest_balance_date": lowest_balance_date,
        "ending_balance": current_balance,
        "timeline": timeline,
        "violations": violations,
    }
