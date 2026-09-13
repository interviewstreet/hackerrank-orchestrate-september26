"""Entry point for the Buy or Wait? solution.

Runs the full pipeline (Modules 1, 6, 3, 4, 5, 7, 9, 8 — loaders, llm_extract,
event_normalizer, forecast_engine, plan_selector, llm_explain, output_writer,
usage_tracker) over every row in dataset/requests.csv, writes the final
output.csv to the repo root (per README.md's Quick Start), and regenerates
code/evaluation/usage_report.md from this run's actual token usage.

Modules 6 (message/image fact extraction) and 7 (decision_explanation
writing) call Claude when ANTHROPIC_API_KEY (or LLM_API_KEY) is set in the
environment. Without a key, both no-op safely: facts=[] and
decision_explanation stays plan_selector's deterministic template — the
pipeline is fully runnable, just LLM-free, and usage_report.md records that
no calls were made.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...   # optional — enables Modules 6/7
    python3 code/evaluation/main.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from output_writer import run_pipeline, write_output_csv  # noqa: E402
from usage_tracker import write_usage_report  # noqa: E402

REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
OUTPUT_PATH = REPO_ROOT / "output.csv"
USAGE_REPORT_PATH = Path(__file__).resolve().parent / "usage_report.md"


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    start = time.time()
    rows, extract_usage, explain_usage = run_pipeline(DATASET_DIR)
    write_output_csv(rows, OUTPUT_PATH)
    write_usage_report(USAGE_REPORT_PATH, extract_usage, explain_usage, len(rows))
    elapsed = time.time() - start

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH} in {elapsed:.2f}s")
    print(f"Wrote usage report to {USAGE_REPORT_PATH}")

    total_calls = len(extract_usage) + len(explain_usage)
    if total_calls:
        total_in = sum(u.input_tokens for u in extract_usage) + sum(u.input_tokens for u in explain_usage)
        total_out = sum(u.output_tokens for u in extract_usage) + sum(u.output_tokens for u in explain_usage)
        print(
            f"LLM usage: {total_calls} calls "
            f"({len(extract_usage)} llm_extract + {len(explain_usage)} llm_explain), "
            f"{total_in} input / {total_out} output tokens — see usage_report.md for the full breakdown"
        )
    else:
        print(
            "No LLM calls made (no ANTHROPIC_API_KEY/LLM_API_KEY set) — "
            "facts=[] and decision_explanation used the deterministic template throughout"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
