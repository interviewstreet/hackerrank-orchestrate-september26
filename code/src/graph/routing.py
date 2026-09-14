from typing import Literal
from code.src.state import AgentState


def route_after_evaluation(state: AgentState) -> Literal["select_decision", "generate_change_sets"]:
    """
    Conditional edge router:
    If an immediate plan (full payment today, installments, or partial payment) is already safe,
    route directly to decision selection.
    If no immediate plan is safe (i.e. only wait or nothing is safe), explore spending changes
    to see if the user can safely complete the request without waiting.
    """
    evaluated_plans = state.get("evaluated_plans", [])
    has_immediate_safe_plan = any(
        ev.eligible and ev.plan.method in ("full_payment", "installments", "partial_payment")
        for ev in evaluated_plans
    )

    if has_immediate_safe_plan:
        return "select_decision"
    return "generate_change_sets"
