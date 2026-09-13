"""Fail-closed submission schema validation and deterministic CSV writing."""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .load import LoadedDataset
    from .simulator import BaselineSimulator

COLUMNS=("request_id","amount_safe_to_pay","affordability_status","recommended_payment_method","payment_plan","earliest_date_for_full_payment","spending_changes_needed","decision_explanation")

def _parse_plan(value: str) -> tuple[tuple[date, Decimal], ...]:
    if value == "none":
        return ()
    payments: list[tuple[date, Decimal]] = []
    for item in value.split("|"):
        try:
            raw_date, raw_amount = item.split(":", 1)
            payment_date, amount = date.fromisoformat(raw_date), Decimal(raw_amount)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("invalid payment plan") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError("payment plan amounts must be positive finite Decimals")
        payments.append((payment_date, amount))
    if tuple(sorted(payments)) != tuple(payments):
        raise ValueError("payment plan must be chronological")
    return tuple(payments)


def validate_rows(
    rows: list[dict[str, str]], request_ids: tuple[str, ...], *,
    dataset: "LoadedDataset | None" = None, simulator: "BaselineSimulator | None" = None,
) -> None:
    if len(rows)!=len(request_ids) or {r["request_id"] for r in rows} != set(request_ids) or len({r["request_id"] for r in rows}) != len(rows): raise ValueError("output rows must exactly match requests")
    for row in rows:
        if tuple(row) != COLUMNS: raise ValueError("output columns are invalid")
        try:
            safe_amount = Decimal(row["amount_safe_to_pay"])
            if not safe_amount.is_finite() or safe_amount < 0: raise ValueError
        except (InvalidOperation, ValueError): raise ValueError("invalid safe amount")
        if row["affordability_status"] not in {"affordable_now","affordable_with_plan","affordable_later","not_affordable"}: raise ValueError("invalid status")
        if row["recommended_payment_method"] not in {"full_payment","partial_payment","installments","wait","not_recommended"}: raise ValueError("invalid method")
        if row["earliest_date_for_full_payment"]: date.fromisoformat(row["earliest_date_for_full_payment"])
        if row["payment_plan"] == "none" and row["recommended_payment_method"] != "not_recommended": raise ValueError("accepted plan is missing")
        if not row["decision_explanation"].strip():
            raise ValueError("decision explanation is required")
        _parse_plan(row["payment_plan"])
    if dataset is not None or simulator is not None:
        if dataset is None or simulator is None:
            raise ValueError("semantic validation requires dataset and simulator together")
        _validate_semantics(rows, dataset, simulator)


def _validate_semantics(rows: list[dict[str, str]], dataset: "LoadedDataset", simulator: "BaselineSimulator") -> None:
    """Independently enforce output-level plan and safety invariants.

    This deliberately parses the serialized CSV representation rather than
    trusting planner objects, so a malformed or unsafe selected plan cannot
    reach the submission file through a future planner change.
    """
    requests = {request.request_id: request for request in dataset.requests}
    options = {}
    for option in dataset.payment_options:
        options.setdefault(option.request_id, []).append(option)
    for row in rows:
        request = requests[row["request_id"]]
        safe = Decimal(row["amount_safe_to_pay"])
        if safe > request.requested_amount:
            raise ValueError("safe amount exceeds requested amount")
        payments = _parse_plan(row["payment_plan"])
        method, status = row["recommended_payment_method"], row["affordability_status"]
        earliest = date.fromisoformat(row["earliest_date_for_full_payment"]) if row["earliest_date_for_full_payment"] else None
        if row["spending_changes_needed"] != "none":
            # No spending-change engine currently emits changes; fail closed
            # until each action can be reconstructed and simulated here.
            raise ValueError("unverified spending changes are not permitted")
        if method == "not_recommended":
            if status != "not_affordable" or payments:
                raise ValueError("not-recommended rows must be unaffordable with no payments")
            continue
        if not payments or payments[-1][0] > request.desired_completion_date:
            raise ValueError("accepted plan must complete by desired date")
        if method == "full_payment":
            if status != "affordable_now" or payments != ((request.request_date, request.requested_amount),):
                raise ValueError("full payment must be the exact request paid today")
            if earliest != request.request_date:
                raise ValueError("affordable-now earliest date must be request date")
        elif method == "wait":
            if status != "affordable_later" or len(payments) != 1 or payments[0][1] != request.requested_amount:
                raise ValueError("wait must represent one later full payment")
        elif method == "partial_payment":
            if (status != "affordable_with_plan" or not request.allows_partial_payment or
                    len(payments) != 2 or payments[0] != (request.request_date, safe) or
                    not Decimal("0") < safe < request.requested_amount or earliest is None or
                    payments[1] != (earliest, request.requested_amount - safe)):
                raise ValueError("partial payment violates request or baseline semantics")
        elif method == "installments":
            if status != "affordable_with_plan":
                raise ValueError("installments require affordable_with_plan")
            supplied = []
            for option in options.get(request.request_id, []):
                if option.payment_method != "installments":
                    continue
                expected = tuple((option.first_payment_date + __import__("datetime").timedelta(days=option.payment_frequency_days * index), option.payment_amount) for index in range(option.number_of_payments))
                supplied.append(expected)
            if payments not in supplied:
                raise ValueError("installment plan does not exactly match a supplied option")
        else:
            raise ValueError("unsupported method")
        simulation = simulator.simulate(request)
        balances = dict(simulation.daily_balances)
        for payment_date, amount in payments:
            if payment_date not in balances:
                raise ValueError("payment falls outside the safety horizon")
            for candidate in balances:
                if candidate >= payment_date:
                    balances[candidate] -= amount
        if any(balance < simulation.minimum_balance_to_keep for balance in balances.values()):
            raise ValueError("selected plan violates minimum balance")

def write_output(path: Path, rows: list[dict[str,str]], request_ids: tuple[str,...], *, dataset: "LoadedDataset | None" = None, simulator: "BaselineSimulator | None" = None) -> None:
    validate_rows(rows, request_ids, dataset=dataset, simulator=simulator)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
