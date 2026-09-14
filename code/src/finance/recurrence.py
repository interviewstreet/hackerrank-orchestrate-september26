from datetime import date, timedelta
from collections import defaultdict
from code.src.models import FinancialEvent, NormalizedFinancialEvent

ONE_OFF_CATEGORIES = {
    "shopping",
    "travel",
    "emergency_expense",
    "investment_purchase",
    "investment_valuation",
    "investment_sale",
    "refund",
    "other",
}


def add_months(orig_date: date, months: int) -> date:
    """Adds `months` to `orig_date` preserving day of month as much as possible."""
    new_year = orig_date.year + (orig_date.month + months - 1) // 12
    new_month = (orig_date.month + months - 1) % 12 + 1
    import calendar
    max_days = calendar.monthrange(new_year, new_month)[1]
    new_day = min(orig_date.day, max_days)
    return date(new_year, new_month, new_day)


def generate_missing_recurrences(
    historical_events: list[FinancialEvent],
    request_date: date,
    horizon_days: int,
    explicit_future_events: list[FinancialEvent],
    user_home_currency: str,
) -> list[NormalizedFinancialEvent]:
    """
    Detects recurring patterns from settled historical transactions and projects them
    forward from request_date up to request_date + horizon_days.

    CRITICAL FIX (Issue 4):
    Ensures that if an occurrence already exists as an explicit future event
    (e.g., next confirmed salary, scheduled bill retry, pending debit),
    the recurrence engine MUST NOT generate a duplicate event.
    """
    horizon_end = request_date + timedelta(days=horizon_days)

    # 1. Index explicit future events by (category, settlement_date) and by (category, year, month)
    explicit_future_by_cat_date = set()
    explicit_future_by_cat_month = set()
    confirmed_salary_template: FinancialEvent | None = None

    for e in explicit_future_events:
        explicit_future_by_cat_date.add((e.category, e.settlement_date))
        explicit_future_by_cat_month.add((e.category, e.settlement_date.year, e.settlement_date.month))
        if e.category == "salary" and e.amount is not None:
            confirmed_salary_template = e

    # 2. Group historical settled events by category and description
    # One-off events and non-salary credits are excluded from recurrence
    groups = defaultdict(list)
    for e in historical_events:
        if e.category in ONE_OFF_CATEGORIES or (e.direction == "credit" and e.category != "salary"):
            continue
        if e.status == "settled" and e.settlement_date < request_date and e.amount is not None:
            groups[(e.category, e.direction, e.flexibility)].append(e)

    # Terminal salary detection: if user received a 'Final employer payroll' or similar, do not project future salary
    TERMINAL_SALARY_KEYWORDS = ("final", "severance", "terminal", "last paycheck")
    for key in list(groups.keys()):
        if key[0] == "salary":
            sal_events = groups[key]
            sal_events.sort(key=lambda x: x.settlement_date)
            latest_sal = sal_events[-1]
            if any(kw in latest_sal.description.lower() for kw in TERMINAL_SALARY_KEYWORDS):
                del groups[key]

    generated_events: list[NormalizedFinancialEvent] = []

    for (cat, direction, flexibility), cat_events in groups.items():
        if len(cat_events) < 2 and cat not in ("salary", "rent", "housing", "utilities", "subscription"):
            continue

        cat_events.sort(key=lambda x: x.settlement_date)
        dates = [e.settlement_date for e in cat_events]
        diffs = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        avg_diff = sum(diffs) / len(diffs) if diffs else 30.5

        # Representative template (the most recent occurrence)
        template = cat_events[-1]
        
        # Calculate representative amount
        if cat == "salary" and confirmed_salary_template is not None:
            rep_amount = confirmed_salary_template.amount
            day_of_month = confirmed_salary_template.settlement_date.day
        else:
            recent_amts = [e.amount for e in cat_events[-3:] if e.amount is not None]
            recent_amts.sort()
            rep_amount = recent_amts[len(recent_amts) // 2] if recent_amts else template.amount
            from collections import Counter
            days = [e.settlement_date.day for e in cat_events if e.settlement_date]
            day_of_month = Counter(days).most_common(1)[0][0] if days else template.settlement_date.day

        # Case A: Monthly recurrence
        if 25 <= avg_diff <= 35 or cat in ("salary", "rent", "housing", "utilities", "education", "debt_repayment", "insurance", "healthcare") or template.event_type == "subscription":
            curr_month_date = date(request_date.year, request_date.month, 1)
            for m in range(5):
                proj_date = add_months(curr_month_date, m)
                try:
                    import calendar
                    max_d = calendar.monthrange(proj_date.year, proj_date.month)[1]
                    target_date = date(proj_date.year, proj_date.month, min(day_of_month, max_d))
                except Exception:
                    continue

                if target_date < request_date:
                    continue
                if target_date > horizon_end:
                    break

                # CHECK FOR EXISTING EXPLICIT EVENT
                if (cat, target_date.year, target_date.month) in explicit_future_by_cat_month:
                    continue
                if (cat, target_date) in explicit_future_by_cat_date:
                    continue

                gen_ev = NormalizedFinancialEvent(
                    event_id=f"rec_{template.event_id}_{target_date.isoformat()}",
                    user_id=template.user_id,
                    event_type=template.event_type,
                    description=f"{template.description} (projected)",
                    category=template.category,
                    direction=direction,
                    amount=rep_amount,
                    currency=template.currency,
                    converted_amount=rep_amount,
                    event_date=target_date,
                    settlement_date=target_date,
                    status="scheduled",
                    linked_event_id=template.event_id,
                    flexibility=flexibility,
                    minimum_allowed_amount=template.minimum_allowed_amount,
                    is_recurring=True,
                    evidence_source="recurrence_engine",
                )
                generated_events.append(gen_ev)

        # Case B: Fixed interval cadence (groceries, transport, dining)
        elif 5 <= avg_diff < 25:
            cadence_days = round(avg_diff)
            next_date = dates[-1] + timedelta(days=cadence_days)
            while next_date <= request_date:
                next_date += timedelta(days=cadence_days)

            while next_date <= horizon_end:
                if (cat, next_date) in explicit_future_by_cat_date:
                    next_date += timedelta(days=cadence_days)
                    continue

                gen_ev = NormalizedFinancialEvent(
                    event_id=f"rec_{template.event_id}_{next_date.isoformat()}",
                    user_id=template.user_id,
                    event_type=template.event_type,
                    description=f"{template.description} (projected)",
                    category=template.category,
                    direction=direction,
                    amount=rep_amount,
                    currency=template.currency,
                    converted_amount=rep_amount,
                    event_date=next_date,
                    settlement_date=next_date,
                    status="scheduled",
                    linked_event_id=template.event_id,
                    flexibility=flexibility,
                    minimum_allowed_amount=template.minimum_allowed_amount,
                    is_recurring=True,
                    evidence_source="recurrence_engine",
                )
                generated_events.append(gen_ev)
                next_date += timedelta(days=cadence_days)

    return generated_events
