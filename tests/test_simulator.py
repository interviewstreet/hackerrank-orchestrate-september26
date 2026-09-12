from datetime import date
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    NormalizedFinancialEvent,
    PaymentPlan,
    PaymentItem,
)
from code.src.finance.simulator import simulate_plan
from code.src.finance.plans import evaluate_plan


def test_temporary_dip_violates_safety():
    """
    Day 10: balance = 8,000
    Day 30: balance = 50,000
    Minimum = 10,000
    Expected: safe = False (even though ending balance is 50,000!)
    """
    events = [
        NormalizedFinancialEvent(
            event_id="exp1",
            user_id="u1",
            event_type="expense",
            description="Big expense",
            category="other",
            direction="debit",
            amount=12000.0,
            currency="USD",
            converted_amount=12000.0,
            event_date=date(2024, 1, 10),
            settlement_date=date(2024, 1, 10),
            status="settled",
            flexibility="fixed",
        ),
        NormalizedFinancialEvent(
            event_id="sal1",
            user_id="u1",
            event_type="income",
            description="Salary",
            category="salary",
            direction="credit",
            amount=42000.0,
            currency="USD",
            converted_amount=42000.0,
            event_date=date(2024, 1, 30),
            settlement_date=date(2024, 1, 30),
            status="settled",
            flexibility="fixed",
        ),
    ]

    res = simulate_plan(
        starting_balance=20000.0,
        base_events=events,
        payment_plan=None,
        minimum_balance=10000.0,
        start_date=date(2024, 1, 1),
        horizon_days=90,
    )

    assert res["lowest_balance"] == 8000.0
    assert res["ending_balance"] == 50000.0
    assert res["safe"] is False
    assert len(res["violations"]) > 0


def test_deadline_hard_constraint():
    req = RequestContext(
        request_id="r1",
        user_id="u1",
        request_date=date(2024, 1, 1),
        request_type="purchase",
        requested_amount=1000.0,
        desired_completion_date=date(2024, 1, 15),
        allows_partial_payment=True,
        request_text="Buy laptop",
    )
    prof = UserFinancialProfile(
        user_id="u1",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=1000.0,
        payment_methods_user_will_consider=["full_payment", "installments"],
    )

    # Plan that finishes on Jan 20 (after desired_completion_date Jan 15)
    late_plan = PaymentPlan(
        plan_id="late_inst",
        method="installments",
        payments=[
            PaymentItem(payment_date=date(2024, 1, 5), amount=500.0),
            PaymentItem(payment_date=date(2024, 1, 20), amount=500.0),
        ],
        total_amount=1000.0,
        completion_date=date(2024, 1, 20),
    )

    ev = evaluate_plan(late_plan, req, prof, [])
    assert ev.deadline_ok is False
    assert ev.eligible is False
    assert "DEADLINE_EXCEEDED" in ev.violation_codes


def test_user_refuses_installments():
    req = RequestContext(
        request_id="r2",
        user_id="u2",
        request_date=date(2024, 1, 1),
        request_type="purchase",
        requested_amount=1000.0,
        desired_completion_date=date(2024, 6, 1),
        allows_partial_payment=False,
        request_text="Buy furniture",
    )
    prof = UserFinancialProfile(
        user_id="u2",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=1000.0,
        payment_methods_user_will_consider=["full_payment"],  # No installments
        max_installment_months=None,
    )

    plan = PaymentPlan(
        plan_id="inst_plan",
        method="installments",
        payments=[
            PaymentItem(payment_date=date(2024, 1, 1), amount=500.0),
            PaymentItem(payment_date=date(2024, 2, 1), amount=500.0),
        ],
        total_amount=1000.0,
        completion_date=date(2024, 2, 1),
    )

    ev = evaluate_plan(plan, req, prof, [])
    assert ev.method_allowed is False
    assert ev.eligible is False
    assert "PAYMENT_METHOD_NOT_CONSIDERED" in ev.violation_codes


def test_installment_safe_while_full_unsafe():
    """
    Starting balance: 5,000, minimum to keep: 3,000.
    Requested amount: 3,000.
    Full payment today: drops balance to 2,000 (< 3,000) -> UNSAFE!
    Installments: 3 payments of 1,000 monthly, with 1,500 monthly income.
    -> SAFE!
    """
    req = RequestContext(
        request_id="r3",
        user_id="u3",
        request_date=date(2024, 1, 1),
        request_type="purchase",
        requested_amount=3000.0,
        desired_completion_date=date(2024, 4, 1),
        allows_partial_payment=False,
        request_text="Buy equipment",
    )
    prof = UserFinancialProfile(
        user_id="u3",
        home_currency="USD",
        current_available_balance=5000.0,
        minimum_balance_to_keep=3000.0,
        payment_methods_user_will_consider=["full_payment", "installments"],
        max_installment_months=6,
    )

    salaries = [
        NormalizedFinancialEvent(
            event_id="sal_feb",
            user_id="u3",
            event_type="income",
            description="Salary",
            category="salary",
            direction="credit",
            amount=1500.0,
            currency="USD",
            converted_amount=1500.0,
            event_date=date(2024, 1, 25),
            settlement_date=date(2024, 1, 25),
            status="settled",
            flexibility="fixed",
        ),
        NormalizedFinancialEvent(
            event_id="sal_mar",
            user_id="u3",
            event_type="income",
            description="Salary",
            category="salary",
            direction="credit",
            amount=1500.0,
            currency="USD",
            converted_amount=1500.0,
            event_date=date(2024, 2, 25),
            settlement_date=date(2024, 2, 25),
            status="settled",
            flexibility="fixed",
        ),
    ]

    full_plan = PaymentPlan(
        plan_id="full",
        method="full_payment",
        payments=[PaymentItem(payment_date=date(2024, 1, 1), amount=3000.0)],
        total_amount=3000.0,
        completion_date=date(2024, 1, 1),
    )

    inst_plan = PaymentPlan(
        plan_id="inst",
        method="installments",
        payments=[
            PaymentItem(payment_date=date(2024, 1, 1), amount=1000.0),
            PaymentItem(payment_date=date(2024, 2, 1), amount=1000.0),
            PaymentItem(payment_date=date(2024, 3, 1), amount=1000.0),
        ],
        total_amount=3000.0,
        completion_date=date(2024, 3, 1),
    )

    ev_full = evaluate_plan(full_plan, req, prof, salaries)
    assert ev_full.financially_safe is False
    assert ev_full.eligible is False

    ev_inst = evaluate_plan(inst_plan, req, prof, salaries)
    assert ev_inst.financially_safe is True
    assert ev_inst.eligible is True
