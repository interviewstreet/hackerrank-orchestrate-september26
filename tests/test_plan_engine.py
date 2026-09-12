import unittest
from datetime import date, timedelta

from models import FinancialProfile, Request, FinancialEvent
from plan_generator import PlanGenerator
from decision_engine import DecisionEngine


class TestPlanGeneration(unittest.TestCase):
    def setUp(self):
        self.profile = FinancialProfile(
            user_id="u1",
            home_currency="USD",
            current_balance=10000.0,
            minimum_balance_to_keep=1000.0,
            priorities=[],
            protected_spending_categories=[],
            flexible_spending_categories=["entertainment", "shopping"],
            payment_preferences=["partial", "installments"],
            max_installment_months=None,
        )
        self.request = Request(
            request_id="r1",
            user_id="u1",
            requested_amount=5000.0,
            request_date=date.today(),
            desired_completion_date=date.today() + timedelta(days=30),
        )
        self.events = []
        self.generator = PlanGenerator()
        self.engine = DecisionEngine()

    def test_candidate_count(self):
        candidates = self.generator.generate_candidates(self.request, self.profile, self.events)
        self.assertGreaterEqual(len(candidates), 6)

    def test_full_payment_candidate(self):
        candidates = self.generator.generate_candidates(self.request, self.profile, self.events)
        full = next(c for c in candidates if c.recommended_payment_method == "full_payment")
        self.assertEqual(full.amount_safe_to_pay, self.request.requested_amount)
        self.assertEqual(full.affordability_status, "affordable_now")

    def test_partial_allowed(self):
        candidates = self.generator.generate_candidates(self.request, self.profile, self.events)
        partial = next(c for c in candidates if c.recommended_payment_method == "partial_payment" and c.amount_safe_to_pay < self.request.requested_amount)
        self.assertTrue(partial.amount_safe_to_pay > 0)

    def test_ranking_prefers_full_without_spending(self):
        candidates = self.generator.generate_candidates(self.request, self.profile, self.events)
        for c in candidates:
            if c.recommended_payment_method == "full_payment":
                c.meets_deadline = True
                c.uses_spending_changes = False
                c.total_paid = c.amount_safe_to_pay
                c.start_date = self.request.request_date
                c.payment_count = 1
                c.payment_option_id = None
        best = self.engine.select_best_plan(candidates)
        self.assertEqual(best.recommended_payment_method, "full_payment")

if __name__ == '__main__':
    unittest.main()
