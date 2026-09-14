from datetime import date, datetime, timedelta
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

        # Preload authentic Indian consumer personas
        self._init_indian_personas()

        # Active user defaults to Indian persona
        self.active_user_id = "aarav_in"

        # Chat history: list of {"role": "user"|"assistant", "timestamp": str, "content": str, "meta": dict}
        self.chat_history: list[dict[str, Any]] = [
            {
                "role": "assistant",
                "timestamp": datetime.now().strftime("%H:%M"),
                "content": (
                    "🙏 **Namaste! Welcome to your Personal Financial AI Co-Pilot (India)** 🇮🇳\n\n"
                    "I help you make smart purchasing decisions in the era of UPI, credit cards, and No-Cost EMIs. "
                    "Before making any purchase or commitment, ask me:\n"
                    "- *'Can I buy iPhone 16 for ₹79,900 on 6-month EMI?'*\n"
                    "- *'How much safe UPI spending budget do I have this weekend?'*\n"
                    "- *'What EMIs and credit card bills are due this month?'*\n\n"
                    "I will simulate your 90-day bank cash flow day-by-day and ensure your emergency reserve stays protected!"
                ),
                "meta": {}
            }
        ]

    def _init_indian_personas(self):
        today = date.today()
        cur_year = today.year
        cur_month = today.month

        def get_date(day_num: int, month_offset: int = 0) -> date:
            m = cur_month + month_offset
            y = cur_year
            while m > 12:
                m -= 12
                y += 1
            while m < 1:
                m += 12
                y -= 1
            # Clamp day
            max_d = 28 if m == 2 else (30 if m in (4, 6, 9, 11) else 31)
            return date(y, m, min(day_num, max_d))

        # 1. Aarav Sharma — Tech Lead in Bangalore
        p1 = UserFinancialProfile(
            user_id="aarav_in",
            home_currency="INR",
            current_available_balance=85000.0,
            minimum_balance_to_keep=45000.0,  # Emergency Cushion floor
            financial_priorities=["rent", "debt_repayment", "investments"],
            expense_categories_to_protect=["rent", "debt", "utilities", "groceries"],
            expense_categories_user_is_willing_to_reduce=["dining", "entertainment"],
            expense_categories_user_is_willing_to_stop=["subscriptions", "shopping"],
            payment_methods_user_will_consider=["full_payment", "installments", "partial_payment"],
            max_installment_months=12,
        )
        self.custom_profiles["aarav_in"] = p1

        evs1 = [
            # Incoming salary on 1st
            FinancialEvent(
                event_id="aarav_sal_1", user_id="aarav_in", event_type="income", category="salary",
                direction="credit", amount=140000.0, currency="INR", status="settled", flexibility="fixed",
                event_date=get_date(1, 0), settlement_date=get_date(1, 0), description="Monthly Tech Salary Credit"
            ),
            FinancialEvent(
                event_id="aarav_sal_2", user_id="aarav_in", event_type="income", category="salary",
                direction="credit", amount=140000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(1, 1), settlement_date=get_date(1, 1), description="Monthly Tech Salary Credit"
            ),
            FinancialEvent(
                event_id="aarav_sal_3", user_id="aarav_in", event_type="income", category="salary",
                direction="credit", amount=140000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(1, 2), settlement_date=get_date(1, 2), description="Monthly Tech Salary Credit"
            ),
            # Rent in HSR Layout
            FinancialEvent(
                event_id="aarav_rent_1", user_id="aarav_in", event_type="expense", category="rent",
                direction="debit", amount=35000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(5, 0), settlement_date=get_date(5, 0), description="HSR Layout 2BHK Rent"
            ),
            FinancialEvent(
                event_id="aarav_rent_2", user_id="aarav_in", event_type="expense", category="rent",
                direction="debit", amount=35000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(5, 1), settlement_date=get_date(5, 1), description="HSR Layout 2BHK Rent"
            ),
            # Mutual Fund SIP
            FinancialEvent(
                event_id="aarav_sip_1", user_id="aarav_in", event_type="expense", category="investments",
                direction="debit", amount=15000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(7, 0), settlement_date=get_date(7, 0), description="Nifty 50 Mutual Fund SIP"
            ),
            # Car Loan EMI
            FinancialEvent(
                event_id="aarav_car_emi_1", user_id="aarav_in", event_type="expense", category="debt",
                direction="debit", amount=14500.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(10, 0), settlement_date=get_date(10, 0), description="Hyundai Creta Car Loan EMI"
            ),
            # HDFC Credit Card Bill
            FinancialEvent(
                event_id="aarav_cc_1", user_id="aarav_in", event_type="expense", category="debt",
                direction="debit", amount=22000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(12, 0), settlement_date=get_date(12, 0), description="HDFC Regalia Credit Card Due"
            ),
            # BESCOM Electricity & WiFi
            FinancialEvent(
                event_id="aarav_util_1", user_id="aarav_in", event_type="expense", category="utilities",
                direction="debit", amount=3500.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(15, 0), settlement_date=get_date(15, 0), description="BESCOM Power & ACT Broadband"
            ),
            # OTT Subscriptions
            FinancialEvent(
                event_id="aarav_ott_1", user_id="aarav_in", event_type="subscription", category="subscriptions",
                direction="debit", amount=1199.0, currency="INR", status="scheduled", flexibility="reducible_or_stoppable",
                event_date=get_date(18, 0), settlement_date=get_date(18, 0), description="Netflix Premium + Hotstar Pack"
            ),
            # Swiggy & Zomato
            FinancialEvent(
                event_id="aarav_dining_1", user_id="aarav_in", event_type="expense", category="dining",
                direction="debit", amount=6000.0, currency="INR", status="scheduled", flexibility="reducible_or_stoppable",
                minimum_allowed_amount=2000.0, event_date=get_date(22, 0), settlement_date=get_date(22, 0),
                description="Swiggy & Weekend Food Deliveries"
            ),
            # Weekend Social Outing
            FinancialEvent(
                event_id="aarav_out_1", user_id="aarav_in", event_type="expense", category="entertainment",
                direction="debit", amount=4500.0, currency="INR", status="scheduled", flexibility="reducible_or_stoppable",
                event_date=get_date(25, 0), settlement_date=get_date(25, 0), description="Weekend Pubs & Social Outings"
            ),
        ]
        self.custom_events["aarav_in"] = evs1

        # 2. Priya Patel — Marketing Specialist in Mumbai
        p2 = UserFinancialProfile(
            user_id="priya_in",
            home_currency="INR",
            current_available_balance=48000.0,
            minimum_balance_to_keep=25000.0,
            financial_priorities=["rent", "debt_repayment"],
            expense_categories_to_protect=["rent", "transport", "groceries"],
            expense_categories_user_is_willing_to_reduce=["dining"],
            expense_categories_user_is_willing_to_stop=["shopping", "subscriptions"],
            payment_methods_user_will_consider=["full_payment", "installments"],
            max_installment_months=6,
        )
        self.custom_profiles["priya_in"] = p2

        evs2 = [
            FinancialEvent(
                event_id="priya_sal_1", user_id="priya_in", event_type="income", category="salary",
                direction="credit", amount=80000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(1, 0), settlement_date=get_date(1, 0), description="Monthly Salary Credit"
            ),
            FinancialEvent(
                event_id="priya_rent_1", user_id="priya_in", event_type="expense", category="rent",
                direction="debit", amount=24000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(4, 0), settlement_date=get_date(4, 0), description="Andheri West Apartment Rent"
            ),
            FinancialEvent(
                event_id="priya_cc_1", user_id="priya_in", event_type="expense", category="debt",
                direction="debit", amount=12000.0, currency="INR", status="scheduled", flexibility="fixed",
                event_date=get_date(9, 0), settlement_date=get_date(9, 0), description="ICICI Amazon Pay Card Bill"
            ),
            FinancialEvent(
                event_id="priya_gym_1", user_id="priya_in", event_type="subscription", category="subscriptions",
                direction="debit", amount=2500.0, currency="INR", status="scheduled", flexibility="reducible_or_stoppable",
                event_date=get_date(14, 0), settlement_date=get_date(14, 0), description="Cult.fit Fitness Pass"
            ),
            FinancialEvent(
                event_id="priya_shop_1", user_id="priya_in", event_type="expense", category="shopping",
                direction="debit", amount=5500.0, currency="INR", status="scheduled", flexibility="reducible_or_stoppable",
                event_date=get_date(20, 0), settlement_date=get_date(20, 0), description="Myntra / Zara Clothing Shopping"
            ),
        ]
        self.custom_events["priya_in"] = evs2

    def list_users(self) -> list[dict[str, Any]]:
        users = []
        # Predefined Indian Personas first
        persona_names = {
            "aarav_in": "Aarav Sharma (Bangalore Techie 🇮🇳)",
            "priya_in": "Priya Patel (Mumbai Marketer 🇮🇳)",
        }
        for u_id, prof in sorted(self.custom_profiles.items()):
            events = self.custom_events.get(u_id, [])
            users.append({
                "user_id": u_id,
                "display_name": persona_names.get(u_id, u_id),
                "home_currency": "INR",
                "balance": prof.current_available_balance,
                "min_balance": prof.minimum_balance_to_keep,
                "event_count": len(events),
                "is_custom": True,
            })

        # All repository profiles converted to INR
        for u_id, prof in sorted(self.repo.profiles.items()):
            events = self.repo.events_by_user.get(u_id, [])
            users.append({
                "user_id": u_id,
                "display_name": f"{u_id} (₹ INR)",
                "home_currency": "INR",
                "balance": prof.current_available_balance,
                "min_balance": prof.minimum_balance_to_keep,
                "event_count": len(events),
                "is_custom": False,
            })

        return users

    def get_profile(self, user_id: str | None = None) -> UserFinancialProfile | None:
        target_id = user_id or self.active_user_id
        if target_id in self.custom_profiles:
            prof = self.custom_profiles[target_id]
            prof.home_currency = "INR"
            return prof
        if target_id in self.repo.profiles:
            prof = copy.deepcopy(self.repo.profiles[target_id])
            prof.home_currency = "INR"
            return prof
        return None

    def get_events(self, user_id: str | None = None) -> list[FinancialEvent]:
        target_id = user_id or self.active_user_id
        events = []
        if target_id in self.custom_events:
            events = self.custom_events[target_id]
        elif target_id in self.repo.events_by_user:
            events = copy.deepcopy(self.repo.events_by_user[target_id])
        for e in events:
            e.currency = "INR"
        return events

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
            home_currency="INR",  # Strictly INR for India
            current_available_balance=float(profile_data.get("current_available_balance", existing.current_available_balance if existing else 50000.0)),
            minimum_balance_to_keep=float(profile_data.get("minimum_balance_to_keep", existing.minimum_balance_to_keep if existing else 20000.0)),
            financial_priorities=profile_data.get("financial_priorities", existing.financial_priorities if existing else ["rent", "debt_repayment"]),
            expense_categories_to_protect=profile_data.get("expense_categories_to_protect", existing.expense_categories_to_protect if existing else ["rent", "debt", "groceries"]),
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
        ev_id = f"ev_custom_in_{len(self.get_events(user_id)) + 1}_{int(datetime.now().timestamp())}"

        from code.src.data.loaders import parse_date
        settlement_date = parse_date(event_data.get("settlement_date", date.today().isoformat()))

        is_inc = event_data.get("event_type") == "income"
        event = FinancialEvent(
            event_id=ev_id,
            user_id=user_id,
            event_type=event_data.get("event_type", "expense"),
            category=event_data.get("category", "miscellaneous"),
            direction="credit" if is_inc else "debit",
            amount=float(event_data.get("amount", 0.0)),
            currency="INR",  # Strictly INR for India
            status=event_data.get("status", "scheduled"),
            event_date=settlement_date,
            settlement_date=settlement_date,
            flexibility="fixed",
            description=event_data.get("description", "Custom Indian Bill / Income")
        )

        if user_id not in self.custom_events:
            existing = self.repo.events_by_user.get(user_id, [])
            self.custom_events[user_id] = list(existing)

        self.custom_events[user_id].append(event)
        return event
