"""Buy or Wait? -- AI-powered financial affordability agent.

Usage:
    python main.py                          # every request in dataset/requests.csv
    python main.py --limit 10               # first 10 requests
    python main.py --request-id request_42   # one request
    python main.py --samples                # run the 25 labelled samples instead
    python main.py --resume                 # continue from the checkpoint
    python main.py --no-llm                 # deterministic engine only, no API calls

Requires GROQ_API_KEY in the environment or in .env at the repository root
(not needed with --no-llm).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from config import CODE_DIR, OUTPUT_COLUMNS, REPO_ROOT, Settings, get_settings
from tools.balance_forecaster import ForecastConfig
from tools.dataset_loader import DatasetLoader
from tools.decision_engine import decide
from tools.evidence_cache import EvidenceCache
from tools.exchange_converter import ExchangeConverter
from tools.image_extractor import ImageExtractor
from tools.message_resolver import MessageResolver
from tools.retriever import SampleRetriever, SeriesMatcher
from tools.safety_gate import SafetyGate
from utils.llm_client import LLMClient
from utils.logger import bind_request, setup_logger
from utils.token_tracker import TokenTracker
from validators.schemas import AgentOutput, RequestRow


def checkpoint_path(samples: bool, engine: str) -> Path:
    """A separate checkpoint per run scope *and* per engine.

    Scope alone is not enough. A deterministic scoring pass over the samples
    shares request ids with an agent pass over the same samples, and since
    load_checkpoint keeps the last entry per id, sharing one file lets the
    cheaper run silently overwrite the better one on the next --resume.
    """
    scope = "samples" if samples else "requests"
    return CODE_DIR / ".cache" / f"checkpoint_{scope}_{engine}.jsonl"


def engine_name(args: argparse.Namespace) -> str:
    if args.no_llm:
        return "deterministic"
    return "lean" if args.lean else "agent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=None, help="process the first N")
    parser.add_argument("--request-id", type=str, default=None, help="one request only")
    parser.add_argument("--samples", action="store_true", help="run sample_requests.csv")
    parser.add_argument("--resume", action="store_true", help="skip checkpointed rows")
    parser.add_argument("--no-llm", action="store_true", help="deterministic only")
    parser.add_argument(
        "--lean",
        action="store_true",
        help=(
            "resolve evidence then decide deterministically, skipping the "
            "orchestrator loop. Roughly a fifth of the tokens, and keeps the "
            "message-resolution accuracy gain; needed because Groq caps tokens "
            "per day per model at 200k."
        ),
    )
    parser.add_argument("--no-rag", action="store_true", help="skip few-shot retrieval")
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help=(
            "requests processed concurrently (default 3). Throughput comes from "
            "the orchestrator pool's separate per-model token buckets, so more "
            "workers than pool models mostly adds waiting."
        ),
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help=(
            "with --lean, reuse evidence already recorded in the cache instead "
            "of calling the resolver again. Zero tokens; use to re-run rows "
            "after a fix to the deterministic logic."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=None, help="override the output path"
    )
    return parser.parse_args()


def select_requests(loader: DatasetLoader, args: argparse.Namespace) -> list[RequestRow]:
    if args.samples:
        requests = [loader._request(row) for row in loader.sample_requests]
    else:
        requests = list(loader.requests)
    if args.request_id:
        requests = [r for r in requests if r.request_id == args.request_id]
    if args.limit:
        requests = requests[: args.limit]
    return requests


def load_checkpoint(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    done: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("request_id"):
                done[row["request_id"]] = row
    return done


def append_checkpoint(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def write_output(rows: list[dict[str, str]], paths: tuple[Path, ...]) -> None:
    """Write output.csv in the required column order, one row per request.

    Written via a temporary file and renamed into place, because this is called
    repeatedly while the run progresses and anyone reading the file -- an editor,
    evaluation/main.py -- must never catch it half-written.
    """
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_COLUMNS))
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)


def resolve_output_paths(
    args: argparse.Namespace, settings: Settings | None
) -> tuple[Path, ...]:
    """Where predictions are written: the submission file and the template."""
    if args.output:
        return (args.output,)
    if settings is not None:
        return settings.output_paths
    return (REPO_ROOT / "output.csv", REPO_ROOT / "dataset" / "output.csv")


def collect_evidence(
    loader: DatasetLoader, request: RequestRow
) -> tuple[list, list, list, list]:
    """The events, messages, images and payment options relevant to one request."""
    events = loader.events_by_user.get(request.user_id, [])
    options = loader.options_by_request.get(request.request_id, [])
    messages = [
        m
        for m in loader.messages_by_user.get(request.user_id, [])
        if m.request_id in (None, request.request_id)
    ]
    # An image is relevant when it belongs to this request, or when it is the
    # receipt for one of this user's events whose amount is blank.
    by_event = loader.images_by_event
    images = [
        ref
        for ref in loader.images_by_user.get(request.user_id, [])
        if ref.request_id in (None, request.request_id)
    ]
    images += [
        by_event[event.event_id]
        for event in events
        if event.amount is None
        and event.event_id in by_event
        and by_event[event.event_id] not in images
    ]
    return events, messages, images, options


def build_agent(settings: Settings, tracker: TokenTracker, loader: DatasetLoader,
                converter: ExchangeConverter, use_rag: bool, lean: bool,
                replay: bool, logger):
    """Assemble the orchestrator, or the lean evidence-only path."""
    from agents.orchestrator import OrchestratorAgent

    client = LLMClient(settings, tracker)
    evidence = EvidenceCache(settings.evidence_cache_path)
    gate = SafetyGate(client, settings.safety_model)
    extractor = ImageExtractor(settings, client, converter)

    if lean:
        from agents.lean_runner import LeanRunner

        logger.info(
            "lean mode: evidence tools plus the deterministic engine",
            resolver_pool=list(settings.resolver_pool),
            vision=settings.vision_model,
        )
        return LeanRunner(
            settings=settings,
            converter=converter,
            extractor=extractor,
            resolver=MessageResolver(settings, client, None),
            gate=gate,
            evidence=evidence,
            forecast_config=ForecastConfig(),
            replay_only=replay,
            logger=logger,
        )

    retriever = None
    matcher = None
    if use_rag:
        logger.info("building sample index for few-shot retrieval")
        retriever = SampleRetriever(settings.embedding_model, loader.sample_requests)
        matcher = SeriesMatcher(settings.embedding_model, settings.similarity_threshold)
    return OrchestratorAgent(
        settings=settings,
        client=client,
        tracker=tracker,
        converter=converter,
        extractor=extractor,
        resolver=MessageResolver(settings, client, matcher),
        gate=gate,
        retriever=retriever,
        forecast_config=ForecastConfig(),
        evidence=evidence,
        logger=logger,
    )


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    logger = setup_logger(args.verbose)

    loader = DatasetLoader(REPO_ROOT / "dataset")
    converter = ExchangeConverter(loader.exchange_rates)
    requests = select_requests(loader, args)
    logger.info("selected requests", count=len(requests), deterministic=args.no_llm)

    # Persisted so a resumed or segmented run still reports the whole of the
    # usage that produced output.csv.
    tracker = TokenTracker(ledger_path=CODE_DIR / ".cache" / "usage_ledger.json")
    agent = None
    settings = None
    if not args.no_llm:
        settings = get_settings()
        agent = build_agent(
            settings, tracker, loader, converter,
            not args.no_rag and not args.lean, args.lean, args.replay, logger,
        )

    checkpoint = checkpoint_path(args.samples, engine_name(args))
    done = load_checkpoint(checkpoint) if args.resume else {}

    # Groq's token limits are per model, and the orchestrator alternates across
    # a pool of them, so requests on different models do not compete for the
    # same bucket. Running a few at once therefore converts idle pacing time
    # into throughput; it does not raise the rate at which any one model is hit.
    pending = [(i, r) for i, r in enumerate(requests) if r.request_id not in done]
    results: dict[int, dict[str, str]] = {
        i: done[r.request_id] for i, r in enumerate(requests) if r.request_id in done
    }
    write_lock = threading.Lock()
    completed = len(results)
    output_paths = resolve_output_paths(args, settings)
    if results:
        # Show resumed rows straight away rather than waiting for the first new
        # completion to trigger a flush.
        write_output([results[i] for i in sorted(results)], output_paths)

    def handle(index: int, request: RequestRow) -> tuple[int, dict[str, str]]:
        bind_request(request.request_id)
        profile = loader.profiles.get(request.user_id)
        if profile is None:
            logger.warning("no profile; emitting a conservative row")
            return index, _fallback_row(request)
        bundle_parts = collect_evidence(loader, request)
        output = _process(agent, request, profile, *bundle_parts, converter, logger)
        return index, output.to_row()

    workers = 1 if args.no_llm else max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(handle, i, r) for i, r in pending]
        for future in as_completed(futures):
            index, row = future.result()
            with write_lock:
                results[index] = row
                append_checkpoint(checkpoint, row)
                completed += 1
                # Flush after every completion so the output file fills in as the
                # run progresses instead of appearing only at the end. The rows
                # written are always in dataset order, never completion order.
                write_output([results[i] for i in sorted(results)], output_paths)
                if completed % 10 == 0 or completed == len(requests):
                    logger.info(
                        "progress",
                        done=f"{completed}/{len(requests)}",
                        usage=tracker.summary_line(),
                    )

    rows = [results[i] for i in sorted(results)]
    write_output(rows, output_paths)
    logger.info("wrote output", rows=len(rows), paths=[str(p) for p in output_paths])

    if not args.no_llm and settings is not None:
        tracker.write_usage_report(settings.usage_report_path, len(rows))
        logger.info("wrote usage report", path=str(settings.usage_report_path))
    logger.info("done", usage=tracker.summary_line())


def _process(agent, request, profile, events, messages, images, options, converter, logger):
    """Run one request through the agent, falling back to the engine on error."""
    from agents.orchestrator import RequestBundle
    from tools.balance_forecaster import build_forecast_model

    if agent is not None:
        bundle = RequestBundle(
            request=request,
            profile=profile,
            events=events,
            messages=agent.gate.screen(messages, request.request_id),
            images=images,
            options=options,
        )
        return agent.run(bundle)

    model = build_forecast_model(
        profile, events, request.request_date, converter, ForecastConfig()
    )
    decision = decide(request, profile, options, model, events)
    output = decision.output
    if not output.decision_explanation:
        from agents.orchestrator import RequestBundle, _template_explanation

        bundle = RequestBundle(request, profile, events, messages, images, options)
        output = output.model_copy(
            update={"decision_explanation": _template_explanation(bundle, output)}
        )
    return output


def _fallback_row(request: RequestRow) -> dict[str, str]:
    """A valid, conservative row for a request we cannot analyse at all."""
    return AgentOutput(
        request_id=request.request_id,
        amount_safe_to_pay=0.0,
        affordability_status="not_affordable",
        recommended_payment_method="not_recommended",
        payment_plan="none",
        earliest_date_for_full_payment="",
        spending_changes_needed="none",
        decision_explanation=(
            "No financial profile is available for this account, so no payment "
            "can be confirmed as safe."
        ),
        requested_amount=request.requested_amount,
    ).to_row()


if __name__ == "__main__":
    main()
