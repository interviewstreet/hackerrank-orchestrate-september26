import csv
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
DB_PATH = ROOT / "pocketwise.db"


def read_csv(name: str) -> list[dict[str, str]]:
	with (DATASET / name).open(encoding="utf-8", newline="") as handle:
		return list(csv.DictReader(handle))


profiles = {row["user_id"]: row for row in read_csv("financial_profiles.csv")}
events = read_csv("financial_events.csv")
requests = read_csv("requests.csv")
options = read_csv("request_payment_options.csv")
OUTPUT_COLUMNS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]

app = FastAPI(title="PocketWise AI", version="1.0.0", description="Grounded affordability decisions for everyday spending.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


def database() -> sqlite3.Connection:
	connection = sqlite3.connect(DB_PATH)
	connection.execute("CREATE TABLE IF NOT EXISTS chat_logs (id INTEGER PRIMARY KEY, user_id TEXT, query TEXT, response TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
	connection.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
	connection.commit()
	return connection


class DecisionRequest(BaseModel):
	user_id: str = "user_01"
	item: str
	amount: float
	request_date: str | None = None
	desired_completion_date: str | None = None


class ChatRequest(BaseModel):
	user_id: str = "user_01"
	query: str


class AuthRequest(BaseModel):
	name: str = "Maya Rodriguez"
	email: str
	password: str


def money(value: float) -> str:
	return f"{value:.2f}".rstrip("0").rstrip(".")


def password_hash(value: str) -> str:
	return hashlib.sha256(value.encode("utf-8")).hexdigest()


def account_snapshot(user_id: str) -> dict[str, Any]:
	profile = profiles.get(user_id, profiles["user_01"])
	user_events = [event for event in events if event["user_id"] == user_id]
	expense_events = [event for event in user_events if event["direction"] == "debit" and event["status"] in {"settled", "pending", "scheduled"}]
	recurring = sum(float(event["amount"] or 0) for event in expense_events if event["event_type"] in {"subscription", "expense", "debt_payment"}) / max(1, len(expense_events))
	return {
		"user_id": user_id,
		"currency": profile["home_currency"],
		"balance": float(profile["current_available_balance"]),
		"minimum_balance": float(profile["minimum_balance_to_keep"]),
		"salary_inflow": 0,
		"daily_expenses": round(recurring / 30, 2),
		"priorities": profile["financial_priorities"].split("|"),
		"protected": profile["expense_categories_to_protect"].split("|"),
		"alerts": ["Minimum balance protected", "No pending income counted"],
	}


def decide(payload: DecisionRequest) -> dict[str, Any]:
	account = account_snapshot(payload.user_id)
	request_date = date.fromisoformat(payload.request_date or date.today().isoformat())
	completion = date.fromisoformat(payload.desired_completion_date or (request_date + timedelta(days=30)).isoformat())
	available = max(0, account["balance"] - account["minimum_balance"])
	safe_now = min(payload.amount, available)
	selected = [option for option in options if option["request_id"] == next((row["request_id"] for row in requests if row["user_id"] == payload.user_id), "")]
	plans = [option for option in selected if option["payment_method"] == "installments" and int(float(option["number_of_payments"])) <= int(profiles.get(payload.user_id, profiles["user_01"]).get("max_installment_months") or 0)]
	plan = min(plans, key=lambda option: float(option["total_payable_amount"])) if plans else None
	if safe_now >= payload.amount:
		status, method, payment_plan, earliest = "affordable_now", "full_payment", f"{request_date}:{money(payload.amount)}", request_date.isoformat()
		explanation = f"Pay {account['currency']} {money(payload.amount)} today while keeping {account['currency']} {money(account['minimum_balance'])} protected."
	elif plan and float(plan["payment_amount"]) <= available:
		count = int(float(plan["number_of_payments"]))
		first = date.fromisoformat(plan["first_payment_date"])
		payment_plan = "|".join(f"{first + timedelta(days=int(float(plan['payment_frequency_days']))) * index}:{money(float(plan['payment_amount']))}" for index in range(count))
		status, method, earliest = "affordable_with_plan", "installments", (first + timedelta(days=int(float(plan["payment_frequency_days"]))) * (count - 1)).isoformat()
		explanation = f"Use {count} installments of {account['currency']} {money(float(plan['payment_amount']))}; the minimum balance stays protected."
	else:
		target = request_date + timedelta(days=14)
		status, method, payment_plan, earliest = "affordable_later", "wait", f"{target}:{money(payload.amount)}", target.isoformat()
		explanation = f"Wait until {target.isoformat()} so the {account['currency']} {money(account['minimum_balance'])} minimum remains protected."
	return {"amount_safe_to_pay": round(safe_now, 2), "affordability_status": status, "recommended_payment_method": method, "payment_plan": payment_plan, "earliest_date_for_full_payment": earliest, "spending_changes_needed": "none", "decision_explanation": explanation, "account": account, "item": payload.item, "requested_amount": payload.amount}


def as_amount(value: str | None) -> float:
	try:
		return float(value or 0)
	except ValueError:
		return 0.0


def event_amount(event: dict[str, str]) -> float:
	return as_amount(event.get("amount"))


def projected_balance(user_id: str, start: date, end: date, payments: list[tuple[date, float]] | None = None) -> float:
	profile = profiles[user_id]
	balance = as_amount(profile["current_available_balance"])
	user_events = [event for event in events if event["user_id"] == user_id]
	for event in user_events:
		settlement = event.get("settlement_date") or event.get("event_date")
		if not settlement:
			continue
		event_date = date.fromisoformat(settlement)
		if not start <= event_date <= end or event.get("status") in {"failed", "cancelled"}:
			continue
		amount = event_amount(event)
		if event.get("direction") == "credit" and event.get("status") in {"settled", "scheduled"}:
			balance += amount
		elif event.get("direction") == "debit" and event.get("status") in {"settled", "pending", "scheduled"}:
			balance -= amount
	for payment_date, amount in payments or []:
		if start <= payment_date <= end:
			balance -= amount
	return balance


def flexible_reduction(user_id: str, request_date: date, needed: float) -> tuple[str, float] | None:
	profile = profiles[user_id]
	allowed = set(filter(None, profile["expense_categories_user_is_willing_to_reduce"].split("|") + profile["expense_categories_user_is_willing_to_stop"].split("|")))
	candidates = [event for event in events if event["user_id"] == user_id and event.get("event_type") in {"subscription", "expense"} and event.get("category") in allowed and event.get("flexibility") in {"stoppable", "reducible"} and event.get("status") == "settled" and date.fromisoformat(event["event_date"]) < request_date]
	if not candidates:
		return None
	candidate = max(candidates, key=event_amount)
	return candidate["event_id"], min(needed, event_amount(candidate))


def installment_plan(request: dict[str, str], profile: dict[str, str], available: float) -> tuple[list[tuple[date, float]], float] | None:
	request_options = [option for option in options if option["request_id"] == request["request_id"] and option["payment_method"] == "installments"]
	max_months = as_amount(profile.get("max_installment_months"))
	request_date = date.fromisoformat(request["request_date"])
	deadline = date.fromisoformat(request["desired_completion_date"])
	valid = []
	for option in request_options:
		count = int(as_amount(option["number_of_payments"]))
		frequency = int(as_amount(option["payment_frequency_days"]))
		first = date.fromisoformat(option["first_payment_date"])
		last = first + timedelta(days=frequency * (count - 1))
		if (max_months and count > max_months) or last > deadline:
			continue
		payments = [(first + timedelta(days=frequency * index), as_amount(option["payment_amount"])) for index in range(count)]
		if payments[0][1] <= available:
			valid.append((payments, as_amount(option["total_payable_amount"])))
	return min(valid, key=lambda item: item[1]) if valid else None


def prediction_for(request: dict[str, str]) -> dict[str, str]:
	profile = profiles[request["user_id"]]
	request_date = date.fromisoformat(request["request_date"])
	deadline = date.fromisoformat(request["desired_completion_date"])
	amount = as_amount(request["requested_amount"])
	minimum = as_amount(profile["minimum_balance_to_keep"])
	horizon = request_date + timedelta(days=90)
	available = max(0.0, as_amount(profile["current_available_balance"]) - minimum)
	forecast_floor = projected_balance(request["user_id"], request_date, horizon)
	safe_now = max(0.0, min(amount, available, forecast_floor - minimum))
	changes = "none"
	if safe_now < amount:
		adjustment = flexible_reduction(request["user_id"], request_date, amount - safe_now)
		if adjustment:
			event_id, reduction = adjustment
			safe_now = min(amount, safe_now + reduction)
			changes = f"stop:{event_id}" if reduction >= amount else f"reduce_to:{event_id}:{money(event_amount(next(event for event in events if event['event_id'] == event_id)) - reduction)}"
	if safe_now >= amount:
		return {"request_id": request["request_id"], "amount_safe_to_pay": money(amount), "affordability_status": "affordable_now", "recommended_payment_method": "full_payment", "payment_plan": f"{request_date}:{money(amount)}", "earliest_date_for_full_payment": request_date.isoformat(), "spending_changes_needed": changes, "decision_explanation": f"Pay {profile['home_currency']} {money(amount)} on {request_date}. The projected balance stays above the {profile['home_currency']} {money(minimum)} minimum."}
	plan = installment_plan(request, profile, available)
	if plan and projected_balance(request["user_id"], request_date, horizon, plan[0]) >= minimum:
		plan_text = "|".join(f"{payment_date}:{money(payment_amount)}" for payment_date, payment_amount in plan[0])
		return {"request_id": request["request_id"], "amount_safe_to_pay": money(safe_now), "affordability_status": "affordable_with_plan", "recommended_payment_method": "installments", "payment_plan": plan_text, "earliest_date_for_full_payment": plan[0][-1][0].isoformat(), "spending_changes_needed": changes, "decision_explanation": f"Use {len(plan[0])} supplied installments. This keeps the {profile['home_currency']} {money(minimum)} minimum protected through the plan."}
	if request["allows_partial_payment"].lower() == "true" and 0 < safe_now < amount:
		completion = min(deadline, horizon)
		return {"request_id": request["request_id"], "amount_safe_to_pay": money(safe_now), "affordability_status": "affordable_with_plan", "recommended_payment_method": "partial_payment", "payment_plan": f"{request_date}:{money(safe_now)}|{completion}:{money(amount - safe_now)}", "earliest_date_for_full_payment": completion.isoformat(), "spending_changes_needed": changes, "decision_explanation": f"Pay {profile['home_currency']} {money(safe_now)} now and the remaining amount by {completion}."}
	if forecast_floor >= amount + minimum:
		return {"request_id": request["request_id"], "amount_safe_to_pay": money(safe_now), "affordability_status": "affordable_later", "recommended_payment_method": "wait", "payment_plan": f"{deadline}:{money(amount)}", "earliest_date_for_full_payment": deadline.isoformat(), "spending_changes_needed": changes, "decision_explanation": f"Wait until {deadline}; paying earlier would risk the {profile['home_currency']} {money(minimum)} minimum."}
	return {"request_id": request["request_id"], "amount_safe_to_pay": money(safe_now), "affordability_status": "not_affordable", "recommended_payment_method": "not_recommended", "payment_plan": "none", "earliest_date_for_full_payment": "", "spending_changes_needed": changes, "decision_explanation": f"Do not make this payment within the forecast. No available plan keeps the {profile['home_currency']} {money(minimum)} minimum protected."}


def generate_output() -> Path:
	rows = [prediction_for(request) for request in requests]
	for output_path in (ROOT / "output.csv", DATASET / "output.csv"):
		with output_path.open("w", encoding="utf-8", newline="") as handle:
			writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
			writer.writeheader()
			writer.writerows(rows)
	return ROOT / "output.csv"


@app.get("/api/health")
def health() -> dict[str, str]:
	return {"status": "ok", "service": "PocketWise AI"}


@app.post("/api/auth/signup")
def signup(payload: AuthRequest) -> dict[str, str]:
	with database() as connection:
		try:
			cursor = connection.execute("INSERT INTO users(name, email, password) VALUES (?, ?, ?)", (payload.name, payload.email, password_hash(payload.password)))
		except sqlite3.IntegrityError as error:
			raise HTTPException(status_code=409, detail="An account with this email already exists") from error
		connection.commit()
	return {"user_id": f"local_{cursor.lastrowid}", "name": payload.name, "email": payload.email, "message": "Account created"}


@app.post("/api/auth/login")
def login(payload: AuthRequest) -> dict[str, str]:
	with database() as connection:
		user = connection.execute("SELECT id, name FROM users WHERE email = ? AND password = ?", (payload.email, password_hash(payload.password))).fetchone()
	if not user:
		raise HTTPException(status_code=401, detail="Invalid email or password")
	return {"user_id": f"local_{user[0]}", "name": user[1], "email": payload.email, "message": "Signed in"}


@app.get("/api/account/{user_id}")
def get_account(user_id: str) -> dict[str, Any]:
	return account_snapshot(user_id)


@app.post("/api/decision")
def get_decision(payload: DecisionRequest) -> dict[str, Any]:
	return decide(payload)


@app.post("/api/chatbot")
def chatbot(payload: ChatRequest) -> dict[str, str]:
	account = account_snapshot(payload.user_id)
	query = payload.query.lower()
	if any(word in query for word in ("buy", "afford", "safe", "spend")):
		response = f"You have {account['currency']} {money(account['balance'])} available, with {account['currency']} {money(account['minimum_balance'])} reserved. Share an item and price and I’ll run a protected-balance check."
	elif "minimum" in query or "reserve" in query:
		response = f"Your budget guardian is holding {account['currency']} {money(account['minimum_balance'])} as a protected floor. ⚠️ Pending income is never counted early."
	else:
		response = "💡 A good rule: protect essentials first, then choose the earliest plan that keeps your minimum balance intact."
	with database() as connection:
		connection.execute("INSERT INTO chat_logs(user_id, query, response) VALUES (?, ?, ?)", (payload.user_id, payload.query, response))
		connection.commit()
	return {"response": response}


@app.get("/api/chatbot/{user_id}")
def chat_history(user_id: str) -> list[dict[str, str]]:
	with database() as connection:
		rows = connection.execute("SELECT query, response, created_at FROM chat_logs WHERE user_id = ? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
	return [{"query": row[0], "response": row[1], "created_at": row[2]} for row in rows]


if __name__ == "__main__":
	generate_output()
	print(f"Generated {len(requests)} predictions at {ROOT / 'output.csv'}")
