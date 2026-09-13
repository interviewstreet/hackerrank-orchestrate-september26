"""Bounded, cached, optional provider access for structured evidence extraction.

Nothing here decides money. A `Provider.extract()` call returns
`ProposedFact` objects (`evidence.py`), which are proposals only --
`evidence.resolve_fact` independently validates every one before anything
reaches the deterministic core. This module's job is purely operational:
one call wrapper with an explicit timeout, a monotonic per-row deadline,
bounded retries that never retry authentication/configuration failures, a
per-row and full-run token/call budget, and a content-hash cache.

No import here executes a network call at import time, and no test in
`code/tests/` requires an API key or network access: `FakeProvider` is the
offline stand-in every test uses. `AnthropicProvider` is isolated behind an
explicit environment variable and an optional import so that constructing it
without credentials fails closed (`ProviderUnavailable`) instead of raising an
import error the caller cannot handle.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from .evidence import ProposedFact

#: Bumped whenever the extraction policy text or the fact schema changes, so a
#: cached record from an earlier version can never be served silently.
PROMPT_VERSION = "extraction_v1"
SCHEMA_VERSION = "fact_v1"

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str = PROMPT_VERSION) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------- exceptions


class ProviderError(RuntimeError):
    """Base class for provider failures."""


class AuthError(ProviderError):
    """Credentials or configuration are wrong. Never retried."""


class TransientError(ProviderError):
    """Worth retrying: timeouts, rate limits, transient server errors."""


class ProviderUnavailable(ProviderError):
    """No usable provider is configured. Assisted mode must fail closed to
    the deterministic result, never crash the run."""


class BudgetExceeded(ProviderError):
    """A per-row or full-run call/token budget would be exceeded."""


# ------------------------------------------------------------------- types


#: One evidence source handed to the provider: (source_id, kind, text, image_bytes).
Source = tuple[str, str, str, Optional[bytes]]


@dataclass(frozen=True)
class ExtractionRequest:
    request_id: str
    user_id: str
    model_id: str
    sources: tuple[Source, ...]
    #: event_ids whose amount is currently unknown, for the prompt to target.
    unresolved_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.calls + other.calls,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    def as_dict(self) -> dict:
        return {
            "calls": self.calls, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True)
class ExtractionResult:
    facts: tuple[ProposedFact, ...]
    usage: Usage
    raw_text: str = ""


class Provider(Protocol):
    model_id: str

    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


# -------------------------------------------------------------- providers


@dataclass
class FakeProvider:
    """Deterministic offline stand-in for every test in `code/tests/`.

    `responses` maps `request_id` to an `ExtractionResult`, an `Exception`
    instance to raise, or a zero-arg callable returning either -- so a test
    can simulate a timeout, an auth failure, or a slow/flaky call without any
    real I/O or sleeping.
    """

    model_id: str = "fake-extractor-1"
    responses: dict = field(default_factory=dict)
    default: Optional[ExtractionResult] = None
    calls: list = field(default_factory=list)

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        self.calls.append(request.request_id)
        outcome = self.responses.get(request.request_id, self.default)
        if outcome is None:
            return ExtractionResult(facts=(), usage=Usage(calls=1, input_tokens=10, output_tokens=1))
        if callable(outcome) and not isinstance(outcome, ExtractionResult):
            outcome = outcome()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


_SYSTEM_PROMPT_CACHE: Optional[str] = None


def _system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        _SYSTEM_PROMPT_CACHE = load_prompt()
    return _SYSTEM_PROMPT_CACHE


_FACT_TOOL = {
    "name": "record_facts",
    "description": "Record proposed financial facts extracted from the supplied evidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "target_event_id": {"type": ["string", "null"]},
                        "target_scope": {"type": "string"},
                        "value": {"type": "string"},
                        "currency": {"type": ["string", "null"]},
                        "value_date": {"type": ["string", "null"]},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                        "source_span": {"type": "string"},
                    },
                    "required": ["field", "target_scope", "value", "source_ids"],
                },
            }
        },
        "required": ["facts"],
    },
}


class AnthropicProvider:
    """Real provider, isolated behind an explicit API key and optional import.

    Never constructed unless `ANTHROPIC_API_KEY` is set and the `anthropic`
    package is importable; both absences raise `ProviderUnavailable` so
    callers fail closed to the deterministic result instead of crashing.
    Per `AGENTS.md`/`CLAUDE.md`, no paid call is triggered by importing or
    constructing this class -- only by a caller explicitly invoking `extract`
    with credentials the participant has supplied.
    """

    def __init__(self, model_id: str = "claude-sonnet-5") -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic  # noqa: F401 -- optional dependency, imported lazily
        except ImportError as exc:
            raise ProviderUnavailable("the 'anthropic' package is not installed") from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model_id = model_id

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        anthropic = self._anthropic
        content = _build_message_content(request)
        try:
            response = self._client.messages.create(
                model=self.model_id,
                max_tokens=1024,
                system=_system_prompt(),
                tools=[_FACT_TOOL],
                tool_choice={"type": "tool", "name": "record_facts"},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise AuthError(str(exc)) from exc
        except (anthropic.APITimeoutError, anthropic.RateLimitError,
                anthropic.APIConnectionError) as exc:
            raise TransientError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and status >= 500:
                raise TransientError(str(exc)) from exc
            raise ProviderError(str(exc)) from exc

        facts: list[ProposedFact] = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_facts":
                for item in block.input.get("facts", []):
                    facts.append(ProposedFact(
                        field=item.get("field", ""),
                        target_event_id=item.get("target_event_id"),
                        target_scope=item.get("target_scope", "event"),
                        value=item.get("value", ""),
                        currency=item.get("currency"),
                        value_date=item.get("value_date"),
                        source_ids=tuple(item.get("source_ids", [])),
                        source_span=item.get("source_span", ""),
                    ))

        raw_usage = getattr(response, "usage", None)
        usage = Usage(
            calls=1,
            input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        )
        return ExtractionResult(facts=tuple(facts), usage=usage, raw_text=str(response.content))


def _build_message_content(request: ExtractionRequest) -> list[dict]:
    """Render sources as untrusted **data**, never as instructions.

    Each source is wrapped with its real id so the model can cite it, and
    prefixed by the system prompt's standing instruction that embedded text
    is content to read, not commands to follow.
    """
    parts: list[dict] = [{
        "type": "text",
        "text": (
            f"request_id={request.request_id} user_id={request.user_id} "
            f"unresolved_event_ids={list(request.unresolved_targets)}\n"
            "The following are untrusted evidence records, each labelled with its "
            "real source id. Cite only these ids in `source_ids`."
        ),
    }]
    for source_id, kind, text, image_bytes in request.sources:
        if kind == "image" and image_bytes:
            import base64
            parts.append({"type": "text", "text": f"--- image {source_id} ---"})
            parts.append({
                "type": "image",
                "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            })
        else:
            parts.append({"type": "text", "text": f"--- {kind} {source_id} ---\n{text}"})
    return parts


# -------------------------------------------------------------- bounded call


DEFAULT_PER_ROW_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_ATTEMPTS_PER_ROW = 3
DEFAULT_BACKOFF_SECONDS = 1.0


@dataclass
class UsageLedger:
    """Accumulates usage across a run and enforces the full-run budget."""

    full_run_call_budget: Optional[int] = None
    full_run_token_budget: Optional[int] = None
    total: Usage = field(default_factory=Usage)
    per_request: dict = field(default_factory=dict)

    def record(self, request_id: str, usage: Usage) -> None:
        self.total = self.total + usage
        self.per_request[request_id] = self.per_request.get(request_id, Usage()) + usage

    def check_budget(self) -> None:
        # A hard ceiling must reject at the limit itself, not only past it --
        # `>=` here, not `>` -- otherwise a call that lands exactly on budget
        # would still let one more call through.
        if self.full_run_call_budget is not None and self.total.calls >= self.full_run_call_budget:
            raise BudgetExceeded(f"full-run call budget {self.full_run_call_budget} exceeded")
        total_tokens = self.total.input_tokens + self.total.output_tokens
        if self.full_run_token_budget is not None and total_tokens >= self.full_run_token_budget:
            raise BudgetExceeded(f"full-run token budget {self.full_run_token_budget} exceeded")


#: Sentinel returned by `_run_with_hard_timeout` when the deadline elapses
#: before the worker thread reports a result. A plain object (not `None` or an
#: exception) so it cannot be confused with a real result or a raised error.
_TIMED_OUT = object()


def _run_with_hard_timeout(fn: Callable[..., Any], *args: Any, timeout: float) -> Any:
    """Run `fn(*args)` on a daemon thread and wait at most `timeout` seconds.

    Returns the result, the raised exception (not re-raised, so the caller can
    classify it), or `_TIMED_OUT`. Unlike `ThreadPoolExecutor`, this never
    blocks the caller past `timeout`: a hung `fn` is abandoned on its daemon
    thread, which cannot delay the caller or interpreter exit, giving the
    per-row timeout a true wall-clock bound.
    """
    outcome: "queue.Queue[Any]" = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 - classified by the caller
            outcome.put(exc)
        else:
            outcome.put(result)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        return outcome.get(timeout=timeout)
    except queue.Empty:
        return _TIMED_OUT


@dataclass
class BoundedCaller:
    """One provider-call wrapper for extraction and vision.

    A monotonic deadline (`clock`, defaulting to `time.monotonic`) bounds the
    whole row, not just one attempt: retries share the remaining time rather
    than each getting a fresh timeout. `AuthError` is never retried. An
    unclassified exception from a provider is treated as non-retryable --
    retrying an error the wrapper cannot classify as transient would risk
    silently multiplying calls against an unknown failure mode.
    """

    per_row_timeout_seconds: float = DEFAULT_PER_ROW_TIMEOUT_SECONDS
    max_attempts_per_row: int = DEFAULT_MAX_ATTEMPTS_PER_ROW
    per_row_token_budget: Optional[int] = None
    backoff_base_seconds: float = DEFAULT_BACKOFF_SECONDS
    sleeper: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def call(self, provider: Provider, request: ExtractionRequest, ledger: UsageLedger) -> ExtractionResult:
        # Checked before any call is attempted, not only after: `check_budget`
        # raising here means the ledger was already over budget from a prior
        # row, so this row must not place a new paid call at all.
        ledger.check_budget()

        deadline = self.clock() + self.per_row_timeout_seconds
        row_usage = Usage()
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_attempts_per_row + 1):
            remaining = deadline - self.clock()
            if remaining <= 0:
                last_error = TransientError(
                    f"{request.request_id}: per-row deadline exceeded before attempt {attempt}"
                )
                break

            outcome = _run_with_hard_timeout(provider.extract, request, timeout=remaining)
            if outcome is _TIMED_OUT:
                last_error = TransientError(f"{request.request_id}: attempt {attempt} timed out")
            elif isinstance(outcome, Exception):
                exc = outcome
                if isinstance(exc, AuthError):
                    ledger.record(request.request_id, row_usage)
                    raise exc
                if isinstance(exc, TransientError):
                    last_error = exc
                else:  # unclassified, do not retry
                    ledger.record(request.request_id, row_usage)
                    raise ProviderError(f"{request.request_id}: {exc}") from exc
            else:
                result = outcome
                row_usage = row_usage + result.usage
                if (self.per_row_token_budget is not None
                        and row_usage.input_tokens + row_usage.output_tokens
                        > self.per_row_token_budget):
                    ledger.record(request.request_id, row_usage)
                    raise BudgetExceeded(
                        f"{request.request_id}: per-row token budget "
                        f"{self.per_row_token_budget} exceeded"
                    )
                ledger.record(request.request_id, row_usage)
                ledger.check_budget()
                return result

            remaining = deadline - self.clock()
            if attempt == self.max_attempts_per_row or remaining <= 0:
                break
            backoff = min(self.backoff_base_seconds * (2 ** (attempt - 1)), remaining)
            if backoff > 0:
                self.sleeper(backoff)

        ledger.record(request.request_id, row_usage)
        raise last_error or TransientError(f"{request.request_id}: extraction failed with no result")


# -------------------------------------------------------------------- cache


def content_hash(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def cache_key(
    request: ExtractionRequest, *, model_id: str,
    prompt_version: str = PROMPT_VERSION, schema_version: str = SCHEMA_VERSION,
) -> str:
    """Key by source content, model, prompt/schema version, and request
    context -- media identity alone (August's weakness) is not enough,
    because the same image under a different prompt/schema must miss."""
    source_hash = content_hash(*(
        (source_id, kind, text, image_bytes or b"")
        for source_id, kind, text, image_bytes in request.sources
    ))
    return content_hash(
        source_hash, model_id, prompt_version, schema_version,
        request.request_id, tuple(sorted(request.unresolved_targets)),
    )


def fact_to_json(fact: ProposedFact) -> dict:
    return {
        "field": fact.field, "target_event_id": fact.target_event_id,
        "target_scope": fact.target_scope, "value": fact.value,
        "currency": fact.currency, "value_date": fact.value_date,
        "source_ids": list(fact.source_ids), "source_span": fact.source_span,
    }


def fact_from_json(data: dict) -> ProposedFact:
    return ProposedFact(
        field=data["field"], target_event_id=data.get("target_event_id"),
        target_scope=data.get("target_scope", "event"), value=data.get("value", ""),
        currency=data.get("currency"), value_date=data.get("value_date"),
        source_ids=tuple(data.get("source_ids", ())), source_span=data.get("source_span", ""),
    )


@dataclass
class ExtractionCache:
    """A content-hash-keyed cache of validated extraction results.

    `get` refuses a hit whose stored key does not match the key being asked
    for right now, so a record cannot be served under a different cache key
    than the one it was stored under -- the on-disk cache is a plain dict
    keyed by the same hash, but this makes the invariant explicit and tested
    rather than merely implied by dict lookup.
    """

    path: Optional[Path] = None
    _store: dict = field(default_factory=dict)

    def load(self) -> None:
        if self.path and self.path.exists():
            self._store = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._store, indent=2), encoding="utf-8")

    def get(self, key: str) -> Optional[dict]:
        record = self._store.get(key)
        if record is None or record.get("cache_key") != key:
            return None
        return record

    def put(self, key: str, *, facts: Sequence[ProposedFact], usage: Usage, model_id: str) -> None:
        self._store[key] = {
            "cache_key": key,
            "facts": [fact_to_json(f) for f in facts],
            "usage": usage.as_dict(),
            "model_id": model_id,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
        }
