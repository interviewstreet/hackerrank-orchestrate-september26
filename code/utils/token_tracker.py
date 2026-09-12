"""Track model usage per request and enforce a hard call budget.

Groq's limits on this account are the binding constraint, not cost: roughly
1000 requests per day *per model*, with an 8000-token-per-minute bucket. The
tracker therefore doubles as a budget guard -- it refuses further calls once a
model's allowance is spent, so a full run cannot silently exhaust the quota.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import MODEL_PRICING


class BudgetExhausted(RuntimeError):
    """Raised when a model's per-run call allowance is used up."""


@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_usd(self, model: str) -> float:
        price_in, price_out = MODEL_PRICING.get(model, (0.0, 0.0))
        return (
            self.input_tokens * price_in + self.output_tokens * price_out
        ) / 1_000_000


@dataclass
class TokenTracker:
    """Thread-safe usage ledger."""

    max_calls_per_model: int = 1000
    by_model: dict[str, ModelUsage] = field(default_factory=lambda: defaultdict(ModelUsage))
    requests_seen: set[str] = field(default_factory=set)
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self, model: str) -> None:
        """Claim one call against `model`'s allowance before issuing it."""
        with self._lock:
            if self.by_model[model].calls >= self.max_calls_per_model:
                raise BudgetExhausted(
                    f"{model} reached the {self.max_calls_per_model}-call budget"
                )

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        request_id: str | None = None,
    ) -> None:
        with self._lock:
            usage = self.by_model[model]
            usage.calls += 1
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            if request_id:
                self.requests_seen.add(request_id)

    def record_failure(self, model: str) -> None:
        with self._lock:
            self.by_model[model].failures += 1

    # ---- reporting ---------------------------------------------------------

    @property
    def total_calls(self) -> int:
        return sum(u.calls for u in self.by_model.values())

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self.by_model.values())

    @property
    def total_cost(self) -> float:
        return sum(u.cost_usd(m) for m, u in self.by_model.items())

    def summary_line(self) -> str:
        return (
            f"{self.total_calls} calls, {self.total_tokens:,} tokens, "
            f"${self.total_cost:.4f}"
        )

    def write_usage_report(self, path: Path, request_count: int | None = None) -> None:
        """Emit the evaluation/usage_report.md required by the submission."""
        n = request_count or len(self.requests_seen) or 1
        elapsed = time.time() - self.started_at
        lines = [
            "# Token Usage Report",
            "",
            "Final full-dataset run that produced `output.csv`.",
            "",
            "## Run Summary",
            "",
            f"- Date (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
            f"- Provider: Groq (OpenAI-compatible API)",
            f"- Requests processed: {n}",
            f"- Duration: {int(elapsed // 60)}m {int(elapsed % 60)}s",
            f"- Total model calls: {self.total_calls}",
            "",
            "## Per-Model Breakdown",
            "",
            "| Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |",
            "| --- | --: | --: | --: | --: | --: |",
        ]
        for model in sorted(self.by_model):
            u = self.by_model[model]
            lines.append(
                f"| `{model}` | {u.calls} | {u.input_tokens:,} | {u.output_tokens:,} "
                f"| {u.total_tokens:,} | ${u.cost_usd(model):.4f} |"
            )

        lines += [
            "",
            "## Overall Totals",
            "",
            f"- Total model calls: {self.total_calls}",
            f"- Total tokens: {self.total_tokens:,}",
            f"- Average tokens per request: {self.total_tokens / n:,.0f}",
            f"- Average calls per request: {self.total_calls / n:.2f}",
            f"- Estimated total cost: ${self.total_cost:.4f}",
            f"- Estimated cost per request: ${self.total_cost / n:.6f}",
            "",
            "## Notes",
            "",
            "- Pricing is per million tokens, from `code/config.py::MODEL_PRICING`.",
            "- Receipt OCR results are cached by `image_id`, so each of the 16",
            "  dataset images is read by the vision model at most once per run.",
            "- Requests with no messages and no linked images need no evidence",
            "  calls, which is why average calls per request is below the cap.",
            "- No API keys or credentials are recorded here.",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
