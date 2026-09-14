import csv
from pathlib import Path
from code.src.config import DATASET_DIR, OUTPUT_PATH, USAGE_REPORT_PATH
from code.src.data.repository import DataRepository
from code.src.graph.builder import build_financial_agent_graph
from code.src.models import OutputRow
from code.src.llm.client import global_tracker


class FinancialAgentPipeline:
    def __init__(self, dataset_dir: Path = DATASET_DIR):
        self.dataset_dir = dataset_dir
        self.repo = DataRepository(dataset_dir)
        self.graph = build_financial_agent_graph(self.repo)

    def process_request(self, request_id: str) -> OutputRow:
        initial_state = {
            "run_id": request_id,
            "errors": [],
            "warnings": [],
            "audit_log": [],
        }
        final_state = self.graph.invoke(initial_state)
        return final_state["output_row"]

    def process_all_requests(
        self,
        output_csv_path: Path = OUTPUT_PATH,
        requests_csv_path: Path | None = None,
    ) -> list[OutputRow]:
        req_file = requests_csv_path or (self.dataset_dir / "requests.csv")
        results: list[OutputRow] = []

        # Read requests in exact original order
        ordered_request_ids = []
        with open(req_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ordered_request_ids.append(row["request_id"].strip())

        print(f"Starting pipeline run for {len(ordered_request_ids)} requests...", flush=True)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        results_by_id = {}
        with ThreadPoolExecutor(max_workers=16) as executor:
            future_to_id = {executor.submit(self.process_request, req_id): req_id for req_id in ordered_request_ids}
            completed_count = 0
            for future in as_completed(future_to_id):
                req_id = future_to_id[future]
                try:
                    out_row = future.result()
                    results_by_id[req_id] = out_row
                except Exception as ex:
                    print(f"Error processing {req_id}: {ex}", flush=True)
                completed_count += 1
                if completed_count % 10 == 0 or completed_count == len(ordered_request_ids):
                    print(f"Processed {completed_count}/{len(ordered_request_ids)} requests...", flush=True)

        # Preserve exact original order
        results = [results_by_id[req_id] for req_id in ordered_request_ids if req_id in results_by_id]
        output_rows_dicts = [out_row.to_csv_dict() for out_row in results]

        # Write output.csv with exact required headers
        fieldnames = [
            "request_id",
            "amount_safe_to_pay",
            "affordability_status",
            "recommended_payment_method",
            "payment_plan",
            "earliest_date_for_full_payment",
            "spending_changes_needed",
            "decision_explanation",
        ]
        with open(output_csv_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows_dicts)

        dataset_out = self.dataset_dir / "output.csv"
        if output_csv_path.resolve() != dataset_out.resolve():
            with open(dataset_out, mode="w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(output_rows_dicts)

        print(f"Successfully wrote {len(results)} rows to {output_csv_path}", flush=True)

        # Write usage report
        usage_md = global_tracker.generate_report_markdown(total_requests=len(results))
        USAGE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_REPORT_PATH, mode="w", encoding="utf-8") as f:
            f.write(usage_md)

        return results
