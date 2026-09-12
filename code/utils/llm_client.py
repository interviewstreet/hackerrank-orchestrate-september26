"""Groq access layer: structured extraction, tool calling, and rate-limit care.

Two entry points, deliberately separate:

* :meth:`LLMClient.extract` -- one-shot structured extraction into a Pydantic
  model, via ``instructor``. Used for leaf tasks (receipt OCR, message
  interpretation) where a typed answer is all we want.
* :meth:`LLMClient.converse` -- a raw tool-calling turn. ``instructor`` cannot
  drive an agentic loop, because in tool mode it spends the tool slot on its own
  schema, so the orchestrator uses the unpatched client.

Every call reserves budget first, retries on transient failures with
exponential backoff, and records tokens for the usage report.
"""

from __future__ import annotations

from typing import Any, TypeVar

import instructor
from groq import Groq, RateLimitError
from groq import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import Settings
from utils.rate_limiter import (
    RateLimiter,
    Reservation,
    estimate_tokens,
    suggested_wait,
)
from utils.token_tracker import TokenTracker

ModelT = TypeVar("ModelT", bound=BaseModel)

TRANSIENT = (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError)


def _is_rate_limited(error: Exception) -> bool:
    """True for a 429, including one wrapped by instructor's retry handler."""
    if isinstance(error, RateLimitError):
        return True
    text = str(error)
    return "rate_limit_exceeded" in text or "429" in text


class LLMClient:
    """Rate-limit-aware Groq wrapper shared by every tool."""

    def __init__(
        self,
        settings: Settings,
        tracker: TokenTracker,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings
        self.tracker = tracker
        self.limiter = limiter or RateLimiter(settings.tokens_per_minute)
        self._raw = Groq(api_key=settings.groq_api_key, max_retries=0)
        # Two extraction modes, because Groq validates tool-call arguments
        # server-side against the generated schema. For a flat model that check
        # is helpful and TOOLS mode recovers more fields (measured on the
        # dataset's receipts). For a nested model it is too strict: a model that
        # answers correctly but names a key "type" instead of "action" gets its
        # whole answer rejected with a 400, so nested schemas use JSON mode and
        # are parsed locally, where field aliases can absorb the variation.
        self._by_mode = {
            "tools": instructor.from_groq(self._raw, mode=instructor.Mode.TOOLS),
            "json": instructor.from_groq(self._raw, mode=instructor.Mode.JSON),
        }

    # ---- structured extraction --------------------------------------------

    def extract(
        self,
        *,
        model: str,
        response_model: type[ModelT],
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        request_id: str | None = None,
        mode: str = "tools",
    ) -> ModelT | None:
        """Extract a validated Pydantic model, or None if it cannot be had.

        Returning None rather than raising matters: a receipt the model cannot
        read must not be treated as a zero amount.
        """
        self.tracker.reserve(model)
        budget = max_tokens or self.settings.max_output_tokens
        estimate = estimate_tokens(messages, budget)

        completion = None
        result = None
        reservation = None
        for attempt in range(self.settings.max_retries + 2):
            reservation = self.limiter.acquire(model, estimate)
            try:
                result, completion = self._call_structured(
                    model=model,
                    response_model=response_model,
                    messages=messages,
                    max_tokens=budget,
                    mode=mode,
                )
                break
            except Exception as error:  # noqa: BLE001 - classify below
                if not _is_rate_limited(error) or attempt == self.settings.max_retries + 1:
                    self.tracker.record_failure(model)
                    return None
                self.limiter.pause(model, suggested_wait(error))

        if result is None:
            self.tracker.record_failure(model)
            return None

        self._settle(model, completion, reservation, request_id, budget)
        return result

    @retry(
        retry=retry_if_exception_type(TRANSIENT),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _call_structured(
        self,
        *,
        model: str,
        response_model: type[ModelT],
        messages: list[dict[str, Any]],
        max_tokens: int,
        mode: str = "tools",
    ) -> tuple[ModelT, Any]:
        return self._by_mode[mode].chat.completions.create_with_completion(
            model=model,
            response_model=response_model,
            messages=messages,
            temperature=self.settings.temperature,
            max_tokens=max_tokens,
            max_retries=self.settings.max_retries,
        )

    # ---- tool-calling turn -------------------------------------------------

    def converse(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> Any | None:
        """One assistant turn, which may return tool calls or a final answer."""
        self.tracker.reserve(model)
        budget = max_tokens or self.settings.max_output_tokens
        estimate = estimate_tokens(messages, budget, tools)

        for attempt in range(self.settings.max_retries + 2):
            reservation = self.limiter.acquire(model, estimate)
            try:
                completion = self._call_chat(
                    model=model,
                    messages=messages,
                    tools=tools,
                    max_tokens=budget,
                )
            except Exception as error:  # noqa: BLE001 - classify below
                if not _is_rate_limited(error) or attempt == self.settings.max_retries + 1:
                    self.tracker.record_failure(model)
                    return None
                self.limiter.pause(model, suggested_wait(error))
                continue
            self._settle(model, completion, reservation, request_id, budget)
            return completion.choices[0].message
        return None

    @retry(
        retry=retry_if_exception_type(TRANSIENT),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _call_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self._raw.chat.completions.create(**kwargs)

    # ---- lightweight classifier -------------------------------------------

    def classify(
        self, *, model: str, text: str, request_id: str | None = None
    ) -> str | None:
        """Single-label classification, used by the prompt-injection screen."""
        self.tracker.reserve(model)
        messages = [{"role": "user", "content": text}]
        reservation = self.limiter.acquire(model, estimate_tokens(messages, 16))
        try:
            completion = self._call_chat(
                model=model, messages=messages, tools=None, max_tokens=16
            )
        except Exception:
            self.tracker.record_failure(model)
            return None
        self._settle(model, completion, reservation, request_id, 16)
        return (completion.choices[0].message.content or "").strip()

    # ---- bookkeeping -------------------------------------------------------

    def _settle(
        self,
        model: str,
        completion: Any,
        reservation: Reservation | None,
        request_id: str | None,
        requested_max: int,
    ) -> None:
        """Record real usage, and charge the window what the server charges.

        The usage report tracks the tokens actually spent; the pacer tracks
        prompt + requested ceiling, which is what counts against TPM.
        """
        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        self.tracker.record(model, prompt_tokens, output_tokens, request_id)
        if reservation is not None:
            reservation.settle(prompt_tokens + requested_max)
