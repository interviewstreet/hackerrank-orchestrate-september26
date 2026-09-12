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

        # 1. Check for purchase evaluation intent: e.g. "Can I buy X for $Y?", "I want to purchase a phone for 800"
        purchase_intent = self._extract_purchase_intent(text)
        if purchase_intent:
            item_name = purchase_intent["item"]
            amount = purchase_intent["amount"]
            eval_result = self.engine.evaluate_purchase(
                user_id=target_id,
                item_name=item_name,
                amount=amount,
            )
            
            # Format assistant response
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
            "available to spend", "spend today", "afford today", "current balance"
        ]
        if any(w in lower for w in headroom_keywords):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            bal = summary["current_balance"]
            cushion = summary["emergency_cushion"]
            safe = summary["safe_headroom_today"]
            upcoming = summary["upcoming_30d_debits_total"]

            content = (
                f"### 📊 Your Current Financial Headroom\n\n"
                f"- **Current Balance:** {bal:,.2f} {cur}\n"
                f"- **Emergency Cushion (Protected Floor):** {cushion:,.2f} {cur}\n"
                f"- **Upcoming Obligations (Next 30 Days):** {upcoming:,.2f} {cur}\n\n"
                f"💡 **Safe Discretionary Headroom Today: {safe:,.2f} {cur}**\n\n"
                f"You can safely spend up to **{safe:,.2f} {cur}** on discretionary purchases right now without violating your emergency floor or risking upcoming bills."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "headroom_summary",
                "summary": summary,
            }

        # 3. Check for upcoming bills / obligations intent
        if any(w in lower for w in ["upcoming bills", "upcoming commitments", "what bills", "due date", "rent due", "bills this month"]):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            commitments = summary["upcoming_commitments"]
            credits = summary["upcoming_credits"]

            rows = []
            for c in commitments:
                rows.append(f"| {c['settlement_date']} | **{c['description']}** | {c['amount']:,.2f} {cur} | `{c['category']}` |")

            table_str = "\n".join(rows) if rows else "| None | No major obligations scheduled | - | - |"

            cred_rows = []
            for cr in credits:
                cred_rows.append(f"- **{cr['settlement_date']}**: {cr['description']} (+{cr['amount']:,.2f} {cur})")
            creds_str = "\n".join(cred_rows) if cred_rows else "_No incoming salary or credits confirmed in next 30 days._"

            content = (
                f"### 🗓️ Upcoming Financial Obligations (Next 30 Days)\n\n"
                f"| Date | Obligation | Amount | Category |\n"
                f"|---|---|---|---|\n"
                f"{table_str}\n\n"
                f"**Total Upcoming Debits:** {summary['upcoming_30d_debits_total']:,.2f} {cur}\n\n"
                f"#### 💰 Expected Income / Credits\n{creds_str}"
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "bills_list",
                "summary": summary,
            }

        # 4. Check for emergency fund advice
        if any(w in lower for w in ["emergency fund", "safety cushion", "minimum balance"]):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cushion = summary["emergency_cushion"]
            content = (
                f"### 🛡️ About Your Emergency Cushion\n\n"
                f"Your target emergency reserve is currently set to **{cushion:,.2f} {cur}**.\n\n"
                f"**Why this matters in the credit economy:**\n"
                f"1. **Zero-Overdraft Buffer:** Even if unexpected bills or bank fees arrive, this money stays untouched.\n"
                f"2. **Strict Protection:** The Copilot will never recommend a purchase or installment schedule that breaches this baseline floor.\n"
                f"3. **Rule of Thumb:** Financial advisors recommend keeping 1–3 months of essential fixed expenses in your emergency reserve. You can adjust this floor anytime in the profile settings."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "advice",
            }

        # 5. Default conversational greeting & help
        summary = self.engine.get_financial_summary(target_id)
        cur = summary.get("home_currency", "USD")
        safe = summary.get("safe_headroom_today", 0.0)

        content = (
            f"I can help you make a safe financial decision! Here is what you can ask me:\n\n"
            f"- **'Can I buy a laptop for 950?'** — I'll simulate your 90-day cash flow and give you an instant verdict.\n"
            f"- **'How much can I safely spend today?'** — (Current safe headroom: **{safe:,.2f} {cur}**)\n"
            f"- **'What bills are due this month?'** — Check upcoming rent, subscriptions, and EMIs.\n"
            f"- **'How do I budget for a vacation?'** — Learn what spending adjustments to make."
        )
        return {
            "role": "assistant",
            "content": content,
            "type": "general",
        }

    def _extract_purchase_intent(self, text: str) -> dict[str, Any] | None:
        # Match patterns like:
        # "Can I buy a laptop for $1200?"
        # "I want to buy Sony headphones for 350"
        # "Should I purchase Nike shoes for $150 today?"
        # "Can I afford 500 for a weekend trip?"
        
        # Regex for price: $?([0-9]+(?:\.[0-9]{1,2})?)
        price_match = re.search(r'[\$€£₹]?\s*([0-9]{1,6}(?:\.[0-9]{1,2})?)\s*(?:dollars|usd|eur|gbp|inr|\$|€|£|₹)?', text, re.IGNORECASE)
        if not price_match:
            return None

        # Check if text mentions buy, purchase, afford, get, pay for, cost
        has_action = bool(re.search(r'\b(buy|purchase|afford|get|spend|order|pay\s+for|cost)\b', text, re.IGNORECASE))
        if not has_action:
            return None

        # Extract amount
        # Find all number candidates in text
        numbers = re.findall(r'\b(?:\$|€|£|₹)?\s*([0-9]+(?:\.[0-9]{1,2})?)\b', text)
        if not numbers:
            return None

        # Pick the most likely price (usually highest or after "for" / "$")
        for_match = re.search(r'(?:for|\$|€|£|₹)\s*([0-9]+(?:\.[0-9]{1,2})?)', text, re.IGNORECASE)
        if for_match:
            amount = float(for_match.group(1))
        else:
            amount = float(numbers[0])

        if amount <= 0:
            return None

        # Extract item description
        # Remove trigger phrases
        clean = re.sub(r'^(can i (afford|buy|purchase|get)|should i (buy|purchase|get)|i want to (buy|purchase|get)|i want to pay for)\s*', '', text, flags=re.IGNORECASE)
        clean = re.sub(r'(for\s+[\$€£₹]?\s*[0-9]+(?:\.[0-9]{1,2})?.*)$', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'[\$€£₹]?\s*[0-9]+(?:\.[0-9]{1,2})?', '', clean)
        clean = clean.strip(' ?,.!')
        
        item_name = clean.title() if clean and len(clean) > 2 else "Requested Item"

        return {
            "item": item_name,
            "amount": amount,
        }

    def _format_purchase_response(self, eval_res: dict[str, Any]) -> str:
        explanation = eval_res["explanation"]
        status = eval_res["affordability_status"]
        method = eval_res["recommended_payment_method"]
        cur = eval_res["currency"]
        safe_today = eval_res["amount_safe_to_pay_today"]
        plan = eval_res.get("payment_plan_summary")
        changes = eval_res.get("human_spending_changes", [])

        status_badge = {
            "affordable_now": "🟢 **STATUS: AFFORDABLE NOW**",
            "affordable_with_plan": "🟡 **STATUS: AFFORDABLE WITH PLAN**",
            "affordable_later": "🟠 **STATUS: AFFORDABLE LATER (WAIT)**",
            "not_affordable": "🔴 **STATUS: NOT AFFORDABLE**",
        }.get(status, status)

        lines = [
            f"### {status_badge}",
            f"\n{explanation}\n",
            f"**Decision Summary:**",
            f"- **Safe to Pay Today:** {safe_today:,.2f} {cur}",
            f"- **Recommended Method:** `{method}`",
        ]

        if plan and plan != "none":
            lines.append(f"- **Recommended Payment Plan:** `{plan}`")

        if changes:
            lines.append("\n**Actionable Spending Adjustments to Make It Safe:**")
            for ch in changes:
                lines.append(f"- ✨ {ch}")

        lines.append(f"\n*(Tip: Scroll down to view the 90-day Cash Curve simulation chart below)*")
        return "\n".join(lines)
