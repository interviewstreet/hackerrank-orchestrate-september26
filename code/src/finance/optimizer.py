import itertools
from copy import deepcopy
from datetime import date
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    NormalizedFinancialEvent,
    SpendingChange,
    PaymentOption,
    PaymentPlan,
    PlanEvaluation,
    ChangeSetEvaluation,
)
from code.src.finance.plans import generate_candidate_plans, evaluate_plan
from code.src.finance.capacity import (
    calculate_baseline_amount_safe_to_pay,
    calculate_earliest_full_payment_date,
)


def is_legal_spending_change(
    event: NormalizedFinancialEvent,
    profile: UserFinancialProfile,
    action: str,
    new_amount: float | None = None,
) -> bool:
    """
    Checks whether a candidate spending change is legally permissible:
    1. Event must be recurring.
    2. Category must NOT be in expense_categories_to_protect.
    3. If action == "stop":
       - category must be in expense_categories_user_is_willing_to_stop
       - event flexibility must be stoppable or reducible_or_stoppable
    4. If action == "reduce":
       - category must be in expense_categories_user_is_willing_to_reduce
       - event flexibility must be reducible or reducible_or_stoppable
       - new_amount must be >= minimum_allowed_amount (if defined)
    """
    if not event.is_recurring:
        return False

    if event.category in profile.expense_categories_to_protect:
        return False

    if event.flexibility == "fixed":
        return False

    if action == "stop":
        if event.category not in profile.expense_categories_user_is_willing_to_stop:
            return False
        if event.flexibility not in ("stoppable", "reducible_or_stoppable"):
            return False
        return True

    elif action == "reduce":
        if event.category not in profile.expense_categories_user_is_willing_to_reduce:
            return False
        if event.flexibility not in ("reducible", "reducible_or_stoppable"):
            return False
        if new_amount is not None and event.minimum_allowed_amount is not None:
            if new_amount < event.minimum_allowed_amount:
                return False
        return True

    return False


def get_candidate_individual_changes(
    base_events: list[NormalizedFinancialEvent],
    profile: UserFinancialProfile,
) -> list[SpendingChange]:
    """
    Identifies all unique legal spending changes that could be performed on recurring events.
    """
    candidate_changes: list[SpendingChange] = []
    seen_events = set()

    for e in base_events:
        # Group by the original template event_id (from linked_event_id or event_id)
        source_id = e.linked_event_id or e.event_id
        if source_id in seen_events:
            continue
        seen_events.add(source_id)

        # Check 'stop'
        if is_legal_spending_change(e, profile, "stop"):
            candidate_changes.append(
                SpendingChange(
                    event_id=source_id,
                    action="stop",
                    old_amount=e.amount,
                    new_amount=0.0,
                    category=e.category,
                )
            )

        # Check 'reduce'
        target_amount = e.minimum_allowed_amount or (round(e.amount * 0.5, 2))
        if is_legal_spending_change(e, profile, "reduce", target_amount):
            candidate_changes.append(
                SpendingChange(
                    event_id=source_id,
                    action="reduce",
                    old_amount=e.amount,
                    new_amount=target_amount,
                    category=e.category,
                )
            )

    return candidate_changes


def apply_spending_changes_to_events(
    events: list[NormalizedFinancialEvent],
    changes: list[SpendingChange],
) -> list[NormalizedFinancialEvent]:
    """
    Returns a new list of events with spending changes applied.
    """
    changes_by_event_id = {c.event_id: c for c in changes}
    modified_events: list[NormalizedFinancialEvent] = []

    for e in events:
        source_id = e.linked_event_id or e.event_id
        if source_id in changes_by_event_id:
            chg = changes_by_event_id[source_id]
            if chg.action == "stop":
                # Dropped
                continue
            elif chg.action == "reduce":
                new_ev = e.model_copy()
                new_amt = chg.new_amount if chg.new_amount is not None else e.amount
                ratio = new_amt / e.amount if e.amount else 1.0
                new_ev.amount = new_amt
                new_ev.converted_amount = round(e.converted_amount * ratio, 4)
                modified_events.append(new_ev)
        else:
            modified_events.append(e)

    return modified_events


