"""Reproducible comparison of baseline affordability against solved examples."""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from buy_or_wait.cashflows import CashFlowNormalizer
from buy_or_wait.load import DatasetLoader
from buy_or_wait.planner import DeterministicPlanner
from buy_or_wait.simulator import BaselineAffordabilityCalculator, BaselineSimulator


def main() -> int:
    dataset = DatasetLoader(ROOT / "dataset").load()
    truth = {row["request_id"]: row for row in csv.DictReader((ROOT / "dataset" / "sample_requests.csv").open(newline=""))}
    simulator = BaselineSimulator(CashFlowNormalizer(dataset))
    calculator = BaselineAffordabilityCalculator(simulator)
    planner = DeterministicPlanner(dataset, simulator)
    metrics = {key: 0 for key in ("amount", "date", "combined", "status", "method", "plan", "changes")}
    absolute_error = Decimal("0")
    print("request_id,official_amount,actual_amount,amount_delta,official_date,actual_date,date_match,combined_match")
    for request in dataset.sample_requests:
        expected, baseline, decision = truth[request.request_id], calculator.calculate(request), planner.decide(request)
        actual_date = baseline.earliest_date_for_full_payment.isoformat() if baseline.earliest_date_for_full_payment else ""
        amount_match = baseline.amount_safe_to_pay == Decimal(expected["amount_safe_to_pay"])
        date_match = actual_date == expected["earliest_date_for_full_payment"]
        metrics["amount"] += amount_match; metrics["date"] += date_match; metrics["combined"] += amount_match and date_match
        absolute_error += abs(baseline.amount_safe_to_pay - Decimal(expected["amount_safe_to_pay"]))
        for field, key in (("affordability_status", "status"), ("recommended_payment_method", "method"), ("payment_plan", "plan"), ("spending_changes_needed", "changes")):
            metrics[key] += decision[field] == expected[field]
        print(f"{request.request_id},{expected['amount_safe_to_pay']},{baseline.amount_safe_to_pay},{baseline.amount_safe_to_pay - Decimal(expected['amount_safe_to_pay'])},{expected['earliest_date_for_full_payment']},{actual_date},{date_match},{amount_match and date_match}")
    print("metrics," + ",".join(f"{key}={value}/25" for key, value in metrics.items()) + f",absolute_amount_error={absolute_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
