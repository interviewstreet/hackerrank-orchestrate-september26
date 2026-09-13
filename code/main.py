"""Entry point for the Buy or Wait? solution.

Runs the full pipeline (Modules 1, 6, 3, 4, 5, 7, 9 — loaders, llm_extract,
event_normalizer, forecast_engine, plan_selector, llm_explain, output_writer)
over every row in dataset/requests.csv and writes the final output.csv to the
repo root, per README.md's Quick Start.

Modules 6 (message/image fact extraction) and 7 (decision_explanation
writing) call Claude when ANTHROPIC_API_KEY (or LLM_API_KEY) is set in the
environment. Without a key, both no-op safely: facts=[] and
decision_explanation stays plan_selector's deterministic template — the
pipeline is fully runnable, just LLM-free.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...   # optional — enables Modules 6/7
    python3 code/main.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from output_writer import run_pipeline, write_output_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
OUTPUT_PATH = REPO_ROOT / "output.csv"


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    start = time.time()
    rows, extract_usage, explain_usage = run_pipeline(DATASET_DIR)
    write_output_csv(rows, OUTPUT_PATH)
    elapsed = time.time() - start

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH} in {elapsed:.2f}s")

    if extract_usage or explain_usage:
        extract_in = sum(u.input_tokens for u in extract_usage)
        extract_out = sum(u.output_tokens for u in extract_usage)
        explain_in = sum(u.input_tokens for u in explain_usage)
        explain_out = sum(u.output_tokens for u in explain_usage)
        print(
            f"llm_extract: {len(extract_usage)} calls, {extract_in} input / {extract_out} output tokens"
        )
        print(
            f"llm_explain: {len(explain_usage)} calls, {explain_in} input / {explain_out} output tokens"
        )
        print(
            f"Total: {extract_in + explain_in} input / {extract_out + explain_out} output tokens "
            f"across {len(extract_usage) + len(explain_usage)} calls "
            "(fill these into evaluation/usage_report.md for submission)"
        )
    else:
        print(
            "No LLM calls made (no ANTHROPIC_API_KEY/LLM_API_KEY set) — "
            "facts=[] and decision_explanation used the deterministic template throughout"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