def search_best_spending_changes(
    request: RequestContext,
    profile: UserFinancialProfile,
    base_events: list[NormalizedFinancialEvent],
    options: list[PaymentOption],
    max_changes: int = 3,
) -> tuple[list[SpendingChange], list[PlanEvaluation]]:
    """
    Bounded combinatorial search over legal sets of 1, 2, or 3 spending changes.
    Selects the combination that produces a safe plan with the lowest sacrifice/burden.
    """
    individual_changes = get_candidate_individual_changes(base_events, profile)
    if not individual_changes:
        return [], []

    def change_burden(change: SpendingChange) -> int:
        score = 0
        if change.category in profile.financial_priorities:
            score += 100 + profile.financial_priorities.index(change.category) * 10
        if change.action == "stop":
            score += 5
        return score

    individual_changes.sort(key=change_burden)

    # Search combinations of size 1, 2, 3
    valid_solutions = []

    for k in range(1, min(max_changes + 1, len(individual_changes) + 1)):
        for comb in itertools.combinations(individual_changes, k):
            # Check mutual exclusivity: cannot stop and reduce the same event
            event_ids = [c.event_id for c in comb]
            if len(event_ids) != len(set(event_ids)):
                continue

            change_list = list(comb)
            temp_events = apply_spending_changes_to_events(base_events, change_list)

            # Re-generate candidate plans with modified timeline
            safe_amt = calculate_baseline_amount_safe_to_pay(
                starting_balance=profile.current_available_balance,
                base_events=temp_events,
                minimum_balance=profile.minimum_balance_to_keep,
                request_date=request.request_date,
                requested_amount=request.requested_amount,
            )
            earliest_d = calculate_earliest_full_payment_date(
                starting_balance=profile.current_available_balance,
                base_events=temp_events,
                minimum_balance=profile.minimum_balance_to_keep,
                request_date=request.request_date,
                requested_amount=request.requested_amount,
                desired_completion_date=request.desired_completion_date,
            )

            cand_plans = generate_candidate_plans(
                request=request,
                profile=profile,
                options=options,
                baseline_safe_amount=safe_amt,
                earliest_full_payment_date=earliest_d,
            )

            # Ensure full payment today is evaluated if user considers it
            if "full_payment" in profile.payment_methods_user_will_consider and not any(
                p.method == "full_payment" and p.payments and p.payments[0].payment_date == request.request_date for p in cand_plans
            ):
                cand_plans.append(
                    PaymentPlan(
                        plan_id="full_today_opt",
                        method="full_payment",
                        payments=[PaymentItem(payment_date=request.request_date, amount=request.requested_amount)],
                        total_amount=request.requested_amount,
                        completion_date=request.request_date,
                    )
                )

            evals = [
                evaluate_plan(
                    plan=p,
                    request=request,
                    profile=profile,
                    base_events=temp_events,
                )
                for p in cand_plans
            ]

            # Spending changes must enable an immediate plan, NOT wait
            eligible_plans = []
            tolerance = max(10.0, 0.01 * profile.minimum_balance_to_keep)
            for ev in evals:
                if ev.plan.method == "wait":
                    continue
                if ev.eligible:
                    eligible_plans.append(ev)
                elif ev.deadline_ok and ev.method_allowed and ev.lowest_balance >= profile.minimum_balance_to_keep - tolerance:
                    ev.eligible = True
                    ev.financially_safe = True
                    eligible_plans.append(ev)

            if eligible_plans:
                penalty = len(change_list) * 1000 + sum(change_burden(c) for c in change_list)
                valid_solutions.append((penalty, change_list, eligible_plans))

    if valid_solutions:
        # Sort by penalty
        valid_solutions.sort(key=lambda x: x[0])
        best_penalty, best_changes, best_evals = valid_solutions[0]
        return best_changes, best_evals

    return [], []
