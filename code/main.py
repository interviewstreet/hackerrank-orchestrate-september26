"""Command-line entry point for the Buy or Wait deterministic solution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from buy_or_wait import DatasetLoader, DatasetValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Buy or Wait input validation")
    parser.add_argument("--validate-input", action="store_true", help="validate dataset inputs without generating output.csv")
    parser.add_argument("--dataset-dir", type=Path, default=Path(__file__).resolve().parents[1] / "dataset")
    args = parser.parse_args()
    if not args.validate_input:
        parser.error("only --validate-input is implemented; decision generation is intentionally not available yet")
    try:
        dataset = DatasetLoader(args.dataset_dir).load()
    except DatasetValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Dataset validation passed: {args.dataset_dir}")
    for filename, count in dataset.row_counts().items():
        print(f"  {filename}: {count} rows")
    print(f"  image-backed event amounts resolved: {sum(event.amount_from_image_evidence for event in dataset.events)}")
    print("No output.csv was generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
