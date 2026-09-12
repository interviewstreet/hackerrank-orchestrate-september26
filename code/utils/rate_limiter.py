"""Per-model pacing so a full run does not trip Groq's rate limits.

Measured on this account (from ``x-ratelimit-*`` response headers):

* ~1000 requests per day, per model
* an 8000-token-per-minute bucket, per model
* ``qwen/qwen3.6-27b`` additionally rejects any request whose ``max_tokens``
  exceeds 1000 output tokens per minute

The limiter keeps a sliding 60-second window of tokens spent per model and
blocks until there is room, which turns a burst of 429s into steady progress.
Because buckets are per model, routing different jobs to different models
multiplies the throughput actually available.

What the window charges is deliberately *not* the tokens a call turned out to
spend. Groq bills TPM for ``prompt_tokens + max_tokens`` the moment a request is
accepted -- a 429 body reads "Used 7626, Requested 2225" before any output
exists -- so a claim is corrected upward when the prompt was larger than
estimated, and never downward. Refunding the unused output allowance would look
like free throughput and simply produce 429s, whose backoff costs far more than
the pacing it skipped.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

RETRY_AFTER = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)
DEFAULT_BACKOFF = 5.0
MAX_BACKOFF = 65.0
# Fraction of the advertised limit we are willing to hold, leaving room for
# estimation error on the call in flight.
SAFETY_FRACTION = 0.92


@dataclass
class Reservation:
    """A claim on a model's token window, correctable after the fact."""

    model: str
    tokens: int
    _limiter: "RateLimiter"

    def settle(self, charged_tokens: int) -> None:
        """Correct the claim to what the server actually charged."""
        self._limiter._settle(self, charged_tokens)


class RateLimiter:
    """Sliding-window token pacer, one window per model."""

    def __init__(self, tokens_per_minute: int = 8000, window: float = 60.0) -> None:
        self.limit = tokens_per_minute
        self.window = window
        self._entries: dict[str, deque[list]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def budget(self) -> int:
        return max(1, int(self.limit * SAFETY_FRACTION))

    def acquire(self, model: str, estimated_tokens: int) -> Reservation:
        """Block until `estimated_tokens` fits this model's window, then claim it."""
        want = max(1, min(estimated_tokens, self.budget))
        while True:
            with self._lock:
                used = self._prune(model)
                if used + want <= self.budget:
                    entry = [time.monotonic(), want]
                    self._entries[model].append(entry)
                    return Reservation(model=model, tokens=want, _limiter=self)
                wait_until = self._entries[model][0][0] + self.window
            time.sleep(max(0.05, min(self.window, wait_until - time.monotonic())))

    def _settle(self, reservation: Reservation, charged_tokens: int) -> None:
        """Correct a claim, but never below what the server charges.

        Groq bills the window for ``prompt_tokens + max_tokens`` at the moment a
        request is accepted, not for the completion actually produced -- a 429
        body reads "Used 7626, Requested 2225" before any output exists. Settling
        down to real completion tokens therefore under-counts against their
        ledger and invites a 429, whose backoff costs far more than the
        throughput the refund would have won. So a claim only ever moves up.
        """
        charged = max(1, min(charged_tokens, self.budget))
        with self._lock:
            for entry in reversed(self._entries[reservation.model]):
                if entry[1] == reservation.tokens:
                    entry[1] = max(entry[1], charged)
                    return

    def pause(self, model: str, seconds: float) -> None:
        """Honour an explicit server-side backoff for one model."""
        time.sleep(min(seconds, MAX_BACKOFF))

    def _prune(self, model: str) -> int:
        cutoff = time.monotonic() - self.window
        window = self._entries[model]
        while window and window[0][0] < cutoff:
            window.popleft()
        return sum(tokens for _, tokens in window)


def suggested_wait(error: Exception) -> float:
    """Seconds Groq asked us to wait, from the 429 body; else a safe default."""
    found = RETRY_AFTER.search(str(error))
    if found:
        try:
            return min(MAX_BACKOFF, float(found.group(1)) + 0.5)
        except ValueError:
            pass
    return DEFAULT_BACKOFF


def estimate_tokens(messages: list, max_output: int) -> int:
    """Estimate what Groq will charge: ~4 characters per token, images ~1900.

    ``max_output`` is included because the server charges the requested ceiling
    up front, not the completion it ends up returning.
    """
    characters = 0
    images = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            characters += len(content)
            continue
        for part in content or []:
            if part.get("type") == "image_url":
                images += 1
            else:
                characters += len(part.get("text") or "")
    return characters // 4 + images * 1900 + max_output
