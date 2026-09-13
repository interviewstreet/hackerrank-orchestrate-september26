"""Buy or Wait? -- command line entry point.

    python code/main.py                      # audit the dataset (default)
    python code/main.py --mode audit
    python code/main.py --mode deterministic --out output.csv
    python code/main.py --mode assisted --out output.csv

Milestone status (see docs/IMPLEMENTATION_STATUS.md): M0 contract/loaders/audit,
M1 deterministic financial core, M3 payment plans and spending changes, M2
evidence extraction (assisted mode). deterministic mode never calls a model
provider. assisted mode extracts and validates evidence facts, then runs the
same deterministic core on a context with any resolved amounts patched in; it
falls back to the deterministic result whenever no provider is configured or
extraction is unavailable/fails.

Exit codes: 0 success, 1 dataset audit errors.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `buy_or_wait` importable
REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # optional: load ANTHROPIC_API_KEY etc. from a repo-root .env if present
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from buy_or_wait import assist  # noqa: E402
from buy_or_wait import forecast as forecast_module  # noqa: E402
from buy_or_wait import model as model_module  # noqa: E402
from buy_or_wait import planner, recurrence, state, validation  # noqa: E402
from buy_or_wait.audit import audit_dataset, errors  # noqa: E402
from buy_or_wait.data import DataError, load_dataset  # noqa: E402
from buy_or_wait.evidence import apply_facts_to_events, citation_note  # noqa: E402
from buy_or_wait.output import PublishError, publish, to_row  # noqa: E402
from buy_or_wait.schema import RequestContext  # noqa: E402

DEFAULT_DATASET = REPO_ROOT / "dataset"
DEFAULT_OUTPUT = REPO_ROOT / "output.csv"

# Full-run provider budgets for assisted mode. These are engineering ceilings
# to bound cost/blast-radius on a misbehaving run (e.g. many more unresolved
# amounts than expected), not a measured or promised spend -- per
# docs/IMPLEMENTATION_PLAN.md section 6, "engineering defaults to validate,
# not measured performance or permission to incur costs now." `--mode
# deterministic` never constructs a `UsageLedger` and is unaffected.
DEFAULT_FULL_RUN_CALL_BUDGET = 60
DEFAULT_FULL_RUN_TOKEN_BUDGET = 300_000
ENV_MAX_CALLS = "BUY_OR_WAIT_MAX_CALLS"
ENV_MAX_TOKENS = "BUY_OR_WAIT_MAX_TOKENS"


def _resolve_budget(cli_value: int | None, env_name: str, default: int) -> int:
    """CLI flag wins over the environment variable, which wins over the
    documented default. Never returns `None` -- assisted mode must always
    run under an explicit full-run ceiling."""
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_name)
    if env_value:
        return int(env_value)
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buy-or-wait", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET,
                        help="dataset directory (default: <repo>/dataset)")
    parser.add_argument("--mode", choices=("audit", "deterministic", "assisted"), default="audit",
                        help="audit: validate the dataset only. deterministic: no model calls. "
                             "assisted: deterministic engine plus evidence extraction.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT,
                        help="prediction output path (default: <repo>/output.csv)")
    parser.add_argument("--limit", type=int, default=None,
                        help="process only the first N requests (smoke runs)")
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    parser.add_argument("--max-calls", type=int, default=None,
                        help="assisted mode: full-run provider call ceiling "
                             f"(default: {DEFAULT_FULL_RUN_CALL_BUDGET}, or "
                             f"${ENV_MAX_CALLS} if set)")
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="assisted mode: full-run input+output token ceiling "
                             f"(default: {DEFAULT_FULL_RUN_TOKEN_BUDGET}, or "
                             f"${ENV_MAX_TOKENS} if set)")
    return parser


def run_audit(dataset_dir: Path, *, quiet: bool = False) -> int:
    try:
        data = load_dataset(dataset_dir)
    except DataError as exc:
        print(f"DATASET ERROR\n{exc}", file=sys.stderr)
        return 1

    findings = audit_dataset(data)
    failures = errors(findings)

    if not quiet:
        print("=============== DATASET AUDIT ===============")
        print(f"dataset            : {data.dataset_dir}")
        print(f"evaluation requests: {len(data.requests)}")
        print(f"public samples     : {len(data.sample_requests)}")
        print(f"profiles           : {len(data.profiles)}")
        print(f"financial events   : {len(data.events)}  "
              f"(unknown amounts: {sum(1 for e in data.events if e.amount_is_unknown)})")
        print(f"payment options    : {len(data.payment_options)}")
        print(f"messages / images  : {len(data.messages)} / {len(data.images)}")
        print(f"exchange rates     : {len(data.exchange_rates)}")
        print("--- input file hashes (sha256, first 16) ---")
        for name, digest in sorted(data.manifest.items()):
            print(f"  {name:32} {digest[:16]}")
        print(f"--- media content hashes ({len(data.media_manifest)} files) ---")
        for name, digest in sorted(data.media_manifest.items()):
            print(f"  {name:32} {digest[:16]}")
        print("=============================================")
        for finding in findings:
            print(finding)

    print(f"\naudit: {len(findings)} finding(s), {len(failures)} error(s)")
    return 1 if failures else 0


def decide_one(context: RequestContext, rates) -> tuple[planner.Decision, list[validation.GateFailure]]:
    """Run the deterministic core for one request and gate the result.

    This is the core routing function: every request takes exactly this path.
    Cash state -> recurrence -> forecast -> candidates -> gate. A row that fails
    the gate is replaced by the conservative fallback rather than published.
    """
    request, profile = context.request, context.profile

    cash = state.reconstruct(context.events, profile, request.request_date, rates)
    series = recurrence.detect(context.events, profile, request.request_date, rates)
    forecast = forecast_module.build(cash, series, request.request_date)

    decision = planner.choose(request, profile, forecast, series, context.payment_options)
    failures = validation.check(decision, request, profile, forecast,
                                context.payment_options, context.events, series)
    if failures:
        decision = validation.conservative_fallback(
            request, "failed quality gate: " + "; ".join(str(f) for f in failures)
        )
        # The fallback must itself pass, or we have a bug rather than a bad row.
        residual = validation.check(decision, request, profile, forecast)
        if residual:
            raise RuntimeError(
                f"{request.request_id}: conservative fallback failed validation: {residual}"
            )
    return decision, failures


def _build_provider() -> model_module.Provider | None:
    """Construct the real provider only if it is actually usable.

    Any absence -- no API key, no `anthropic` package, any other
    configuration problem -- must be a quiet `None`, never a crash: assisted
    mode always has a deterministic-only fallback available.
    """
    try:
        return model_module.AnthropicProvider()
    except model_module.ProviderUnavailable:
        return None


def _build_assist_config(dataset_dir: Path, *, max_calls: int = DEFAULT_FULL_RUN_CALL_BUDGET,
                         max_tokens: int = DEFAULT_FULL_RUN_TOKEN_BUDGET) -> assist.AssistConfig:
    provider = _build_provider()
    cache_path = dataset_dir.parent / "code" / "evaluation" / "extraction_cache.json"
    cache = model_module.ExtractionCache(path=cache_path)
    cache.load()
    ledger = model_module.UsageLedger(full_run_call_budget=max_calls,
                                      full_run_token_budget=max_tokens)
    return assist.AssistConfig(provider=provider, cache=cache, ledger=ledger)


def predict_one(data, request_id: str, *, mode: str,
                assist_config: "assist.AssistConfig | None" = None) -> dict:
    """Produce one output row plus bookkeeping for `request_id`.

    Shared by `run_predictions` (the CLI) and the evaluation harness, so
    scoring assisted mode exercises the identical row-level path -- including
    per-row failure isolation -- rather than a second, divergent copy of it.
    Returns a dict with keys: row, decision, failures, trace (or None),
    accepted_facts (always a tuple), crashed (bool), error (str or None).
    """
    request = data.requests_by_id[request_id]
    trace = None
    accepted_facts: tuple = ()
    try:
        context = data.context_for(request_id)
        if mode == "assisted":
            trace, accepted_facts = assist.extract_facts(context, data, assist_config)
            if accepted_facts:
                patched_events = apply_facts_to_events(context.events, accepted_facts)
                context = dataclasses.replace(context, events=patched_events)
        decision, failures = decide_one(context, data.rates_by_key)
        row = to_row(decision, context.profile.home_currency, request.requested_amount,
                     context.profile.minimum_balance_to_keep)
        if mode == "assisted" and accepted_facts:
            note = citation_note(trace)
            if note:
                row["decision_explanation"] = f"{row['decision_explanation']} {note}"
        return {"row": row, "decision": decision, "failures": failures, "trace": trace,
                "accepted_facts": accepted_facts, "crashed": False, "error": None}
    except Exception as exc:  # noqa: BLE001 - one row must not end the run
        error = f"{type(exc).__name__}: {exc}"
        decision = validation.conservative_fallback(
            request, f"unhandled error: {type(exc).__name__}")
        profile = data.profiles_by_user[request.user_id]
        row = to_row(decision, profile.home_currency, request.requested_amount,
                     profile.minimum_balance_to_keep)
        return {"row": row, "decision": decision, "failures": (), "trace": trace,
                "accepted_facts": accepted_facts, "crashed": True, "error": error}


def run_predictions(dataset_dir: Path, out_path: Path, *, mode: str,
                    limit: int | None, quiet: bool,
                    max_calls: int = DEFAULT_FULL_RUN_CALL_BUDGET,
                    max_tokens: int = DEFAULT_FULL_RUN_TOKEN_BUDGET) -> int:
    data = load_dataset(dataset_dir)
    requests = list(data.requests)[:limit] if limit else list(data.requests)

    assist_config: assist.AssistConfig | None = None
    traces: list[dict] = []
    if mode == "assisted":
        assist_config = _build_assist_config(dataset_dir, max_calls=max_calls, max_tokens=max_tokens)
        if not quiet:
            print(f"assisted mode provider status: {assist.provider_status(assist_config)}")
            print(f"assisted mode full-run budget: {max_calls} calls, {max_tokens} tokens")

    rows: list[dict] = []
    gate_failures: list[str] = []
    degraded: list[str] = []
    crashed: list[str] = []
    methods: dict[str, int] = {}

    for request in requests:
        result = predict_one(data, request.request_id, mode=mode, assist_config=assist_config)
        row, decision = result["row"], result["decision"]
        if result["trace"] is not None:
            traces.append(result["trace"].to_json())
        if result["crashed"]:
            crashed.append(f"{request.request_id}: {result['error']}")
        else:
            if result["failures"]:
                gate_failures.append(f"{request.request_id}: {result['failures'][0]}")
            if decision.degraded:
                degraded.append(f"{request.request_id}: {decision.degradation_reason}")
        methods[decision.recommended_payment_method] = (
            methods.get(decision.recommended_payment_method, 0) + 1)
        rows.append(row)
        if not quiet:
            print(f"  {request.request_id:14} {decision.affordability_status:22} "
                  f"{decision.recommended_payment_method}")

    if crashed:
        # An unhandled programming error is not the same as expected-unavailable
        # evidence (which `predict_one` already degrades to the conservative
        # fallback without raising). Publishing over a good prior `output.csv`
        # with a run that hit a real bug would silently discard a working
        # submission artifact, so the previous file is left untouched and the
        # run is reported as failed instead.
        print(f"\nrefusing to publish: {len(crashed)} row(s) hit an unhandled error; "
              f"{out_path} left unchanged", file=sys.stderr)
        for item in crashed[:10]:
            print(f"  UNHANDLED: {item}", file=sys.stderr)
        return 1

    publish(rows, out_path, [r.request_id for r in requests], dataset_dir=dataset_dir)

    if mode == "assisted" and assist_config is not None:
        if assist_config.cache is not None:
            assist_config.cache.save()
        run_dir = Path(__file__).resolve().parent / "evaluation" / "runs" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        run_dir.mkdir(parents=True, exist_ok=True)
        trace_path = run_dir / "trace.jsonl"
        with trace_path.open("w", encoding="utf-8") as handle:
            for trace in traces:
                handle.write(json.dumps(trace) + "\n")
        usage_path = run_dir / "usage.json"
        usage_path.write_text(json.dumps({
            "full_run_call_budget": assist_config.ledger.full_run_call_budget,
            "full_run_token_budget": assist_config.ledger.full_run_token_budget,
            "total": assist_config.ledger.total.as_dict(),
            "per_request": {k: v.as_dict() for k, v in assist_config.ledger.per_request.items()},
        }, indent=2), encoding="utf-8")
        print(f"assisted-mode trace: {trace_path}")

    print(f"\nwrote {len(rows)} rows to {out_path}")
    print("method distribution: " + ", ".join(f"{k}={v}" for k, v in sorted(methods.items())))
    print(f"degraded rows      : {len(degraded)}")
    print(f"gate failures      : {len(gate_failures)}")
    for item in gate_failures[:10]:
        print(f"  GATE FAILURE: {item}", file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    status = run_audit(args.dataset, quiet=args.quiet)
    if args.mode == "audit":
        return status
    if status != 0:
        print("refusing to predict on a dataset that failed its audit", file=sys.stderr)
        return status

    max_calls = _resolve_budget(args.max_calls, ENV_MAX_CALLS, DEFAULT_FULL_RUN_CALL_BUDGET)
    max_tokens = _resolve_budget(args.max_tokens, ENV_MAX_TOKENS, DEFAULT_FULL_RUN_TOKEN_BUDGET)
    try:
        return run_predictions(args.dataset, args.out, mode=args.mode,
                               limit=args.limit, quiet=args.quiet,
                               max_calls=max_calls, max_tokens=max_tokens)
    except (DataError, PublishError) as exc:
        print(f"RUN FAILED\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
