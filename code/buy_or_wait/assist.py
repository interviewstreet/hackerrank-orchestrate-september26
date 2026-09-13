"""Assisted-mode orchestration: wires `evidence.py` and `model.py` around the
unmodified deterministic core (`main.decide_one`).

The contract this module exists to keep: assisted mode can only ever *repair*
an unknown `FinancialEvent.amount` (or apply an explicit amendment/
cancellation) with a validated, cited fact -- it never talks to
`state.py`/`recurrence.py`/`forecast.py`/`planner.py`/`validation.py`
directly, and it never crashes a row. Any failure anywhere in extraction --
no provider configured, a timeout, a budget exceeded, an unexpected
exception, or every fact being rejected -- must fall back to exactly the
deterministic result for that request, never a partially-applied or
degraded-in-a-new-way one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import model as model_module
from .data import DataSet
from .evidence import (
    ExtractedFact,
    ProposedFact,
    RowTrace,
    apply_facts_to_events,
    available_candidates,
    resolve_conflicts,
    resolve_fact,
    retrieve_candidates,
)
from .schema import RequestContext


@dataclass(frozen=True)
class AssistConfig:
    """Everything assisted mode needs beyond the deterministic engine.

    `provider is None` (no credentials, package missing, or explicitly
    disabled) is not an error condition -- it is the documented fail-closed
    path, and every request simply runs deterministic-only with a trace that
    records why.
    """

    provider: Optional[model_module.Provider]
    caller: model_module.BoundedCaller = field(default_factory=model_module.BoundedCaller)
    ledger: model_module.UsageLedger = field(default_factory=model_module.UsageLedger)
    cache: Optional[model_module.ExtractionCache] = None
    max_image_bytes: int = 2_000_000


def provider_status(config: Optional[AssistConfig]) -> str:
    if config is None or config.provider is None:
        return "unavailable"
    return "configured"


def _load_source_text(context: RequestContext, ref_id: str) -> Optional[tuple[str, str, str]]:
    """Return (kind, text, image_bytes_placeholder) content for one available
    message/image id, or `None` for a source kind this call does not build
    text for (structured events are cited but not sent as prose)."""
    for message in context.messages:
        if message.message_id == ref_id:
            return ("message", message.message_text, None)
    return None


def build_sources(
    context: RequestContext, dataset: DataSet, candidates: dict, *, max_image_bytes: int
) -> tuple[model_module.Source, ...]:
    """Render the available candidate registry as provider input.

    Images are read through `dataset.media_path` -- the sole sanctioned,
    path-traversal-safe resolver -- and skipped (not fabricated as empty)
    when the file is missing or larger than the configured bound.
    """
    sources: list[model_module.Source] = []
    for ref_id, ref in candidates.items():
        if ref.kind == "message":
            found = _load_source_text(context, ref_id)
            if found:
                _, text, _ = found
                sources.append((ref_id, "message", text, None))
        elif ref.kind == "image":
            for image in context.images:
                if image.image_id == ref_id:
                    path = dataset.media_path(image)
                    if path.exists() and path.stat().st_size <= max_image_bytes:
                        sources.append((ref_id, "image", "", path.read_bytes()))
                    break
    return tuple(sources)


def extract_facts(
    context: RequestContext, dataset: DataSet, config: Optional[AssistConfig]
) -> tuple[RowTrace, tuple[ExtractedFact, ...]]:
    """Run the full request-scoped extraction pipeline for one request.

    Always returns a `RowTrace` (never raises): the caller folds `accepted`
    facts into a patched context and otherwise proceeds exactly as
    deterministic mode would.
    """
    events_by_id = {e.event_id: e for e in context.events}
    refs = retrieve_candidates(context, events_by_id)
    candidates = available_candidates(refs)
    retrieved_ids = tuple(sorted(candidates))

    if config is None or config.provider is None:
        return RowTrace(context.request.request_id, retrieved_ids,
                        provider_status="unavailable"), ()

    unresolved = tuple(e.event_id for e in context.events if e.amount_is_unknown)
    if not unresolved:
        return RowTrace(context.request.request_id, retrieved_ids,
                        provider_status="skipped: no unresolved amounts"), ()

    try:
        sources = build_sources(context, dataset, candidates, max_image_bytes=config.max_image_bytes)
        if not sources:
            return RowTrace(context.request.request_id, retrieved_ids,
                            provider_status="skipped: no retrievable sources"), ()

        request = model_module.ExtractionRequest(
            request_id=context.request.request_id, user_id=context.request.user_id,
            model_id=config.provider.model_id, sources=sources, unresolved_targets=unresolved,
        )

        cache_hit = False
        key = model_module.cache_key(request, model_id=config.provider.model_id)
        proposed: tuple[ProposedFact, ...]
        usage_dict: Optional[dict] = None
        if config.cache is not None:
            cached = config.cache.get(key)
            if cached is not None:
                cache_hit = True
                proposed = tuple(model_module.fact_from_json(f) for f in cached["facts"])
                usage_dict = cached["usage"]
        if not cache_hit:
            result = config.caller.call(config.provider, request, config.ledger)
            proposed = result.facts
            usage_dict = result.usage.as_dict()
            if config.cache is not None:
                config.cache.put(key, facts=proposed, usage=result.usage,
                                 model_id=config.provider.model_id)

        resolved = tuple(
            resolve_fact(p, candidates=candidates, context=context, events_by_id=events_by_id,
                        rates_by_key=dataset.rates_by_key)
            for p in proposed
        )
        final_facts = resolve_conflicts(resolved, context)
        accepted = tuple(f for f in final_facts if f.status == "accepted")
        rejected = tuple(f for f in final_facts if f.status != "accepted")

        return RowTrace(
            context.request.request_id, retrieved_ids, accepted=accepted, rejected=rejected,
            provider_status="ok", usage=usage_dict, cache_hit=cache_hit,
        ), accepted
    except model_module.ProviderError as exc:
        return RowTrace(
            context.request.request_id, retrieved_ids, provider_status=f"failed: {exc}",
            notes=(f"{type(exc).__name__}: {exc}",),
        ), ()
    except Exception as exc:  # noqa: BLE001 - one row's extraction must never crash the run
        return RowTrace(
            context.request.request_id, retrieved_ids, provider_status=f"error: {type(exc).__name__}",
            notes=(f"unhandled: {exc}",),
        ), ()
