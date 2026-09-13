"""Entry point for the Buy or Wait? solution.

Runs the deterministic pipeline (Modules 1, 3, 4, 5, 9 — loaders,
event_normalizer, forecast_engine, plan_selector, output_writer) over every
row in dataset/requests.csv and writes the final output.csv to the repo root,
per README.md's Quick Start.

Modules 6/7 (LLM message/image extraction and explanation) are not wired in
yet: facts=[] for every request, and decision_explanation comes from
plan_selector's deterministic template.

Usage:
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
    rows = run_pipeline(DATASET_DIR)
    write_output_csv(rows, OUTPUT_PATH)
    elapsed = time.time() - start

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH} in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
