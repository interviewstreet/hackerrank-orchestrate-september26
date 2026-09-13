"""Deterministic daily baseline balance simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .cashflows import CashFlowNormalizer
from .models import BaselineAffordabilityResult, CashFlow, Request


@dataclass(frozen=True)
class BaselineSimulation:
    start_date: date
    end_date: date
    starting_balance: Decimal
    daily_balances: tuple[tuple[date, Decimal], ...]
    minimum_balance: Decimal
    minimum_balance_date: date
    normalized_cash_flows: tuple[CashFlow, ...]
    minimum_balance_to_keep: Decimal

    @property
    def violates_minimum_balance(self) -> bool:
        return self.minimum_balance < self.minimum_balance_to_keep


class BaselineSimulator:
    def __init__(self, normalizer: CashFlowNormalizer, *, horizon_days: int = 90) -> None:
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        self.normalizer = normalizer
        self.horizon_days = horizon_days

    def simulate(
        self,
        request: Request,
        *,
        proposed_payment: Decimal = Decimal("0"),
        payment_date: date | None = None,
    ) -> BaselineSimulation:
        """Simulate the established forecast with an optional one-off payment.

        A payment is posted after normalized cash flows on its calendar day.
        This is the conservative extension of the simulator's existing
        end-of-day minimum-balance semantics: it never lets a payment use a
        later day's cash flow, while same-day confirmed flows retain their
        deterministic provenance ordering.
        """
        if proposed_payment < Decimal("0"):
            raise ValueError("proposed_payment must not be negative")
        if proposed_payment and payment_date is None:
            raise ValueError("payment_date is required for a proposed payment")
        end_date = request.request_date + timedelta(days=self.horizon_days - 1)
        if payment_date is not None and not request.request_date <= payment_date <= end_date:
            raise ValueError("payment_date must fall within the simulation horizon")
        profile = self.normalizer.profiles[request.user_id]
        flows = self.normalizer.normalize(request, horizon_days=self.horizon_days)
        flows_by_day: dict[date, list[CashFlow]] = {}
        for flow in flows:
            flows_by_day.setdefault(flow.flow_date, []).append(flow)
        balance = profile.current_available_balance
        minimum = balance
        minimum_date = request.request_date
        balances: list[tuple[date, Decimal]] = []
        for offset in range(self.horizon_days):
            current_date = request.request_date + timedelta(days=offset)
            # Stable provenance ordering makes same-day results reproducible.
            for flow in sorted(flows_by_day.get(current_date, ()), key=lambda item: (item.sequence, item.source_event_id or "")):
                if flow.direction == "credit":
                    balance += flow.amount
                elif flow.direction == "debit":
                    balance -= flow.amount
            if current_date == payment_date:
                balance -= proposed_payment
            balances.append((current_date, balance))
            if balance < minimum:
                minimum, minimum_date = balance, current_date
        return BaselineSimulation(request.request_date, end_date, profile.current_available_balance, tuple(balances), minimum, minimum_date, flows, profile.minimum_balance_to_keep)


class BaselineAffordabilityCalculator:
    """Derive baseline capacity by reusing the normalized daily simulator."""

    def __init__(self, simulator: BaselineSimulator) -> None:
        self.simulator = simulator

    def calculate(self, request: Request) -> BaselineAffordabilityResult:
        baseline = self.simulator.simulate(request)
        # The simulator records the opening snapshot before any same-day flow,
        # but a proposed payment is posted after those flows.  Capacity today
        # is therefore constrained by the post-flow daily trajectory only.
        daily_balances = baseline.daily_balances
        headroom = min(balance for _, balance in daily_balances) - baseline.minimum_balance_to_keep
        safe_today = min(request.requested_amount, max(Decimal("0"), headroom))

        full_payment_date: date | None = None
        # A one-off debit only shifts the post-payment daily balances downward
        # by its amount.  A suffix minimum is therefore exactly equivalent to
        # re-simulating every candidate date, while retaining one authoritative
        # simulator for the cash-flow rules and avoiding stateful duplication.
        suffix_minimums: list[Decimal] = []
        running_minimum: Decimal | None = None
        for _, balance in reversed(daily_balances):
            running_minimum = balance if running_minimum is None else min(balance, running_minimum)
            suffix_minimums.append(running_minimum)
        suffix_minimums.reverse()
        required = baseline.minimum_balance_to_keep + request.requested_amount
        for (candidate, _), suffix_minimum in zip(daily_balances, suffix_minimums):
            if suffix_minimum >= required:
                full_payment_date = candidate
                break
        return BaselineAffordabilityResult(safe_today, full_payment_date)
