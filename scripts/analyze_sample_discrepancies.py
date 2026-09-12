import csv
import sys
from pathlib import Path
from datetime import date

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from code.src.pipeline import FinancialAgentPipeline
from code.src.data.repository import DataRepository
from code.src.config import DATASET_DIR
from code.src.finance.plans import generate_candidate_plans, evaluate_plan
from code.src.finance.optimizer import get_candidate_individual_changes


def main():
    pipeline = FinancialAgentPipeline(DATASET_DIR)
    repo = pipeline.repo
    sample_csv = DATASET_DIR / "sample_requests.csv"

    with open(sample_csv, mode="r", encoding="utf-8") as f:
        samples = list(csv.DictReader(f))

    print("=" * 120, flush=True)
    print("DIAGNOSTIC ANALYSIS OF THE 25 SAMPLE REQUESTS", flush=True)
    print("=" * 120, flush=True)

    for row in samples:
        req_id = row["request_id"].strip()
        u_id = row["user_id"].strip()
        prof = repo.profiles[u_id]
        req = repo.requests[req_id]

        actual_row = pipeline.process_request(req_id)
        actual = actual_row.to_csv_dict()
        expected = row

        # Inspect graph state
        st = pipeline.graph.invoke({"run_id": req_id, "errors": [], "warnings": [], "audit_log": []})

        resolved_events = st.get("resolved_events", [])
        future_income = [e for e in resolved_events if e.direction == "credit"]
        future_mandatory = [e for e in resolved_events if e.direction == "debit" and e.flexibility == "fixed"]
        future_flexible = [e for e in resolved_events if e.direction == "debit" and e.flexibility != "fixed"]

        base_fc = st.get("base_forecast")
        cand_plans = st.get("candidate_plans", [])
        eval_plans = st.get("evaluated_plans", [])
        cand_changes = get_candidate_individual_changes(resolved_events, prof)

        diffs = []
        for field in [
            "amount_safe_to_pay",
            "affordability_status",
            "recommended_payment_method",
            "payment_plan",
            "earliest_date_for_full_payment",
            "spending_changes_needed",
        ]:
            if actual.get(field) != expected.get(field):
                diffs.append(f"{field}: Expected={expected.get(field)!r} vs Actual={actual.get(field)!r}")

        print(f"\n{'='*40} {req_id} (User: {u_id}) {'='*40}", flush=True)
        print(f"REQUEST INFO: Date={req.request_date} | Amount={req.requested_amount:,.2f} | Deadline={req.desired_completion_date} | AllowsPartial={req.allows_partial_payment}", flush=True)
        print(f"PROFILE: StartBal={prof.current_available_balance:,.2f} {prof.home_currency} | MinKeep={prof.minimum_balance_to_keep:,.2f} | GrossHeadroom={prof.current_available_balance - prof.minimum_balance_to_keep:,.2f}", flush=True)
        print(f"FUTURE EVENTS: Income={len(future_income)} ({sum(e.converted_amount for e in future_income):,.2f}) | MandatoryDebits={len(future_mandatory)} ({sum(e.converted_amount for e in future_mandatory):,.2f}) | FlexibleDebits={len(future_flexible)} ({sum(e.converted_amount for e in future_flexible):,.2f})", flush=True)

        if base_fc:
            print(f"BASELINE FORECAST: LowestBal={base_fc.lowest_balance:,.2f} on {base_fc.lowest_balance_date} | EndingBal={base_fc.ending_balance:,.2f} | Safe={base_fc.safe}", flush=True)

        print(f"BASELINE SAFE AMOUNT: Actual={actual.get('amount_safe_to_pay')} | Expected={expected.get('amount_safe_to_pay')}", flush=True)
        print(f"EARLIEST FULL DATE:   Actual={actual.get('earliest_date_for_full_payment')} | Expected={expected.get('earliest_date_for_full_payment')}", flush=True)

        print("CANDIDATE PLANS EVALUATION:", flush=True)
        for ep in eval_plans:
            print(f"  Plan: {ep.plan.method:<16} | Safe={ep.financially_safe} | DeadlineOk={ep.deadline_ok} | Eligible={ep.eligible} | MinBal={ep.lowest_balance:,.2f} | Total={ep.plan.total_amount:,.2f}", flush=True)

        print(f"SPENDING CHANGE CANDIDATES ({len(cand_changes)}): {[f'{c.action}:{c.event_id}({c.category})' for c in cand_changes]}", flush=True)
        print(f"EXPECTED OUTPUT: {expected.get('affordability_status')} | {expected.get('recommended_payment_method')} | {expected.get('payment_plan')} | Changes={expected.get('spending_changes_needed')}", flush=True)
        print(f"ACTUAL OUTPUT:   {actual.get('affordability_status')} | {actual.get('recommended_payment_method')} | {actual.get('payment_plan')} | Changes={actual.get('spending_changes_needed')}", flush=True)

        if diffs:
            print("DIFFERENCES FOUND:", flush=True)
            for d in diffs:
                print(f"  * {d}", flush=True)
        else:
            print("MATCH: 100% Exact Match on all fields!", flush=True)


if __name__ == "__main__":
    main()
