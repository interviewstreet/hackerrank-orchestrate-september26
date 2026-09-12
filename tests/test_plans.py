"""Unit tests for plan generation, payment methods, ranking, and decision engine."""

from __future__ import annotations

import sys
from datetime import date
import pandas as pd
import pytest

sys.path.insert(0, "code")
from models import (
    CandidatePlan,
    Payment,
    SpendingChange,
    _format_money,
    format_payment_plan,
    format_spending_changes,
)
from plans import generate_candidates, make_decision, rank_key


def test_money_formatting():
    assert _format_money(100.0) == "100"
    assert _format_money(100.5) == "100.50"
    assert _format_money(100.55) == "100.55"
    assert _format_money(0.0) == "0"


def test_payment_plan_formatting():
    payments = [
        Payment(date(2026, 1, 15), 200.0),
        Payment(date(2026, 1, 1), 100.0),
    ]
    assert format_payment_plan(payments) == "2026-01-01:100|2026-01-15:200"
    assert format_payment_plan([]) == "none"


def test_spending_changes_formatting():
    changes = [
        SpendingChange("stop", "ev_1"),
        SpendingChange("reduce", "ev_2", 45.50),
    ]
    assert format_spending_changes(changes) == "stop:ev_1|reduce_to:ev_2:45.50"
    assert format_spending_changes([]) == "none"


def test_candidate_ranking_order():
    p1 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p2 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 50)], meets_deadline=False, total_paid=50)
    assert rank_key(p1) < rank_key(p2)

    p3 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, spending_changes=[], total_paid=100)
    p4 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 50)], meets_deadline=True, spending_changes=[SpendingChange("stop", "e1")], total_paid=50)
    assert rank_key(p3) < rank_key(p4)

    p5 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p6 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 120)], meets_deadline=True, total_paid=120)
    assert rank_key(p5) < rank_key(p6)

    p7 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p8 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 5), 100)], meets_deadline=True, total_paid=100)
    assert rank_key(p7) < rank_key(p8)

    p9 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p10 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 50), Payment(date(2026, 2, 1), 50)], meets_deadline=True, total_paid=100)
    assert rank_key(p9) < rank_key(p10)

    p11 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100, payment_option_id="opt_01")
    p12 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100, payment_option_id="opt_02")
    assert rank_key(p11) < rank_key(p12)


def test_full_payment_affordable_now():
    req = pd.Series({
        "request_id": "r_full",
        "user_id": "u1",
        "request_date": "2026-01-01",
        "desired_completion_date": "2026-01-10",
        "requested_amount": 300.0,
        "allows_partial_payment": "false",
    })
    prof = pd.Series({
        "user_id": "u1",
        "home_currency": "USD",
        "current_available_balance": 1000.0,
        "minimum_balance_to_keep": 200.0,
        "payment_methods_user_will_consider": "full_payment",
    })
    ev = pd.DataFrame([])
    opts = pd.DataFrame([])

    d = make_decision(req, prof, ev, opts)
    assert d.affordability_status == "affordable_now"
    assert d.recommended_payment_method == "full_payment"
    assert d.payment_plan == "2026-01-01:300"
    assert d.earliest_date_for_full_payment == "2026-01-01"
    assert d.spending_changes_needed == "none"


def test_partial_payment_rules():
    req = pd.Series({
        "request_id": "r_part",
        "user_id": "u1",
        "request_date": "2026-01-01",
        "desired_completion_date": "2026-01-20",
        "requested_amount": 500.0,
        "allows_partial_payment": "true",
    })
    prof = pd.Series({
        "user_id": "u1",
        "home_currency": "USD",
        "current_available_balance": 400.0,
        "minimum_balance_to_keep": 200.0,
        "payment_methods_user_will_consider": "partial_payment",
    })
    ev = pd.DataFrame([
        {
            "event_id": "sal_1",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 1000.0,
            "currency": "USD",
            "event_date": "2026-01-15",
            "settlement_date": "2026-01-15",
            "status": "scheduled",
        }
    ])
    opts = pd.DataFrame([])

    d = make_decision(req, prof, ev, opts)
    assert d.affordability_status == "affordable_with_plan"
    assert d.recommended_payment_method == "partial_payment"
    assert d.amount_safe_to_pay == 200.0
    assert d.payment_plan == "2026-01-01:200|2026-01-15:300"
    assert d.earliest_date_for_full_payment == "2026-01-15"
