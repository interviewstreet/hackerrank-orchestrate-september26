"""Buy or Wait? -- evaluation entry point.

    python code/evaluation/main.py --show-split
    python code/evaluation/main.py --split dev    --mode deterministic
    python code/evaluation/main.py --split report --mode assisted --compare-baseline

Every run prints an audit header first: which script ran, which dataset and
split manifest (with its fingerprint), how many rows, which subset, the
disjointness result, and the system under test. A reader must be able to tell
what was measured without opening the code.

Milestone status: both `--mode deterministic` and `--mode assisted` are scored
via `main.predict_one`, the identical per-row path `main.py` publishes from.
`--compare-baseline` additionally scores the deterministic-only baseline on
the same subset when `--mode assisted` is selected, so the evidence layer's
effect is visible request-for-request rather than inferred from two separate
runs.

Exit codes: 0 success, 1 dataset/split error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))  # make `buy_or_wait` and `evaluation` importable
REPO_ROOT = CODE_DIR.parent

try:  # optional: load ANTHROPIC_API_KEY etc. from a repo-root .env if present
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from buy_or_wait.data import DataError, canonical_content_sha256, file_sha256, load_dataset  # noqa: E402
from evaluation import metrics  # noqa: E402
from evaluation.labels import load_labels, sample_exposure_note  # noqa: E402
from main import _build_assist_config, predict_one  # noqa: E402
from evaluation.splits import (  # noqa: E402
    MANIFEST_PATH,
    SplitError,
    ensure_split,
    manifest_fingerprint,
)

DEFAULT_DATASET = REPO_ROOT / "dataset"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buy-or-wait-eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("dev", "report"), default=None,
                        help="which frozen subset to score")
    parser.add_argument("--mode", choices=("deterministic", "assisted"), default="deterministic",
                        help="system under test")
    parser.add_argument("--compare-baseline", action="store_true",
                        help="score the deterministic baseline alongside the selected mode")
    parser.add_argument("--show-split", action="store_true",
                        help="print the frozen split manifest and exit")
    parser.add_argument("--verbose", action="store_true",
                        help="show why each mismatched candidate was rejected")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        data = load_dataset(args.dataset)
    except DataError as exc:
        print(f"DATASET ERROR\n{exc}", file=sys.stderr)
        return 1

    sample_path = args.dataset / "sample_requests.csv"
    if not sample_path.exists():
        print("sample_requests.csv is required for evaluation", file=sys.stderr)
        return 1

    try:
        split = ensure_split(
            [r.request_id for r in data.sample_requests],
            canonical_content_sha256(sample_path),
            sample_sha256_raw=file_sha256(sample_path),
        )
        split.assert_disjoint()
    except SplitError as exc:
        print(f"SPLIT ERROR\n{exc}", file=sys.stderr)
        return 1

    labels = load_labels(sample_path)
    missing = sorted(set(split.dev + split.report) - set(labels))
    if missing:
        print(f"SPLIT ERROR\nlabels missing for {missing}", file=sys.stderr)
        return 1

    subset = args.split
    rows = split.subset(subset) if subset else ()

    print("============== EVALUATION AUDIT ==============")
    print(f"script            : code/evaluation/main.py")
    print(f"dataset           : {args.dataset}")
    print(f"labelled source   : sample_requests.csv ({len(data.sample_requests)} rows)")
    print(f"split manifest    : {MANIFEST_PATH}")
    print(f"split fingerprint : {manifest_fingerprint(split)}  (v{split.version}, {split.algorithm})")
    print(f"development subset: {len(split.dev)} rows  -- tuning only, excluded from reported metrics")
    print(f"reporting subset  : {len(split.report)} rows")
    print(f"disjoint check    : PASS")
    print(f"selected subset   : {subset or '(none -- manifest display only)'}"
          f"{f' [{len(rows)} rows]' if subset else ''}")
    print(f"system under test : {args.mode}")
    print(f"baseline compare  : {'yes' if args.compare_baseline else 'no'}")
    print(f"exposure          : {sample_exposure_note()}")
    print("==============================================")

    if args.show_split or subset is None:
        print(f"\ndevelopment ({len(split.dev)}): {', '.join(split.dev)}")
        print(f"reporting   ({len(split.report)}): {', '.join(split.report)}")
        if subset is None and not args.show_split:
            print("\nPass --split dev or --split report to score a subset.")
        return 0

    assist_config = None
    if args.mode == "assisted":
        assist_config = _build_assist_config(args.dataset)
        print(f"assisted mode provider status: "
              f"{'unavailable (no API key/package)' if assist_config.provider is None else 'configured'}")
        print(f"assisted mode full-run budget: {assist_config.ledger.full_run_call_budget} calls, "
              f"{assist_config.ledger.full_run_token_budget} tokens")

    result = score(data, rows, labels, mode=args.mode, assist_config=assist_config,
                  verbose=args.verbose, label="ASSISTED" if args.mode == "assisted" else "DETERMINISTIC")

    if args.compare_baseline and args.mode == "assisted":
        print("\n===== BASELINE (deterministic, no model calls) FOR COMPARISON =====")
        score(data, rows, labels, mode="deterministic", assist_config=None,
             verbose=args.verbose, label="BASELINE")

    return result


def score(data, request_ids, labels, *, mode: str = "deterministic",
         assist_config=None, verbose: bool = False, label: str = "RESULTS") -> int:
    """Score `mode` (deterministic or assisted) against labels for `request_ids`.

    Calls `main.predict_one` -- the same per-row path `main.py` publishes from
    -- so a scored row and a submitted row can never diverge in how they were
    produced.
    """
    statuses: list[tuple[str, str]] = []
    methods: list[tuple[str, str]] = []
    amounts: list[tuple[str, str, str]] = []
    plans: list[tuple[str, str]] = []
    dates: list[tuple[str, str]] = []
    degraded = 0
    crashed = 0
    mismatches: list[str] = []

    for request_id in request_ids:
        result = predict_one(data, request_id, mode=mode, assist_config=assist_config)
        row, decision = result["row"], result["decision"]
        gold = labels[request_id]
        currency = data.profiles_by_user[data.requests_by_id[request_id].user_id].home_currency

        statuses.append((row["affordability_status"], gold.affordability_status))
        methods.append((row["recommended_payment_method"], gold.recommended_payment_method))
        amounts.append((currency, row["amount_safe_to_pay"], gold.amount_safe_to_pay))
        plans.append((row["payment_plan"], gold.payment_plan))
        dates.append((row["earliest_date_for_full_payment"], gold.earliest_date_for_full_payment))
        if result["crashed"]:
            crashed += 1
        elif decision.degraded:
            degraded += 1
        if row["recommended_payment_method"] != gold.recommended_payment_method:
            mismatches.append(
                f"  {request_id:12} pred={row['recommended_payment_method']:16} "
                f"gold={gold.recommended_payment_method:16} "
                f"safe={row['amount_safe_to_pay']} gold_safe={gold.amount_safe_to_pay}"
            )
            if verbose and decision.rejected:
                mismatches.append(f"               rejected: {decision.rejected[0]}")

    correct_status, total = metrics.accuracy(statuses)
    correct_method, _ = metrics.accuracy(methods)
    plan_exact, _ = metrics.exact_match(plans)
    date_exact, _ = metrics.exact_match(dates)
    mean_days, compared, both_empty, emptiness_mismatch = metrics.date_day_error(dates)

    print(f"\n------------------ {label} ------------------")
    print(f"affordability_status      : {correct_status}/{total}  "
          f"macro-F1 {metrics.macro_f1(statuses):.3f}")
    print(f"recommended_payment_method: {correct_method}/{total}  "
          f"macro-F1 {metrics.macro_f1(methods):.3f}")
    print(f"payment_plan (exact)      : {plan_exact}/{total}")
    print(f"earliest_date (exact)     : {date_exact}/{total}  "
          f"(mean |days| {mean_days:.1f} over {compared}; both-empty {both_empty}; "
          f"emptiness disagreement {emptiness_mismatch})")
    print(f"degraded rows             : {degraded}/{total}  (counted as wrong, never dropped)")
    if crashed:
        print(f"unhandled row errors      : {crashed}/{total}  (counted as wrong, never dropped)")

    print("\namount_safe_to_pay by currency (never pooled):")
    for currency, stats in metrics.amount_error_by_currency(amounts).items():
        print(f"  {currency}  n={stats['n']:<3} exact={stats['exact']}/{stats['n']} "
              f"MAE={stats['mae']:.2f}  normalized MAE={stats['normalized_mae']:.3f}")

    print(f"\nstatus confusion (gold->pred): {dict(metrics.confusion(statuses))}")
    print(f"method confusion (gold->pred): {dict(metrics.confusion(methods))}")
    if mismatches:
        print(f"\n---------------- {label} METHOD MISMATCHES ----------------")
        for line in mismatches:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
