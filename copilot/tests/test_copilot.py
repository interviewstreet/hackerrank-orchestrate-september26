import unittest
from datetime import date
from pathlib import Path
import json

from code.src.config import DATASET_DIR
from copilot.backend.state import AppState
from copilot.backend.engine import CopilotEngine
from copilot.backend.assistant import FinancialCopilotAssistant


class TestCopilot(unittest.TestCase):
    def setUp(self):
        self.state = AppState(DATASET_DIR)
        self.engine = CopilotEngine(self.state)
        self.assistant = FinancialCopilotAssistant(self.engine)

    def test_indian_state_initialization(self):
        users = self.state.list_users()
        self.assertGreater(len(users), 0)
        # Verify active user is Indian persona
        self.assertEqual(self.state.active_user_id, "aarav_in")
        prof = self.state.get_profile("aarav_in")
        self.assertIsNotNone(prof)
        self.assertEqual(prof.home_currency, "INR")
        self.assertEqual(prof.current_available_balance, 85000.0)
        self.assertEqual(prof.minimum_balance_to_keep, 45000.0)

    def test_indian_financial_summary(self):
        summary = self.engine.get_financial_summary("aarav_in")
        self.assertEqual(summary["home_currency"], "INR")
        self.assertIn("current_balance", summary)
        self.assertIn("emergency_cushion", summary)
        self.assertIn("safe_headroom_today", summary)
        self.assertIn("upcoming_commitments", summary)
        self.assertGreater(summary["upcoming_30d_debits_total"], 0)

    def test_evaluate_affordable_indian_purchase(self):
        # A small purchase of ₹500 should be affordable now
        result = self.engine.evaluate_purchase(
            user_id="aarav_in",
            item_name="Book",
            amount=500.0,
        )
        self.assertEqual(result["currency"], "INR")
        self.assertIn("affordability_status", result)
        self.assertIn("chart_timeline", result)
        self.assertGreater(len(result["chart_timeline"]), 0)

    def test_evaluate_large_purchase_emi(self):
        # iPhone 16 evaluation in ₹ INR with 6-month EMI
        result = self.engine.evaluate_purchase(
            user_id="aarav_in",
            item_name="Apple iPhone 16",
            amount=79900.0,
            custom_installment_months=6,
        )
        self.assertEqual(result["currency"], "INR")
        self.assertIn(result["affordability_status"], ["affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"])
        self.assertIn("chart_timeline", result)

    def test_assistant_chat_upi_headroom_query(self):
        resp = self.assistant.handle_message("How much safe UPI budget do I have today?", user_id="aarav_in")
        self.assertEqual(resp["type"], "headroom_summary")
        self.assertIn("Financial Headroom (India", resp["content"])
        self.assertIn("₹", resp["content"])

    def test_assistant_chat_bills_and_emis_query(self):
        resp = self.assistant.handle_message("What bills and EMIs are due this month?", user_id="aarav_in")
        self.assertEqual(resp["type"], "bills_list")
        self.assertIn("Fixed Obligations & EMIs", resp["content"])
        self.assertIn("₹", resp["content"])

    def test_assistant_indian_purchase_query_lakh(self):
        resp = self.assistant.handle_message("Can I buy Royal Enfield for 1.5 lakh?", user_id="aarav_in")
        self.assertEqual(resp["type"], "purchase_evaluation")
        self.assertIn("STATUS:", resp["content"])
        self.assertIn("₹", resp["content"])
        self.assertEqual(resp["evaluation"]["requested_amount"], 150000.0)

    def test_assistant_indian_purchase_query_inr_emi(self):
        resp = self.assistant.handle_message("Can I buy iPhone 16 for ₹79,900 on 6-month EMI?", user_id="aarav_in")
        self.assertEqual(resp["type"], "purchase_evaluation")
        self.assertIn("STATUS:", resp["content"])
        self.assertIn("₹", resp["content"])
        self.assertEqual(resp["evaluation"]["requested_amount"], 79900.0)


if __name__ == "__main__":
    unittest.main()
