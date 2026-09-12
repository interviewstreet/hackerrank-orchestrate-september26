from datetime import date, datetime
from pathlib import Path
from typing import Any
import copy

from code.src.data.repository import DataRepository
from code.src.models import (
    UserFinancialProfile,
    FinancialEvent,
    PaymentOption,
    RequestContext,
)

class AppState:
    def __init__(self, dataset_dir: Path):
        self.repo = DataRepository(dataset_dir)
        # Custom in-memory profiles & events
        self.custom_profiles: dict[str, UserFinancialProfile] = {}
        self.custom_events: dict[str, list[FinancialEvent]] = {}
        
        # Current active user
        self.active_user_id = "user_01" if "user_01" in self.repo.profiles else (
            list(self.repo.profiles.keys())[0] if self.repo.profiles else "default_user"
        )
        
        # Chat history: list of {"role": "user"|"assistant", "timestamp": str, "content": str, "meta": dict}
        self.chat_history: list[dict[str, Any]] = [
            {
                "role": "assistant",
                "timestamp": datetime.now().strftime("%H:%M"),
                "content": "👋 Welcome to your **Personal Financial Decision Assistant**! I'm here to protect your financial health in today's credit economy. Before you make any purchase or commitment, ask me: *'Can I afford this?'* or describe what you want to buy. I'll test your 90-day cash flow and give you a safe verdict.",
                "meta": {}
            }
        ]

    def list_users(self) -> list[dict[str, Any]]:
        users = []
        # Predefined users from dataset
        for u_id, prof in sorted(self.repo.profiles.items()):
            events = self.repo.events_by_user.get(u_id, [])
            users.append({
                "user_id": u_id,
                "home_currency": prof.home_currency,
                "balance": prof.current_available_balance,
                "min_balance": prof.minimum_balance_to_keep,
                "event_count": len(events),
                "is_custom": False,
            })
        # Custom users
        for u_id, prof in sorted(self.custom_profiles.items()):
            events = self.custom_events.get(u_id, [])
            users.append({
                "user_id": u_id,
                "home_currency": prof.home_currency,
                "balance": prof.current_available_balance,
                "min_balance": prof.minimum_balance_to_keep,
                "event_count": len(events),
                "is_custom": True,
            })
        return users

    def get_profile(self, user_id: str | None = None) -> UserFinancialProfile | None:
        target_id = user_id or self.active_user_id
        if target_id in self.custom_profiles:
            return self.custom_profiles[target_id]
        if target_id in self.repo.profiles:
            return self.repo.profiles[target_id]
        return None

    def get_events(self, user_id: str | None = None) -> list[FinancialEvent]:
        target_id = user_id or self.active_user_id
        if target_id in self.custom_events:
            return self.custom_events[target_id]
        if target_id in self.repo.events_by_user:
            return self.repo.events_by_user[target_id]
        return []

    def set_active_user(self, user_id: str):
        if user_id in self.repo.profiles or user_id in self.custom_profiles:
            self.active_user_id = user_id
            return True
        return False

    def update_profile(self, profile_data: dict[str, Any]) -> UserFinancialProfile:
        user_id = profile_data.get("user_id", self.active_user_id)
        existing = self.get_profile(user_id)
        
        updated = UserFinancialProfile(
            user_id=user_id,
            home_currency=profile_data.get("home_currency", existing.home_currency if existing else "USD"),
            current_available_balance=float(profile_data.get("current_available_balance", existing.current_available_balance if existing else 1000.0)),
            minimum_balance_to_keep=float(profile_data.get("minimum_balance_to_keep", existing.minimum_balance_to_keep if existing else 200.0)),
            financial_priorities=profile_data.get("financial_priorities", existing.financial_priorities if existing else ["rent", "groceries"]),
            expense_categories_to_protect=profile_data.get("expense_categories_to_protect", existing.expense_categories_to_protect if existing else ["housing", "utilities", "healthcare"]),
            expense_categories_user_is_willing_to_reduce=profile_data.get("expense_categories_user_is_willing_to_reduce", existing.expense_categories_user_is_willing_to_reduce if existing else ["dining", "entertainment"]),
            expense_categories_user_is_willing_to_stop=profile_data.get("expense_categories_user_is_willing_to_stop", existing.expense_categories_user_is_willing_to_stop if existing else ["subscriptions", "shopping"]),
            payment_methods_user_will_consider=profile_data.get("payment_methods_user_will_consider", existing.payment_methods_user_will_consider if existing else ["full_payment", "installments", "partial_payment"]),
            max_installment_months=int(profile_data["max_installment_months"]) if profile_data.get("max_installment_months") not in (None, "", "null") else None
        )
        self.custom_profiles[user_id] = updated
        self.active_user_id = user_id
        return updated

    def add_custom_event(self, event_data: dict[str, Any]) -> FinancialEvent:
        user_id = event_data.get("user_id", self.active_user_id)
        ev_id = f"ev_custom_{len(self.get_events(user_id)) + 1}_{int(datetime.now().timestamp())}"
        
        from code.src.data.loaders import parse_date
        settlement_date = parse_date(event_data.get("settlement_date", date.today().isoformat()))
        
        event = FinancialEvent(
            event_id=ev_id,
            user_id=user_id,
            event_type=event_data.get("event_type", "expense"),
            category=event_data.get("category", "miscellaneous"),
            amount=float(event_data.get("amount", 0.0)),
            currency=event_data.get("currency", "USD"),
            status=event_data.get("status", "scheduled"),
            is_recurring=bool(event_data.get("is_recurring", False)),
            frequency=event_data.get("frequency") or None,
            settlement_date=settlement_date,
            description=event_data.get("description", "Custom event")
        )
        
        if user_id not in self.custom_events:
            # Clone from existing repo if needed
            existing = self.repo.events_by_user.get(user_id, [])
            self.custom_events[user_id] = list(existing)
            
        self.custom_events[user_id].append(event)
        return event
