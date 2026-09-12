from datetime import date
import sys

sys.path.insert(0, 'code')
from models import (
    CandidatePlan,
    Payment,
    SpendingChange,
    format_payment_plan,
    format_spending_changes,
    _format_money,
)
from plan_generator import rank_key

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
    # Formats in chronological order
    formatted = format_payment_plan(payments)
    assert formatted == "2026-01-01:100|2026-01-15:200"
    
    assert format_payment_plan([]) == "none"

def test_spending_changes_formatting():
    changes = [
        SpendingChange("stop", "ev_1"),
        SpendingChange("reduce", "ev_2", 45.50),
    ]
    formatted = format_spending_changes(changes)
    assert formatted == "stop:ev_1|reduce_to:ev_2:45.50"
    
    assert format_spending_changes([]) == "none"

def test_candidate_ranking_order():
    # 1. Meets deadline beats does not meet deadline
    p1 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p2 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 50)], meets_deadline=False, total_paid=50)
    assert rank_key(p1) < rank_key(p2)
    
    # 2. No spending changes beats with spending changes
    p3 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, spending_changes=[], total_paid=100)
    p4 = CandidatePlan(method="full_payment", payments=[Payment(date(2026, 1, 1), 50)], meets_deadline=True, spending_changes=[SpendingChange("stop", "e1")], total_paid=50)
    assert rank_key(p3) < rank_key(p4)
    
    # 3. Lowest total paid
    p5 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p6 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 120)], meets_deadline=True, total_paid=120)
    assert rank_key(p5) < rank_key(p6)
    
    # 4. Earliest start date
    p7 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p8 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 5), 100)], meets_deadline=True, total_paid=100)
    assert rank_key(p7) < rank_key(p8)
    
    # 5. Fewer payments
    p9 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100)
    p10 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 50), Payment(date(2026, 2, 1), 50)], meets_deadline=True, total_paid=100)
    assert rank_key(p9) < rank_key(p10)
    
    # 6. Lowest payment_option_id tie-breaker
    p11 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100, payment_option_id="opt_01")
    p12 = CandidatePlan(method="installments", payments=[Payment(date(2026, 1, 1), 100)], meets_deadline=True, total_paid=100, payment_option_id="opt_02")
    assert rank_key(p11) < rank_key(p12)
