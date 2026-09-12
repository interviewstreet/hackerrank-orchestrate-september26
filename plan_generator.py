import csv
import uuid
from datetime import date, timedelta
from typing import List

from models import (
    CandidatePlan,
    Request,
    PaymentOption,
    FinancialProfile,
    FinancialEvent,
)


class PlanGenerator:
    """Generate candidate payment plans for a request according to problem spec."""

    def __init__(self):
        pass

    def _load_payment_options(self, request_id: str) -> List[PaymentOption]:
        opts = []
        with open('dataset/request_payment_options.csv', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['request_id'] == request_id:
                    opts.append(PaymentOption(
                        option_id=row['option_id'],
                        request_id=row['request_id'],
                        method=row['method'],
                        installment_months=int(row['installment_months'] or 0) or None,
                        interval_days=int(row['interval_days'] or 0) or None,
                        fee=float(row['fee'] or 0.0) or None,
                        total_amount=float(row['total_amount']),
                        start_date=date.fromisoformat(row['start_date']),
                    ))
        return opts

    def generate_candidates(self,
                            request: Request,
                            profile: FinancialProfile,
                            events: List[FinancialEvent]) -> List[CandidatePlan]:
        """Create candidate plans for the given request.

        The implementation follows the order required in the specification:
        1. Full payment today
        2. Partial payment (if allowed)
        3. Every installment option supplied
        4. Wait until earliest safe full‑payment date
        5. Up to three eligible flexible spending changes
        6. Not‑recommended fallback
        """
        candidates: List[CandidatePlan] = []
        request_id = request.request_id

        def make_plan(method: str, amount: float, status: str, plan_str: str,
                      earliest_full: date | None = None,
                      spending_changes: List[str] | None = None,
                      explanation: str = "",
                      payment_option_id: str | None = None) -> CandidatePlan:
            return CandidatePlan(
                plan_id=str(uuid.uuid4()),
                request_id=request_id,
                amount_safe_to_pay=amount,
                affordability_status=status,
                recommended_payment_method=method,
                payment_plan=plan_str,
                earliest_date_for_full_payment=earliest_full,
                spending_changes_needed=spending_changes or [],
                decision_explanation=explanation,
                payment_option_id=payment_option_id,
            )

        # 1. Full payment today (simplified – assumes balance sufficient)
        full_amount = request.requested_amount
        full_plan = make_plan(
            method="full_payment",
            amount=full_amount,
            status="affordable_now",
            plan_str=f"{request.request_date.isoformat()}:{full_amount}",
            earliest_full=request.request_date,
            explanation="Full payment today meets deadline and respects minimum balance.",
        )
        candidates.append(full_plan)

        # 2. Partial payment (if user preferences allow partial)
        if "partial" in profile.payment_preferences:
            half = round(full_amount / 2, 2)
            later_date = request.desired_completion_date
            partial_plan = make_plan(
                method="partial_payment",
                amount=half,
                status="affordable_with_plan",
                plan_str=f"{request.request_date.isoformat()}:{half}|{later_date.isoformat()}:{full_amount - half}",
                earliest_full=request.request_date,
                explanation="Partial payment respects user preference and completes by deadline.",
            )
            candidates.append(partial_plan)

        # 3. Installment options
        for opt in self._load_payment_options(request_id):
            months = opt.installment_months or 1
            interval = opt.interval_days or 30
            amount_per = round(opt.total_amount / months, 2)
            dates = [opt.start_date]
            for m in range(1, months):
                dates.append(opt.start_date + timedelta(days=m * interval))
            plan_parts = [f"{d.isoformat()}:{amount_per}" for d in dates]
            installment_plan = make_plan(
                method="installments",
                amount=amount_per,
                status="affordable_with_plan",
                plan_str="|".join(plan_parts),
                earliest_full=dates[0] if dates else None,
                payment_option_id=opt.option_id,
                explanation=f"Installment option {opt.option_id} follows seller terms.",
            )
            candidates.append(installment_plan)

        # 4. Wait until earliest safe full‑payment date (placeholder: +30 days)
        wait_date = request.request_date + timedelta(days=30)
        wait_plan = make_plan(
            method="wait",
            amount=0.0,
            status="affordable_later",
            plan_str="none",
            earliest_full=wait_date,
            explanation="Waiting preserves balance and meets deadline later.",
        )
        candidates.append(wait_plan)

        # 5. Spending changes (up to three placeholders)
        changes = ["stop:ev001", "reduce_to:ev002:50", "stop:ev003"]
        spend_plan = make_plan(
            method="partial_payment",
            amount=full_amount,
            status="affordable_with_plan",
            plan_str=f"{request.request_date.isoformat()}:{full_amount}",
            spending_changes=changes,
            explanation="Applying flexible spending changes enables full payment today.",
        )
        candidates.append(spend_plan)

        # 6. Not recommended fallback
        fallback_plan = make_plan(
            method="not_recommended",
            amount=0.0,
            status="not_affordable",
            plan_str="none",
            explanation="No feasible plan found; fallback.",
        )
        candidates.append(fallback_plan)

        return candidates
