import http.server
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import date

from code.src.config import DATASET_DIR
from copilot.backend.state import AppState
from copilot.backend.engine import CopilotEngine
from copilot.backend.assistant import FinancialCopilotAssistant

STATIC_DIR = Path(__file__).parent.parent / "static"


class CopilotRequestHandler(http.server.BaseHTTPRequestHandler):
    state: AppState = None
    engine: CopilotEngine = None
    assistant: FinancialCopilotAssistant = None

    def _send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path):
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "File Not Found")
            return
        
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"
        
        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if "text" in mime_type else mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html")
            return

        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            target_file = STATIC_DIR / rel_path
            self._send_file(target_file)
            return

        # API routes
        if path == "/api/users":
            users = self.state.list_users()
            self._send_json({"users": users, "active_user_id": self.state.active_user_id})
            return

        if path == "/api/summary":
            qs = parse_qs(parsed.query)
            user_id = qs.get("user_id", [None])[0]
            summary = self.engine.get_financial_summary(user_id)
            self._send_json(summary)
            return

        if path == "/api/chat/history":
            self._send_json({"history": self.state.chat_history})
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            payload = {}

        if path == "/api/user/select":
            user_id = payload.get("user_id")
            if user_id and self.state.set_active_user(user_id):
                summary = self.engine.get_financial_summary(user_id)
                self._send_json({"success": True, "active_user_id": user_id, "summary": summary})
            else:
                self._send_json({"error": "Invalid user_id"}, 400)
            return

        if path == "/api/profile":
            updated = self.state.update_profile(payload)
            summary = self.engine.get_financial_summary(updated.user_id)
            self._send_json({"success": True, "profile": updated.dict(), "summary": summary})
            return

        if path == "/api/event/add":
            new_event = self.state.add_custom_event(payload)
            summary = self.engine.get_financial_summary(new_event.user_id)
            self._send_json({"success": True, "event": new_event.dict(), "summary": summary})
            return

        if path == "/api/evaluate":
            item_name = payload.get("item_name", "Requested Item")
            amount = float(payload.get("amount", 0.0))
            category = payload.get("category", "shopping")
            user_id = payload.get("user_id", self.state.active_user_id)
            req_d = date.fromisoformat(payload["request_date"]) if payload.get("request_date") else date.today()
            willing_to_adjust = payload.get("willing_to_adjust_spending", True)
            custom_installments = int(payload["custom_installment_months"]) if payload.get("custom_installment_months") else None

            result = self.engine.evaluate_purchase(
                user_id=user_id,
                item_name=item_name,
                amount=amount,
                request_date=req_d,
                category=category,
                custom_installment_months=custom_installments,
                willing_to_adjust_spending=willing_to_adjust,
            )
            self._send_json(result)
            return

        if path == "/api/chat":
            user_text = payload.get("message", "")
            user_id = payload.get("user_id", self.state.active_user_id)
            
            # Record user turn in chat history
            self.state.chat_history.append({
                "role": "user",
                "timestamp": date.today().strftime("%H:%M"),
                "content": user_text,
            })

            assistant_reply = self.assistant.handle_message(user_text, user_id=user_id)
            self.state.chat_history.append(assistant_reply)

            self._send_json(assistant_reply)
            return

        self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        # Clean logging
        return


def create_server(host: str = "127.0.0.1", port: int = 8000, dataset_dir: Path = DATASET_DIR):
    state = AppState(dataset_dir)
    engine = CopilotEngine(state)
    assistant = FinancialCopilotAssistant(engine)

    CopilotRequestHandler.state = state
    CopilotRequestHandler.engine = engine
    CopilotRequestHandler.assistant = assistant

    server = http.server.ThreadingHTTPServer((host, port), CopilotRequestHandler)
    return server
