"""
main.py — CLI entry point for the Buy or Wait? financial decision agent.

Usage:
    python code/main.py
    python code/main.py --dataset dataset/ --output dataset/output.csv
    python code/main.py --validate-only   # Run dataset validation and exit

Runs the full pipeline:
1. Load & validate dataset
2. Extract evidence (OCR + NLP) — Phase 2
3. Evaluate each request via the deterministic simulator + solver — Phases 3–4
4. Generate explanations — Phase 5
5. Write output.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

# Configure logging before any imports that use the logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Buy or Wait? — AI Financial Decision Agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to the dataset directory (overrides DATASET_DIR env var).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write output.csv (overrides OUTPUT_PATH env var).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run dataset validation checks and exit without producing output.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override LOG_LEVEL from env.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Apply log-level override before importing settings (which may log)
    if args.log_level:
        logging.getLogger().setLevel(args.log_level)

    try:
        from .config import settings
    except ImportError:
        # Running as a script directly: python code/main.py
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from code.config import settings  # type: ignore[no-redef]

    if args.log_level:
        logging.getLogger().setLevel(args.log_level)
    else:
        logging.getLogger().setLevel(settings.log_level)

    dataset_dir = args.dataset or settings.dataset_dir
    output_path = args.output or settings.output_path

    logger.info("Buy or Wait? — starting pipeline")
    logger.info("  dataset_dir : %s", dataset_dir)
    logger.info("  output_path : %s", output_path)
    logger.info("  model       : %s", settings.model_name)

    # ── Phase 1: Load & validate dataset ────────────────────────────────────
    try:
        from code.ingestion import DatasetLoader, DatasetValidator
    except ImportError:
        from code.ingestion import DatasetLoader, DatasetValidator  # type: ignore[no-redef]

    loader = DatasetLoader(dataset_dir)
    loader.load_all()

    validator = DatasetValidator(
        profiles=loader.profiles,
        events=loader.events,
        requests=loader.requests,
        payment_options=loader.payment_options,
    )
    issues = validator.validate()
    fatal_errors = [i for i in issues if i.severity.value == "ERROR"]
    if fatal_errors:
        logger.error("%d fatal validation errors — see logs above.", len(fatal_errors))
        if args.validate_only:
            return 1

    if args.validate_only:
        logger.info("Validation complete. %d warnings, %d errors.", len(issues) - len(fatal_errors), len(fatal_errors))
        return 0 if not fatal_errors else 1

    # ── Phases 2–5: Evidence → Simulate → Solve → Explain (TODO) ───────────
    logger.info(
        "Phases 2–5 not yet implemented. Writing empty output for %d requests.",
        len(loader.requests),
    )

    # Write placeholder output so the file always exists with correct headers
    from code.models.output import OUTPUT_COLUMNS
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for req in loader.requests:
            writer.writerow({
                "request_id": req.request_id,
                "amount_safe_to_pay": "",
                "affordability_status": "",
                "recommended_payment_method": "",
                "payment_plan": "",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "",
                "decision_explanation": "",
            })

    logger.info("Placeholder output.csv written to %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
