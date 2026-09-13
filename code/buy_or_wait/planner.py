"""Deterministic payment-plan generation, safety checks, and CSV row policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .load import LoadedDataset
from .models import Request
from .simulator import BaselineAffordabilityCalculator, BaselineSimulator


@dataclass(frozen=True)
class Plan:
    method: str
    payments: tuple[tuple[date, Decimal], ...]
    option_id: str | None = None

    @property
    def total(self) -> Decimal:
        return sum((amount for _, amount in self.payments), Decimal("0"))


class DeterministicPlanner:
    """Generate only supplied payment schedules and verify each by simulation."""

    def __init__(self, dataset: LoadedDataset, simulator: BaselineSimulator) -> None:
        self.dataset = dataset
        self.simulator = simulator
        self.profiles = {item.user_id: item for item in dataset.profiles}
        self.options = {}
        for option in dataset.payment_options:
            self.options.setdefault(option.request_id, []).append(option)

    def decide(self, request: Request) -> dict[str, str]:
        baseline = BaselineAffordabilityCalculator(self.simulator).calculate(request)
        profile = self.profiles[request.user_id]
        plans = self._plans(request, baseline.amount_safe_to_pay, baseline.earliest_date_for_full_payment)
        eligible = [plan for plan in plans if plan.method in profile.payment_methods_user_will_consider and self._safe(request, plan)]
        eligible.sort(key=lambda plan: (plan.payments[-1][0] > request.desired_completion_date, plan.total, plan.payments[0][0], len(plan.payments), plan.option_id or ""))
        if eligible:
            plan = eligible[0]
            now = plan.method == "full_payment" and plan.payments[0][0] == request.request_date
            later = plan.method == "full_payment" and not now
            status = "affordable_now" if now else "affordable_later" if later else "affordable_with_plan"
            output_method = "wait" if later else plan.method
            payment_plan = "|".join(f"{day.isoformat()}:{self._money(amount)}" for day, amount in plan.payments)
            explanation = self._explanation(request, baseline.amount_safe_to_pay, plan, status)
            return self._row(request, baseline.amount_safe_to_pay, status, output_method, payment_plan, baseline.earliest_date_for_full_payment, "none", explanation)
        return self._row(request, baseline.amount_safe_to_pay, "not_affordable", "not_recommended", "none", baseline.earliest_date_for_full_payment, "none", f"No eligible supplied payment schedule keeps the {profile.home_currency} {self._money(profile.minimum_balance_to_keep)} minimum protected over the forecast.")

    def _plans(self, request: Request, safe_today: Decimal, earliest: date | None) -> list[Plan]:
        plans: list[Plan] = []
        if safe_today == request.requested_amount:
            plans.append(Plan("full_payment", ((request.request_date, request.requested_amount),)))
        if earliest is not None:
            plans.append(Plan("full_payment", ((earliest, request.requested_amount),)))
            if request.allows_partial_payment and Decimal("0") < safe_today < request.requested_amount and earliest <= request.desired_completion_date:
                plans.append(Plan("partial_payment", ((request.request_date, safe_today), (earliest, request.requested_amount - safe_today))))
        for option in self.options.get(request.request_id, []):
            dates = tuple(option.first_payment_date if index == 0 else option.first_payment_date + __import__('datetime').timedelta(days=option.payment_frequency_days * index) for index in range(option.number_of_payments))
            plans.append(Plan(option.payment_method, tuple((day, option.payment_amount) for day in dates), option.payment_option_id))
        return [plan for plan in plans if plan.payments and plan.payments[-1][0] <= request.desired_completion_date and plan.total >= request.requested_amount]

    def _safe(self, request: Request, plan: Plan) -> bool:
        # Reuse normalized flows and the simulator's exact daily semantics.
        simulation = self.simulator.simulate(request)
        balances = dict(simulation.daily_balances)
        for day, amount in plan.payments:
            if day not in balances or amount <= 0:
                return False
            for candidate in balances:
                if candidate >= day:
                    balances[candidate] -= amount
        return all(balance >= simulation.minimum_balance_to_keep for balance in balances.values())

    @staticmethod
    def _money(value: Decimal) -> str:
        return format(value.normalize(), "f")

    def _row(self, request: Request, safe: Decimal, status: str, method: str, plan: str, earliest: date | None, changes: str, explanation: str) -> dict[str, str]:
        return {"request_id": request.request_id, "amount_safe_to_pay": self._money(safe), "affordability_status": status, "recommended_payment_method": method, "payment_plan": plan, "earliest_date_for_full_payment": earliest.isoformat() if earliest else "", "spending_changes_needed": changes, "decision_explanation": explanation}

    def _explanation(self, request: Request, safe: Decimal, plan: Plan, status: str) -> str:
        currency = self.profiles[request.user_id].home_currency
        if status == "affordable_now":
            return f"Pay {currency} {self._money(plan.payments[0][1])} today; the verified 90-day forecast keeps the minimum balance protected."
        return f"Use the verified {plan.method.replace('_', ' ')} schedule; it completes by {plan.payments[-1][0].isoformat()} while preserving the minimum balance."
