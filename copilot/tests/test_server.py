import unittest
import io
import json
from unittest.mock import MagicMock
from pathlib import Path

from code.src.config import DATASET_DIR
from copilot.backend.state import AppState
from copilot.backend.engine import CopilotEngine
from copilot.backend.assistant import FinancialCopilotAssistant
from copilot.backend.server import CopilotRequestHandler


class DummyHandler(CopilotRequestHandler):
    def __init__(self, method, path, body=b""):
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = {"Content-Length": str(len(body))}
        self.path = path
        self.command = method
        self.requestline = f"{method} {path} HTTP/1.1"
        self.response_status = None
        self.response_headers = {}

    def send_response(self, code, message=None):
        self.response_status = code

    def send_header(self, keyword, value):
        self.response_headers[keyword] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self.response_status = code


class TestCopilotServerDirect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = AppState(DATASET_DIR)
        cls.engine = CopilotEngine(cls.state)
        cls.assistant = FinancialCopilotAssistant(cls.engine)

        CopilotRequestHandler.state = cls.state
        CopilotRequestHandler.engine = cls.engine
        CopilotRequestHandler.assistant = cls.assistant

    def test_get_users(self):
        handler = DummyHandler("GET", "/api/users")
        handler.do_GET()
        self.assertEqual(handler.response_status, 200)
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("users", data)
        self.assertGreater(len(data["users"]), 0)

    def test_get_summary(self):
        handler = DummyHandler("GET", "/api/summary?user_id=user_01")
        handler.do_GET()
        self.assertEqual(handler.response_status, 200)
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(data["user_id"], "user_01")
        self.assertIn("safe_headroom_today", data)

    def test_post_evaluate(self):
        payload = json.dumps({
            "user_id": "user_01",
            "item_name": "Test Item",
            "amount": 50.0,
            "category": "shopping"
        }).encode("utf-8")
        handler = DummyHandler("POST", "/api/evaluate", payload)
        handler.do_POST()
        self.assertEqual(handler.response_status, 200)
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("affordability_status", data)
        self.assertIn("chart_timeline", data)

    def test_post_chat(self):
        payload = json.dumps({
            "user_id": "user_01",
            "message": "Can I buy shoes for $80?"
        }).encode("utf-8")
        handler = DummyHandler("POST", "/api/chat", payload)
        handler.do_POST()
        self.assertEqual(handler.response_status, 200)
        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(data["role"], "assistant")
        self.assertIn("content", data)


if __name__ == "__main__":
    unittest.main()
