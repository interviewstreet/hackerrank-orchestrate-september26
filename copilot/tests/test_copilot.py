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

    def test_state_initialization(self):
        users = self.state.list_users()
        self.assertGreater(len(users), 0)
        prof = self.state.get_profile("user_01")
        self.assertIsNotNone(prof)
        self.assertGreater(prof.current_available_balance, 0)

    def test_financial_summary(self):
        summary = self.engine.get_financial_summary("user_01")
        self.assertIn("current_balance", summary)
        self.assertIn("emergency_cushion", summary)
        self.assertIn("safe_headroom_today", summary)
        self.assertIn("upcoming_commitments", summary)

    def test_evaluate_affordable_purchase(self):
        # A tiny purchase of $10 should be affordable now if headroom exists
        result = self.engine.evaluate_purchase(
            user_id="user_01",
            item_name="Book",
            amount=10.0,
        )
        self.assertIn("affordability_status", result)
        self.assertIn("chart_timeline", result)
        self.assertGreater(len(result["chart_timeline"]), 0)

    def test_evaluate_large_purchase(self):
        # A giant purchase of $1,000,000 should not be affordable
        result = self.engine.evaluate_purchase(
            user_id="user_01",
            item_name="Luxury Yacht",
            amount=1_000_000.0,
        )
        self.assertEqual(result["affordability_status"], "not_affordable")
        self.assertIn("not recommended", result["explanation"].lower())

    def test_assistant_chat_headroom_query(self):
        resp = self.assistant.handle_message("How much can I safely spend today?", user_id="user_01")
        self.assertEqual(resp["type"], "headroom_summary")
        self.assertIn("Safe Discretionary Headroom Today", resp["content"])

    def test_assistant_chat_bills_query(self):
        resp = self.assistant.handle_message("What bills are coming up in next 30 days?", user_id="user_01")
        self.assertEqual(resp["type"], "bills_list")
        self.assertIn("Upcoming Financial Obligations", resp["content"])

    def test_assistant_purchase_query(self):
        resp = self.assistant.handle_message("Can I buy a tablet for $200?", user_id="user_01")
        self.assertEqual(resp["type"], "purchase_evaluation")
        self.assertIn("STATUS:", resp["content"])
        self.assertIn("evaluation", resp)


if __name__ == "__main__":
    unittest.main()
