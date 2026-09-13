import re
from datetime import date, datetime
from typing import Any
from copilot.backend.engine import CopilotEngine


class FinancialCopilotAssistant:
    def __init__(self, engine: CopilotEngine):
        self.engine = engine

    def handle_message(self, user_text: str, user_id: str | None = None) -> dict[str, Any]:
        target_id = user_id or self.engine.state.active_user_id
        text = user_text.strip()
        lower = text.lower()

        # 1. Check for purchase evaluation intent: e.g. "Can I buy iPhone 16 for ₹79,900 on 6-month EMI?"
        purchase_intent = self._extract_purchase_intent(text)
        if purchase_intent:
            item_name = purchase_intent["item"]
            amount = purchase_intent["amount"]
            custom_installments = purchase_intent.get("months")
            
            eval_result = self.engine.evaluate_purchase(
                user_id=target_id,
                item_name=item_name,
                amount=amount,
                custom_installment_months=custom_installments,
            )

            response_md = self._format_purchase_response(eval_result)
            return {
                "role": "assistant",
                "content": response_md,
                "type": "purchase_evaluation",
                "evaluation": eval_result,
            }

        # 2. Check for balance / spending headroom intent
        headroom_keywords = [
            "headroom", "safe to spend", "safely spend", "how much can i spend",
            "how much can i safely spend", "discretionary", "budget today",
            "available to spend", "spend today", "afford today", "current balance",
            "upi budget", "safe upi", "weekend budget", "balance"
        ]
        if any(w in lower for w in headroom_keywords):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            bal = summary["current_balance"]
            cushion = summary["emergency_cushion"]
            safe = summary["safe_headroom_today"]
            upcoming = summary["upcoming_30d_debits_total"]

            content = (
                f"### 📊 Your Financial Headroom (India 🇮🇳)\n\n"
                f"- **Bank Account Balance:** {cur_sym}{bal:,.2f}\n"
                f"- **Emergency Cushion (Protected FD / Reserve Floor):** {cur_sym}{cushion:,.2f}\n"
                f"- **Upcoming Obligations & EMIs (Next 30 Days):** {cur_sym}{upcoming:,.2f}\n\n"
                f"💡 **Safe Discretionary Spending / UPI Headroom Today: {cur_sym}{safe:,.2f}**\n\n"
                f"You can safely spend up to **{cur_sym}{safe:,.2f}** via UPI or debit card right now without touching your emergency reserve or falling short on upcoming EMIs/rent."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "headroom_summary",
                "summary": summary,
            }

        # 3. Check for upcoming bills / obligations intent
        bills_keywords = [
            "upcoming bills", "upcoming commitments", "what bills", "due date",
            "rent due", "bills this month", "emis", "emi due", "credit card due",
            "credit card bill", "sips", "sip due"
        ]
        if any(w in lower for w in bills_keywords):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            commitments = summary["upcoming_commitments"]
            credits = summary["upcoming_credits"]

            rows = []
            for c in commitments:
                rows.append(f"| {c['settlement_date']} | **{c['description']}** | {cur_sym}{c['amount']:,.2f} | `{c['category']}` |")

            table_str = "\n".join(rows) if rows else "| None | No major obligations scheduled | - | - |"

            cred_rows = []
            for cr in credits:
                cred_rows.append(f"- **{cr['settlement_date']}**: {cr['description']} (+{cur_sym}{cr['amount']:,.2f})")
            creds_str = "\n".join(cred_rows) if cred_rows else "_No incoming salary credits scheduled in next 30 days._"

            content = (
                f"### 🗓️ Upcoming Fixed Obligations & EMIs (Next 30 Days)\n\n"
                f"| Due Date | Obligation / EMI | Amount | Category |\n"
                f"|---|---|---|---|\n"
                f"{table_str}\n\n"
                f"**Total Fixed Debits Due:** {cur_sym}{summary['upcoming_30d_debits_total']:,.2f}\n\n"
                f"#### 💰 Expected Salary / Inflows\n{creds_str}"
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "bills_list",
                "summary": summary,
            }

        # 4. Check for emergency fund advice
        if any(w in lower for w in ["emergency fund", "safety cushion", "minimum balance", "fd buffer"]):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            cushion = summary["emergency_cushion"]
            content = (
                f"### 🛡️ About Your Emergency Cushion (India 🇮🇳)\n\n"
                f"Your emergency cushion is currently set to **{cur_sym}{cushion:,.2f}**.\n\n"
                f"**Why this is crucial in India's digital credit economy:**\n"
                f"1. **Zero-Bounce Guarantee:** Keeps your account safe from auto-debit bounce charges (NACH / ECS ECS bounce fees are ₹400–₹500 + GST per instance).\n"
                f"2. **Strict Financial Protection:** The Co-Pilot will never recommend a purchase or No-Cost EMI that causes your balance to dip below this buffer.\n"
                f"3. **Recommended Rule:** Keep 2 to 3 months of essential fixed commitments (Rent + EMIs + Utilities) in this liquid buffer or Sweep-in FD."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "advice",
            }

        # 5. Default conversational greeting & help tailored for India
        summary = self.engine.get_financial_summary(target_id)
        cur = summary.get("home_currency", "INR")
        cur_sym = "₹" if cur == "INR" else cur
        safe = summary.get("safe_headroom_today", 0.0)

        content = (
            f"🙏 **Namaste! How can I help with your finances today?**\n\n"
            f"Here are popular queries Indian users ask me:\n"
            f"- **'Can I buy iPhone 16 for ₹79,900 on 6-month No-Cost EMI?'** — I'll simulate your 90-day bank cash flow.\n"
            f"- **'How much safe UPI budget do I have today?'** — (Current safe headroom: **{cur_sym}{safe:,.2f}**)\n"
            f"- **'What EMIs and credit card bills are due this month?'** — View upcoming rent, car loan, and card bills.\n"
            f"- **'Can I afford a Goa trip for ₹30,000 if I cut Swiggy orders?'** — Discover smart budget trade-offs."
        )
        return {
            "role": "assistant",
            "content": content,
            "type": "general",
        }

    def _extract_purchase_intent(self, text: str) -> dict[str, Any] | None:
        lower = text.lower()
        has_action = bool(re.search(r'\b(buy|purchase|afford|get|spend|order|pay\s+for|cost|trip|iphone|bike|laptop|tv)\b', lower))
        if not has_action:
            return None

        # Check for EMI months mention (e.g. "on 6-month emi", "3 months emi", "12 mo emi")
        months = None
        emi_match = re.search(r'([0-9]{1,2})\s*(?:-|–|\s)*(?:month|mo|m)\s*(?:no[- ]*cost\s*)?emi', lower)
        if emi_match:
            months = int(emi_match.group(1))

        # Check for Lakhs / Lacs: e.g. "1.5 lakh", "2 lakhs", "1.2 lac"
        lakh_match = re.search(r'([0-9]+(?:\.[0-9]{1,2})?)\s*(?:lakh|lakhs|lac|lacs)', lower)
        if lakh_match:
            amount = float(lakh_match.group(1)) * 100000.0
        else:
            # Check for 'k' multiplier: e.g. "80k", "50 k"
            k_match = re.search(r'([0-9]+(?:\.[0-9]{1,2})?)\s*k\b', lower)
            if k_match:
                amount = float(k_match.group(1)) * 1000.0
            else:
                cleaned_num_text = text.replace(",", "")
                # 1. First priority: explicitly prefixed with ₹ / Rs / INR
                curr_match = re.search(r'(?:₹|rs\.?|inr)\s*([0-9]+(?:\.[0-9]{1,2})?)', cleaned_num_text, re.IGNORECASE)
                if curr_match:
                    amount = float(curr_match.group(1))
                else:
                    # 2. Second priority: after "for", "cost", "worth", "at"
                    for_match = re.search(r'(?:for|cost|worth|at)\s*(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]{1,2})?)', cleaned_num_text, re.IGNORECASE)
                    if for_match:
                        amount = float(for_match.group(1))
                    else:
                        # 3. Third priority: pick the largest number (e.g. 79900 instead of 16 in iPhone 16)
                        all_nums = [float(n) for n in re.findall(r'\b[0-9]+(?:\.[0-9]{1,2})?\b', cleaned_num_text)]
                        if months and months in all_nums:
                            all_nums.remove(months)
                        if not all_nums:
                            return None
                        amount = max(all_nums)

        if amount <= 0:
            return None

        # Clean item name
        clean = re.sub(r'^(can i (afford|buy|purchase|get)|should i (buy|purchase|get)|i want to (buy|purchase|get)|i want to pay for)\s*', '', text, flags=re.IGNORECASE)
        clean = re.sub(r'(for\s+(?:₹|rs\.?|inr)?\s*[0-9,]+.*)$', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'(?:₹|rs\.?|inr)\s*[0-9,]+', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b[0-9,]+\s*(?:lakh|lakhs|lac|lacs|k)?\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b(?:on\s+)?(?:[0-9]{1,2}\s*(?:month|mo|m)\s*)?(?:no[- ]*cost\s*)?emi\b', '', clean, flags=re.IGNORECASE)
        clean = clean.strip(' ?,.!')

        item_name = clean.title() if clean and len(clean) > 2 else "Requested Purchase"

        return {
            "item": item_name,
            "amount": amount,
            "months": months,
        }

    def _format_purchase_response(self, eval_res: dict[str, Any]) -> str:
        explanation = eval_res["explanation"]
        status = eval_res["affordability_status"]
        method = eval_res["recommended_payment_method"]
        cur = eval_res["currency"]
        cur_sym = "₹" if cur == "INR" else cur
        safe_today = eval_res["amount_safe_to_pay_today"]
        plan = eval_res.get("payment_plan_summary")
        changes = eval_res.get("human_spending_changes", [])

        status_badge = {
            "affordable_now": "🟢 **STATUS: AFFORDABLE NOW (PAY IN FULL)**",
            "affordable_with_plan": "🟡 **STATUS: AFFORDABLE WITH PLAN / NO-COST EMI**",
            "affordable_later": "🟠 **STATUS: AFFORDABLE LATER (WAIT FOR SALARY)**",
            "not_affordable": "🔴 **STATUS: NOT RECOMMENDED (PROTECT EMERGENCY FUND)**",
        }.get(status, status)

        lines = [
            f"### {status_badge}",
            f"\n{explanation}\n",
            f"**Decision Summary (India 🇮🇳):**",
            f"- **Safe to Pay Today (UPI / Debit):** {cur_sym}{safe_today:,.2f}",
            f"- **Recommended Method:** `{method}`",
        ]

        if plan and plan != "none":
            lines.append(f"- **Recommended Payment Plan / EMI:** `{plan}`")

        if changes:
            lines.append("\n**Recommended Budget Trade-Offs (Controllable Expenses):**")
            for ch in changes:
                lines.append(f"- ✂️ {ch}")

        lines.append(f"\n*(Tip: See the 90-day Cash Curve simulation chart below to inspect your balance vs emergency buffer)*")
        return "\n".join(lines)
