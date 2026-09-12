import argparse
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from code.src.data.repository import DataRepository
from code.src.graph.builder import build_financial_agent_graph
from code.src.config import DATASET_DIR


def main():
    parser = argparse.ArgumentParser(description="Debug single financial request through LangGraph agent")
    parser.add_argument("--request-id", required=True, help="Request ID to run, e.g. request_01 or request_26")
    args = parser.parse_args()

    req_id = args.request_id.strip()
    print(f"=== INITIALIZING AGENT FOR {req_id} ===")

    repo = DataRepository(DATASET_DIR)
    graph = build_financial_agent_graph(repo)

    initial_state = {
        "run_id": req_id,
        "errors": [],
        "warnings": [],
        "audit_log": [],
    }

    final_state = graph.invoke(initial_state)

    print("\n" + "=" * 60)
    print("1. REQUEST")
    print("=" * 60)
    print(final_state.get("request"))

    print("\n" + "=" * 60)
    print("2. PROFILE")
    print("=" * 60)
    print(final_state.get("profile"))

    print("\n" + "=" * 60)
    print("3. RAW EVENTS (count):", len(final_state.get("raw_events", [])))
    print("=" * 60)
    for e in final_state.get("raw_events", [])[:5]:
        print(f"  {e.settlement_date} | {e.event_id} | {e.category} | {e.amount} {e.currency} | {e.status} | {e.description}")

    print("\n" + "=" * 60)
    print("4. IMAGE FACTS")
    print("=" * 60)
    for fact in final_state.get("image_facts", []):
        print(f"  Image {fact.image_id} -> Event {fact.related_event_id}: amt={fact.extracted_amount} curr={fact.extracted_currency}")

    print("\n" + "=" * 60)
    print("5. MESSAGE FACTS")
    print("=" * 60)
    for fact in final_state.get("message_facts", []):
        print(f"  Msg {fact.message_id} -> Action: {fact.action}, new_amt={fact.new_amount}, new_date={fact.new_date}, text={fact.evidence[:80]}")

    print("\n" + "=" * 60)
    print("6. RESOLVED EVENTS (count):", len(final_state.get("resolved_events", [])))
    print("=" * 60)
    for e in final_state.get("resolved_events", [])[:8]:
        print(f"  {e.settlement_date} | {e.event_id} | {e.category} | {e.direction} {e.converted_amount} {e.currency} | {e.evidence_source}")

    print("\n" + "=" * 60)
    print("7. BASE FORECAST")
    print("=" * 60)
    fc = final_state.get("base_forecast")
    if fc:
        print(f"  Starting Balance: {fc.starting_balance}")
        print(f"  Lowest Balance: {fc.lowest_balance} on {fc.lowest_balance_date}")
        print(f"  Ending Balance: {fc.ending_balance}")
        print(f"  Base Safe: {fc.safe}")

    print("\n" + "=" * 60)
    print("8. BASELINE CAPACITY")
    print("=" * 60)
    print(f"  baseline_amount_safe_to_pay: {final_state.get('baseline_amount_safe_to_pay')}")
    print(f"  earliest_baseline_full_payment_date: {final_state.get('earliest_baseline_full_payment_date')}")

    print("\n" + "=" * 60)
    print("9. CANDIDATE PLANS (count):", len(final_state.get("candidate_plans", [])))
    print("=" * 60)
    for p in final_state.get("candidate_plans", []):
        print(f"  Plan {p.plan_id} ({p.method}): total={p.total_amount}, completion={p.completion_date}, payments={len(p.payments)}")

    print("\n" + "=" * 60)
    print("10. PLAN EVALUATIONS")
    print("=" * 60)
    for ev in final_state.get("evaluated_plans", []):
        print(f"  Plan {ev.plan_id}: safe={ev.financially_safe}, deadline_ok={ev.deadline_ok}, method_allowed={ev.method_allowed}, eligible={ev.eligible}, lowest_bal={ev.lowest_balance}, violations={ev.violation_codes}")

    print("\n" + "=" * 60)
    print("11. APPLIED SPENDING CHANGES")
    print("=" * 60)
    for c in final_state.get("applied_spending_changes", []):
        print(f"  Action: {c.action} on {c.event_id} ({c.category}), old={c.old_amount}, new={c.new_amount}")

    print("\n" + "=" * 60)
    print("12. FINAL DECISION")
    print("=" * 60)
    print(final_state.get("decision"))

    print("\n" + "=" * 60)
    print("13. FINAL OUTPUT ROW")
    print("=" * 60)
    out_row = final_state.get("output_row")
    if out_row:
        for k, v in out_row.to_csv_dict().items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
