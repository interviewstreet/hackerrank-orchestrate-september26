from datetime import date, timedelta
from typing import Any
import copy

from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    FinancialEvent,
    NormalizedFinancialEvent,
    PaymentOption,
    PaymentPlan,
    PaymentItem,
    SpendingChange,
)
from code.src.finance.currency import convert_currency
from code.src.finance.recurrence import generate_missing_recurrences
from code.src.finance.capacity import (
    calculate_baseline_amount_safe_to_pay,
    calculate_earliest_full_payment_date,
)
from code.src.finance.plans import generate_candidate_plans, evaluate_plan
from code.src.finance.optimizer import search_best_spending_changes
from code.src.finance.ranking import select_final_decision
from code.src.finance.simulator import simulate_plan
from copilot.backend.state import AppState


class CopilotEngine:
    def __init__(self, state: AppState):
        self.state = state

    def prepare_normalized_events(
        self,
        profile: UserFinancialProfile,
        raw_events: list[FinancialEvent],
        request_date: date,
        horizon_days: int = 90,
    ) -> list[NormalizedFinancialEvent]:
        # Separate historical vs explicit future events
        historical_events = [e for e in raw_events if e.settlement_date < request_date]
        explicit_future_events = [e for e in raw_events if e.settlement_date >= request_date]

        # Generate missing recurrences
        missing_recurrences = generate_missing_recurrences(
            historical_events=historical_events,
            request_date=request_date,
            horizon_days=horizon_days,
            explicit_future_events=explicit_future_events,
            user_home_currency=profile.home_currency,
        )

        combined_events: list[NormalizedFinancialEvent] = []

        # 1. Normalize explicit future events
        for e in explicit_future_events:
            final_amt = e.amount if e.amount is not None else 0.0
            converted_amt = convert_currency(
                amount=final_amt,
                from_currency=e.currency,
                to_currency=profile.home_currency,
                rate_date=e.settlement_date,
                repo=self.state.repo,
            )

            norm_ev = NormalizedFinancialEvent(
                event_id=e.event_id,
                user_id=e.user_id,
                event_type=e.event_type,
                description=e.description,
                category=e.category,
                direction=e.direction,
                amount=final_amt,
                currency=e.currency,
                converted_amount=converted_amt,
                event_date=e.event_date,
                settlement_date=e.settlement_date,
                status=e.status,
                linked_event_id=e.linked_event_id,
                flexibility=e.flexibility,
                minimum_allowed_amount=e.minimum_allowed_amount,
                is_recurring=(e.event_type == "subscription" or e.category in ("rent", "housing", "utilities", "salary")),
                evidence_source="explicit_event",
            )
            combined_events.append(norm_ev)

        # 2. Add generated recurrences
        for rec in missing_recurrences:
            rec.converted_amount = convert_currency(
                amount=rec.amount,
                from_currency=rec.currency,
                to_currency=profile.home_currency,
                rate_date=rec.settlement_date,
                repo=self.state.repo,
            )
            combined_events.append(rec)

        return combined_events

    def get_financial_summary(self, user_id: str | None = None) -> dict[str, Any]:
        target_id = user_id or self.state.active_user_id
        profile = self.state.get_profile(target_id)
        if not profile:
            return {"error": f"Profile not found for {target_id}"}

        raw_events = self.state.get_events(target_id)
        today = date.today()

        norm_events = self.prepare_normalized_events(
            profile=profile,
            raw_events=raw_events,
            request_date=today,
            horizon_days=90,
        )

        amount_safe = calculate_baseline_amount_safe_to_pay(
            starting_balance=profile.current_available_balance,
            base_events=norm_events,
            minimum_balance=profile.minimum_balance_to_keep,
            request_date=today,
            requested_amount=1000000.0,
            horizon_days=90,
        )

        # Top upcoming commitments next 30 days
        upcoming_30 = []
        for ev in sorted(norm_events, key=lambda x: x.settlement_date):
            if today <= ev.settlement_date <= today + timedelta(days=30):
                if ev.direction == "debit" and ev.status in ("pending", "scheduled", "settled"):
                    upcoming_30.append({
                        "event_id": ev.event_id,
                        "description": ev.description,
                        "category": ev.category,
                        "amount": ev.converted_amount,
                        "settlement_date": ev.settlement_date.isoformat(),
                        "flexibility": ev.flexibility,
                        "is_recurring": ev.is_recurring,
                    })

        total_upcoming_debits = sum(item["amount"] for item in upcoming_30)

        # Upcoming salary / credits next 30 days
        upcoming_credits = []
        for ev in sorted(norm_events, key=lambda x: x.settlement_date):
            if today <= ev.settlement_date <= today + timedelta(days=30):
                if ev.direction == "credit" and (ev.category == "salary" or ev.status == "settled"):
                    upcoming_credits.append({
                        "event_id": ev.event_id,
                        "description": ev.description,
                        "amount": ev.converted_amount,
                        "settlement_date": ev.settlement_date.isoformat(),
                    })

        return {
            "user_id": target_id,
            "home_currency": "INR",
            "current_balance": round(profile.current_available_balance, 2),
            "emergency_cushion": round(profile.minimum_balance_to_keep, 2),
            "safe_headroom_today": round(amount_safe, 2),
            "upcoming_30d_debits_total": round(total_upcoming_debits, 2),
            "upcoming_commitments": upcoming_30[:8],
            "upcoming_credits": upcoming_credits[:4],
            "protected_categories": profile.expense_categories_to_protect,
            "flexible_categories": profile.expense_categories_user_is_willing_to_reduce + profile.expense_categories_user_is_willing_to_stop,
            "max_installment_months": profile.max_installment_months,
        }

    def evaluate_purchase(
        self,
        user_id: str | None,
        item_name: str,
        amount: float,
        request_date: date | None = None,
        desired_completion_date: date | None = None,
        category: str = "shopping",
        custom_installment_months: int | None = None,
        willing_to_adjust_spending: bool = True,
    ) -> dict[str, Any]:
        target_id = user_id or self.state.active_user_id
        profile = self.state.get_profile(target_id)
        if not profile:
            return {"error": f"Profile not found for {target_id}"}

        req_d = request_date or date.today()
        comp_d = desired_completion_date or (req_d + timedelta(days=60))

        raw_events = self.state.get_events(target_id)
        norm_events = self.prepare_normalized_events(
            profile=profile,
            raw_events=raw_events,
            request_date=req_d,
            horizon_days=90,
        )

        amount_safe = calculate_baseline_amount_safe_to_pay(
            starting_balance=profile.current_available_balance,
            base_events=norm_events,
            minimum_balance=profile.minimum_balance_to_keep,
            request_date=req_d,
            requested_amount=amount,
            horizon_days=90,
        )

        earliest_full_date = calculate_earliest_full_payment_date(
            starting_balance=profile.current_available_balance,
            base_events=norm_events,
            minimum_balance=profile.minimum_balance_to_keep,
            request_date=req_d,
            requested_amount=amount,
            desired_completion_date=comp_d,
            horizon_days=90,
        )

        # Generate financing options (e.g. 3, 6, 12 month installments)
        payment_options: list[PaymentOption] = []
        max_months = custom_installment_months or profile.max_installment_months or 0

        # Always offer default full payment option
        payment_options.append(PaymentOption(
            payment_option_id="opt_full",
            request_id="copilot_req",
            payment_method="full_payment",
            payment_amount=amount,
            number_of_payments=1,
            first_payment_date=req_d,
            payment_frequency_days=None,
            financing_fee=0.0,
            total_payable_amount=amount,
        ))

        if max_months >= 3 and "installments" in profile.payment_methods_user_will_consider:
            inst_amt = round(amount / 3, 2)
            payment_options.append(PaymentOption(
                payment_option_id="opt_3mo",
                request_id="copilot_req",
                payment_method="installments",
                payment_amount=inst_amt,
                number_of_payments=3,
                first_payment_date=req_d,
                payment_frequency_days=30,
                financing_fee=0.0,
                total_payable_amount=amount,
            ))
            if max_months >= 6:
                inst6_amt = round(amount / 6, 2)
                payment_options.append(PaymentOption(
                    payment_option_id="opt_6mo",
                    request_id="copilot_req",
                    payment_method="installments",
                    payment_amount=inst6_amt,
                    number_of_payments=6,
                    first_payment_date=req_d,
                    payment_frequency_days=30,
                    financing_fee=0.0,
                    total_payable_amount=amount,
                ))
            if max_months >= 9:
                inst9_amt = round(amount / 9, 2)
                payment_options.append(PaymentOption(
                    payment_option_id="opt_9mo",
                    request_id="copilot_req",
                    payment_method="installments",
                    payment_amount=inst9_amt,
                    number_of_payments=9,
                    first_payment_date=req_d,
                    payment_frequency_days=30,
                    financing_fee=0.0,
                    total_payable_amount=amount,
                ))
            if max_months >= 12:
                inst12_amt = round(amount / 12, 2)
                payment_options.append(PaymentOption(
                    payment_option_id="opt_12mo",
                    request_id="copilot_req",
                    payment_method="installments",
                    payment_amount=inst12_amt,
                    number_of_payments=12,
                    first_payment_date=req_d,
                    payment_frequency_days=30,
                    financing_fee=0.0,
                    total_payable_amount=amount,
                ))

        # Request context
        req_context = RequestContext(
            request_id="copilot_eval",
            user_id=target_id,
            request_date=req_d,
            request_type=category,
            requested_amount=amount,
            desired_completion_date=comp_d,
            allows_partial_payment=("partial_payment" in profile.payment_methods_user_will_consider),
            request_text=f"Purchase {item_name} for {amount}",
        )

        # Baseline plan generation & evaluation
        candidate_plans = generate_candidate_plans(
            request=req_context,
            profile=profile,
            options=payment_options,
            baseline_safe_amount=amount_safe,
            earliest_full_payment_date=earliest_full_date,
        )

        plan_evaluations = [
            evaluate_plan(
                plan=p,
                request=req_context,
                profile=profile,
                base_events=norm_events,
                horizon_days=90,
            )
            for p in candidate_plans
        ]

        # Check spending changes if not affordable now
        best_changes: list[SpendingChange] = []
        opt_evals = []
        if willing_to_adjust_spending and amount_safe < amount:
            best_changes, opt_evals = search_best_spending_changes(
                request=req_context,
                profile=profile,
                base_events=norm_events,
                options=payment_options,
                max_changes=3,
            )

        # Select best decision
        decision = select_final_decision(
            request=req_context,
            profile=profile,
            baseline_safe_amount=amount_safe,
            earliest_full_payment_date=earliest_full_date,
            base_evaluations=plan_evaluations,
            optimized_evaluations=opt_evals,
            applied_changes=best_changes,
        )

        # Generate cash flow timelines for visualization (Chart.js)
        # 1. Baseline timeline (no purchase)
        baseline_res = simulate_plan(
            starting_balance=profile.current_available_balance,
            base_events=norm_events,
            payment_plan=None,
            minimum_balance=profile.minimum_balance_to_keep,
            start_date=req_d,
            horizon_days=90,
        )
        baseline_map = {item["date"]: item["ending_balance"] for item in baseline_res.get("timeline", [])}

        # 2. Direct full purchase today timeline
        full_plan = PaymentPlan(
            plan_id="full_eval",
            method="full_payment",
            payments=[PaymentItem(payment_date=req_d, amount=amount)],
            total_amount=amount,
            completion_date=req_d,
        )
        direct_res = simulate_plan(
            starting_balance=profile.current_available_balance,
            base_events=norm_events,
            payment_plan=full_plan,
            minimum_balance=profile.minimum_balance_to_keep,
            start_date=req_d,
            horizon_days=90,
        )
        direct_map = {item["date"]: item["ending_balance"] for item in direct_res.get("timeline", [])}

        # 3. Recommended decision timeline
        rec_payments = []
        if decision.payment_plan and decision.payment_plan != "none":
            for part in decision.payment_plan.split("|"):
                if ":" in part:
                    p_date_str, p_amt_str = part.split(":")
                    rec_payments.append(PaymentItem(payment_date=date.fromisoformat(p_date_str), amount=float(p_amt_str)))

        rec_plan = None
        if rec_payments:
            rec_plan = PaymentPlan(
                plan_id="rec_plan",
                method=decision.recommended_payment_method,
                payments=rec_payments,
                total_amount=sum(p.amount for p in rec_payments),
                completion_date=rec_payments[-1].payment_date,
            )

        events_for_rec = norm_events
        if decision.spending_changes_needed and decision.spending_changes_needed != "none" and best_changes:
            from code.src.finance.optimizer import apply_spending_changes_to_events
            events_for_rec = apply_spending_changes_to_events(norm_events, best_changes)

        rec_res = simulate_plan(
            starting_balance=profile.current_available_balance,
            base_events=events_for_rec,
            payment_plan=rec_plan,
            minimum_balance=profile.minimum_balance_to_keep,
            start_date=req_d,
            horizon_days=90,
        )
        rec_map = {item["date"]: item["ending_balance"] for item in rec_res.get("timeline", [])}

        # Combine dates
        all_dates = sorted(list(set(baseline_map.keys()) | set(direct_map.keys()) | set(rec_map.keys())))
        daily_chart_data = []
        for d_str in all_dates:
            daily_chart_data.append({
                "date": d_str,
                "baseline": round(baseline_map.get(d_str, profile.current_available_balance), 2),
                "after_full_purchase": round(direct_map.get(d_str, profile.current_available_balance - amount), 2),
                "with_copilot_recommendation": round(rec_map.get(d_str, profile.current_available_balance), 2),
                "emergency_floor": round(profile.minimum_balance_to_keep, 2),
            })

        # Format human explanation
        explanation = self._format_human_explanation(
            item_name=item_name,
            amount=amount,
            currency=profile.home_currency,
            status=decision.affordability_status,
            method=decision.recommended_payment_method,
            amount_safe=amount_safe,
            earliest_date_str=decision.earliest_date_for_full_payment,
            plan_str=decision.payment_plan,
            changes=best_changes if decision.spending_changes_needed != "none" else [],
            min_balance=profile.minimum_balance_to_keep,
        )

        # Spending changes human format
        formatted_changes = []
        if decision.spending_changes_needed != "none" and best_changes:
            for ch in best_changes:
                matching_ev = next((e for e in norm_events if e.event_id == ch.event_id or e.linked_event_id == ch.event_id), None)
                desc = matching_ev.description if matching_ev else ch.event_id
                if ch.action == "stop":
                    formatted_changes.append(f"Pause / cancel {desc}")
                else:
                    new_amt = ch.new_amount if ch.new_amount is not None else 0.0
                    formatted_changes.append(f"Reduce {desc} to ₹{new_amt:,.2f}")

        return {
            "item_name": item_name,
            "requested_amount": amount,
            "currency": "INR",
            "affordability_status": decision.affordability_status,
            "recommended_payment_method": decision.recommended_payment_method,
            "amount_safe_to_pay_today": round(amount_safe, 2),
            "earliest_date_for_full_payment": decision.earliest_date_for_full_payment if decision.earliest_date_for_full_payment else None,
            "payment_plan_summary": decision.payment_plan,
            "spending_changes_needed": decision.spending_changes_needed.split("|") if decision.spending_changes_needed != "none" else [],
            "human_spending_changes": formatted_changes,
            "explanation": explanation,
            "chart_timeline": daily_chart_data,
        }

    def _format_human_explanation(
        self,
        item_name: str,
        amount: float,
        currency: str,
        status: str,
        method: str,
        amount_safe: float,
        earliest_date_str: str,
        plan_str: str,
        changes: list[SpendingChange],
        min_balance: float,
    ) -> str:
        cur_sym = "₹" if currency == "INR" else f"{currency} "
        if status == "affordable_now":
            return (
                f"✅ **Safe to Buy in Full Today (UPI / Debit / NetBanking)!**\n\n"
                f"Your bank cash flow easily supports paying **{cur_sym}{amount:,.2f}** for *{item_name}* immediately. "
                f"Even after this purchase, your projected balance remains comfortably above your **{cur_sym}{min_balance:,.2f}** emergency safety cushion throughout the next 90 days."
            )
        elif status == "affordable_with_plan":
            if method == "installments" and plan_str != "none":
                return (
                    f"💳 **Affordable with No-Cost EMI / Installments!**\n\n"
                    f"Paying {cur_sym}{amount:,.2f} in a single lump-sum today would deplete your emergency reserve. "
                    f"However, splitting it into structured EMI payments ({plan_str}) keeps your bank account safely above your **{cur_sym}{min_balance:,.2f}** emergency cushion."
                )
            elif changes:
                cuts_summary = ", ".join([f"{c.action} on {c.event_id}" for c in changes])
                return (
                    f"💡 **Affordable with Targeted Budget Adjustments!**\n\n"
                    f"You currently have only **{cur_sym}{amount_safe:,.2f}** in safe UPI headroom today. "
                    f"However, by temporarily adjusting flexible non-essential spending like Swiggy, dining, or shopping ({cuts_summary}), you can safely purchase *{item_name}* today without compromising your emergency fund."
                )
            else:
                return (
                    f"🗓️ **Affordable with Structured Schedule!**\n\n"
                    f"Recommended schedule: {plan_str}."
                )
        elif status == "affordable_later":
            wait_date = earliest_date_str if earliest_date_str else "your next salary credit"
            return (
                f"⏳ **Recommendation: WAIT until {wait_date}.**\n\n"
                f"You only have **{cur_sym}{amount_safe:,.2f}** in safe discretionary headroom today. "
                f"Buying *{item_name}* for {cur_sym}{amount:,.2f} now would cause your account to dip below your emergency reserve of **{cur_sym}{min_balance:,.2f}**. "
                f"Waiting until **{wait_date}** ensures your confirmed salary credit arrives before making this commitment."
            )
        else:
            return (
                f"⚠️ **Not Recommended (Unsafe Spending).**\n\n"
                f"Purchasing *{item_name}* ({cur_sym}{amount:,.2f}) exceeds your 90-day safe cash flow. "
                f"You have upcoming non-negotiable obligations (rent, loan EMIs, or credit card bills), and buying this would severely deplete your **{cur_sym}{min_balance:,.2f}** emergency cushion."
            )
