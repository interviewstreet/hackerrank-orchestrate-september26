"""Buy or Wait? — Final Production Pipeline

Loads dataset files, retrieves extracted evidence from messages and images,
runs deterministic 90-day cash flow projections and candidate ranking,
and generates dataset/output.csv matching the strict HackerRank challenge contract.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from config import DATASET_DIR, OUTPUT_PATH
from data import index_datasets, load_dataset_files
from evidence import build_evidence_lookups
from plans import make_decision


def main() -> None:
    print("=" * 70)
    print("BUY OR WAIT? — FINANCIAL DECISION AGENT")
    print("=" * 70)

    # 1. Load datasets
    requests_df, profiles_df, events_df, options_df, rates_df = load_dataset_files(DATASET_DIR)
    print(f"Loaded {len(requests_df)} requests, {len(profiles_df)} profiles, {len(events_df)} events.")

    # 2. Load extracted evidence from cache
    blank_amounts, confirmed_incomes, cancelled_events, amended_events = build_evidence_lookups()
    print(
        f"Loaded evidence: {len(blank_amounts)} image amounts, "
        f"{len(confirmed_incomes)} users with confirmed incomes, "
        f"{len(cancelled_events)} cancelled events, "
        f"{len(amended_events)} amended events."
    )

    # 3. Pre-index tables by user/request key
    profiles_by_user, events_by_user, options_by_req = index_datasets(
        profiles_df, events_df, options_df
    )

    # 4. Generate decisions for each request
    output_rows = []
    status_counts: dict[str, int] = {}
    method_counts: dict[str, int] = {}

    print(f"\nEvaluating {len(requests_df)} requests...")
    for _, req in requests_df.iterrows():
        req_id = str(req["request_id"])
        user_id = str(req["user_id"])

        profile = profiles_by_user.get(user_id)
        if profile is None:
            raise ValueError(f"Profile missing for user {user_id} in request {req_id}")

        user_events = events_by_user.get(user_id, pd.DataFrame())
        user_options = options_by_req.get(req_id, pd.DataFrame())
        user_incomes = confirmed_incomes.get(user_id, [])

        decision = make_decision(
            req,
            profile,
            user_events,
            user_options,
            exchange_rates=rates_df,
            blank_amounts=blank_amounts,
            confirmed_incomes=user_incomes,
            cancelled_events=cancelled_events,
            amended_events=amended_events,
        )

        status_counts[decision.affordability_status] = status_counts.get(decision.affordability_status, 0) + 1
        method_counts[decision.recommended_payment_method] = method_counts.get(decision.recommended_payment_method, 0) + 1

        output_rows.append({
            "request_id": decision.request_id,
            "amount_safe_to_pay": decision.amount_safe_to_pay,
            "affordability_status": decision.affordability_status,
            "recommended_payment_method": decision.recommended_payment_method,
            "payment_plan": decision.payment_plan,
            "earliest_date_for_full_payment": decision.earliest_date_for_full_payment,
            "spending_changes_needed": decision.spending_changes_needed,
            "decision_explanation": decision.decision_explanation,
        })

    # 5. Write final output.csv (to both dataset/output.csv and root output.csv)
    output_df = pd.DataFrame(output_rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(OUTPUT_PATH, index=False)
    output_df.to_csv(CODE_DIR.parent / "output.csv", index=False)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"Generated output file: {OUTPUT_PATH}")
    print(f"Total rows written:    {len(output_df)}")
    print("\nAffordability Status Breakdown:")
    for status, cnt in sorted(status_counts.items()):
        print(f"  * {status:25s}: {cnt:4d} ({cnt / len(output_df):.1%})")
    print("\nPayment Method Breakdown:")
    for method, cnt in sorted(method_counts.items()):
        print(f"  * {method:25s}: {cnt:4d} ({cnt / len(output_df):.1%})")


if __name__ == "__main__":
    main()
