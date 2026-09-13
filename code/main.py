"""Command-line entry point for the Buy or Wait deterministic solution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from buy_or_wait import BaselineAffordabilityCalculator, BaselineSimulator, CashFlowNormalizer, DatasetLoader, DatasetValidationError
from buy_or_wait.output import write_output
from buy_or_wait.planner import DeterministicPlanner


def main() -> int:
    parser = argparse.ArgumentParser(description="Buy or Wait input validation")
    parser.add_argument("--validate-input", action="store_true", help="validate dataset inputs without generating output.csv")
    parser.add_argument("--simulate-baseline", action="store_true", help="run deterministic baseline simulations without generating output.csv")
    parser.add_argument("--baseline-affordability", action="store_true", help="calculate deterministic baseline capacity without generating output.csv")
    parser.add_argument("--generate-output", action="store_true", help="generate and validate root output.csv")
    parser.add_argument("--dataset-dir", type=Path, default=Path(__file__).resolve().parents[1] / "dataset")
    args = parser.parse_args()
    if not args.validate_input and not args.simulate_baseline and not args.baseline_affordability and not args.generate_output:
        parser.error("use --validate-input, --simulate-baseline, or --baseline-affordability; decision generation is intentionally not available yet")
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
    if args.simulate_baseline:
        simulator = BaselineSimulator(CashFlowNormalizer(dataset))
        results = tuple(simulator.simulate(request) for request in dataset.requests)
        repeated = tuple(simulator.simulate(request) for request in dataset.requests)
        if results != repeated:
            print("Baseline simulation is not repeatable.", file=sys.stderr)
            return 1
        violations = sum(result.violates_minimum_balance for result in results)
        print(f"Baseline simulations completed: {len(results)} requests; minimum-balance violations: {violations}; repeatability: passed")
    if args.baseline_affordability:
        calculator = BaselineAffordabilityCalculator(BaselineSimulator(CashFlowNormalizer(dataset)))
        results = tuple(calculator.calculate(request) for request in dataset.requests)
        repeated = tuple(calculator.calculate(request) for request in dataset.requests)
        if results != repeated:
            print("Baseline affordability calculation is not repeatable.", file=sys.stderr)
            return 1
        if len(results) != len(dataset.requests):
            print("Baseline affordability result count is incorrect.", file=sys.stderr)
            return 1
        if any(result.amount_safe_to_pay < 0 or result.amount_safe_to_pay > request.requested_amount for request, result in zip(dataset.requests, results)):
            print("Baseline affordability amount is outside the request bounds.", file=sys.stderr)
            return 1
        print(f"Baseline affordability completed: {len(results)} requests; repeatability: passed")
    if args.generate_output:
        simulator = BaselineSimulator(CashFlowNormalizer(dataset))
        planner = DeterministicPlanner(dataset, simulator)
        rows = [planner.decide(request) for request in dataset.requests]
        output_path = Path(__file__).resolve().parents[1] / "output.csv"
        write_output(output_path, rows, dataset.output_template_request_ids, dataset=dataset, simulator=simulator)
        first = output_path.read_bytes()
        write_output(output_path, [planner.decide(request) for request in dataset.requests], dataset.output_template_request_ids, dataset=dataset, simulator=simulator)
        if output_path.read_bytes() != first:
            print("Output generation is not repeatable.", file=sys.stderr); return 1
        print(f"Output generated and validated: {output_path} ({len(rows)} rows; repeatability: passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
