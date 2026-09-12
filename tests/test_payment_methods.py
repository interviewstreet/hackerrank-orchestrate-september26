from datetime import date, timedelta
import pandas as pd
import sys

sys.path.insert(0, 'code')
from plan_generator import generate_candidates
from decision_engine import make_decision

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
        "payment_methods_user_will_consider": "partial_payment",  # User only considers partial
    })
    # Salary comes in on Jan 15 (+1000)
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
    # Safe today is 200 (400 - 200). Second payment is 300 on 2026-01-15
    assert d.payment_plan == "2026-01-01:200|2026-01-15:300"
    assert d.spending_changes_needed == "none"

def test_installments_option_matching():
    req = pd.Series({
        "request_id": "r_inst",
        "user_id": "u1",
        "request_date": "2026-01-01",
        "desired_completion_date": "2026-03-31",
        "requested_amount": 600.0,
        "allows_partial_payment": "false",
    })
    prof = pd.Series({
        "user_id": "u1",
        "home_currency": "USD",
        "current_available_balance": 300.0,
        "minimum_balance_to_keep": 50.0,
        "payment_methods_user_will_consider": "installments",
        "max_installment_months": 3.0,
    })
    opts = pd.DataFrame([
        {
            "payment_option_id": "opt_01",
            "request_id": "r_inst",
            "payment_method": "installments",
            "first_payment_date": "2026-01-05",
            "number_of_payments": 3,
            "payment_frequency_days": 30,
            "payment_amount": 200.0,
            "total_payable_amount": 600.0,
        }
    ])
    # Future salary helps afford the installments
    ev = pd.DataFrame([
        {
            "event_id": "sal_1",
            "event_type": "income",
            "category": "salary",
            "direction": "credit",
            "amount": 500.0,
            "currency": "USD",
            "event_date": "2026-01-25",
            "settlement_date": "2026-01-25",
            "status": "scheduled",
        }
    ])
    
    d = make_decision(req, prof, ev, opts)
    assert d.affordability_status == "affordable_with_plan"
    assert d.recommended_payment_method == "installments"
    assert d.payment_plan == "2026-01-05:200|2026-02-04:200|2026-03-06:200"

def test_wait_payment_method():
    req = pd.Series({
        "request_id": "r_wait",
        "user_id": "u1",
        "request_date": "2026-01-01",
        "desired_completion_date": "2026-02-01",
        "requested_amount": 500.0,
        "allows_partial_payment": "false",
    })
    prof = pd.Series({
        "user_id": "u1",
        "home_currency": "USD",
        "current_available_balance": 100.0,
        "minimum_balance_to_keep": 50.0,
        "payment_methods_user_will_consider": "full_payment",
    })
    # Salary on Jan 15 (+1000) makes full payment safe on Jan 15
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
    assert d.affordability_status == "affordable_later"
    assert d.recommended_payment_method == "wait"
    assert d.payment_plan == "2026-01-15:500"
    assert d.earliest_date_for_full_payment == "2026-01-15"

def test_not_recommended_fallback():
    req = pd.Series({
        "request_id": "r_not",
        "user_id": "u1",
        "request_date": "2026-01-01",
        "desired_completion_date": "2026-01-10",
        "requested_amount": 5000.0,
        "allows_partial_payment": "false",
    })
    prof = pd.Series({
        "user_id": "u1",
        "home_currency": "USD",
        "current_available_balance": 100.0,
        "minimum_balance_to_keep": 50.0,
        "payment_methods_user_will_consider": "full_payment",
    })
    ev = pd.DataFrame([])
    opts = pd.DataFrame([])
    
    d = make_decision(req, prof, ev, opts)
    assert d.affordability_status == "not_affordable"
    assert d.recommended_payment_method == "not_recommended"
    assert d.payment_plan == "none"
    assert d.earliest_date_for_full_payment == ""
    assert d.spending_changes_needed == "none"
