"""Module 8: usage_tracker.

Turns the UsageRecord lists produced by Module 6 (`llm_extract`) and Module 7
(`llm_explain`) into `evaluation/usage_report.md` — the token/cost accounting
the submission requires (AGENTS.md §6.5, problem_statement.md "Token Usage
and Cost Analysis"). Pure aggregation and formatting: no LLM calls happen
here, and nothing here feeds back into the deterministic decision logic.

`write_usage_report()` always overwrites the file with a complete, standalone
report reflecting whatever the most recent `python3 code/main.py` run
actually did — including a "no calls were made" report when no API key was
set, so the file never goes stale relative to the output.csv it was written
next to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llm_explain import UsageRecord as ExplainUsageRecord
from llm_extract import UsageRecord as ExtractUsageRecord

# USD per 1M tokens. Source: https://www.anthropic.com/pricing — verify against
# the live page before trusting a cost estimate; rates change over time and a
# model not listed here reports "unknown" rather than a guessed number.
PRICING_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-5": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}

RUN_INSTRUCTIONS = """## How to run

Requires **Python 3.8 or newer** (tested on 3.10.2). Do not use Python 3.6.x —
the code relies on `from __future__ import annotations` (added in Python 3.7)
and dataclasses throughout.

```bash
cd hackerrank-orchestrate-september26

# Optional but recommended: create a virtual environment with Python 3.8+
python3.10 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 1. Install dependencies
pip install -r code/requirements.txt

# 2. Set your API key (get one at https://console.anthropic.com/)
export ANTHROPIC_API_KEY=sk-ant-...
#   (LLM_API_KEY also works if you prefer that name)

# Optional: override the default model (defaults to claude-sonnet-5)
# export LLM_MODEL=claude-sonnet-5

# 3. Run the full pipeline
python3 code/main.py
```

What happens:

- Reads every file in `dataset/`, builds each user's clean financial timeline,
  and forecasts 90 days forward — all deterministic, no LLM involved.
- **Module 6 (`llm_extract`)**: for every user who has at least one row in
  `messages.csv` or `images.csv`, makes **one** Claude call combining all of
  that user's messages and images (sent as inline vision input) to extract
  structured facts. A user with no messages/images costs nothing.
- **Module 7 (`llm_explain`)**: for every request, makes one short Claude call
  to phrase the already-decided numbers as 1-2 sentences. A response using a
  number or date not present in the decision data is rejected and the
  deterministic template is used instead — this never changes
  `amount_safe_to_pay`, dates, or the recommended method.
- Writes `output.csv` at the repository root and regenerates this report.

Without an API key, `python3 code/main.py` still runs end-to-end
(deterministic-only: `facts=[]`, template-based explanations) and this report
records that no LLM calls were made — useful for sanity-checking the
deterministic engine without spending any tokens."""

PRICING_NOTE_HEADER = "## Pricing assumptions\n\nUSD per 1M tokens, from https://www.anthropic.com/pricing — verify against the live page since rates can change:\n"


@dataclass
class ModelTotals:
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_usd(self) -> Optional[tuple[float, float, float]]:
        rates = PRICING_PER_MILLION_TOKENS.get(self.model)
        if rates is None:
            return None
        input_cost = self.input_tokens / 1_000_000 * rates["input"]
        output_cost = self.output_tokens / 1_000_000 * rates["output"]
        return input_cost, output_cost, input_cost + output_cost


def _fmt_cost(value: Optional[float]) -> str:
    return f"${value:,.4f}" if value is not None else "unknown"


def _aggregate_by_model(
    extract_usage: list[ExtractUsageRecord], explain_usage: list[ExplainUsageRecord]
) -> dict[str, ModelTotals]:
    by_model: dict[str, ModelTotals] = {}

    def add(model: str, input_tokens: int, output_tokens: int) -> None:
        totals = by_model.setdefault(model, ModelTotals(model=model))
        totals.calls += 1
        totals.input_tokens += input_tokens
        totals.output_tokens += output_tokens

    for record in extract_usage:
        add(record.model, record.input_tokens, record.output_tokens)
    for record in explain_usage:
        add(record.model, record.input_tokens, record.output_tokens)
    return by_model


def build_usage_report(
    extract_usage: list[ExtractUsageRecord],
    explain_usage: list[ExplainUsageRecord],
    num_requests: int,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_calls = len(extract_usage) + len(explain_usage)

    lines: list[str] = ["# Token Usage & Cost Report", ""]
    lines.append(f"Generated: {generated_at} — from the run that produced `output.csv`.")
    lines.append("")

    if total_calls == 0:
        lines.append(
            "**No LLM calls were made in this run** (no `ANTHROPIC_API_KEY`/`LLM_API_KEY` was "
            "set, or no users had messages/images). `facts=[]` throughout and every "
            "`decision_explanation` used plan_selector's deterministic template."
        )
        lines.append("")
        lines.append(RUN_INSTRUCTIONS)
        return "\n".join(lines) + "\n"

    extract_in = sum(u.input_tokens for u in extract_usage)
    extract_out = sum(u.output_tokens for u in extract_usage)
    explain_in = sum(u.input_tokens for u in explain_usage)
    explain_out = sum(u.output_tokens for u in explain_usage)
    total_in = extract_in + explain_in
    total_out = extract_out + explain_out
    total_tokens = total_in + total_out

    by_model = _aggregate_by_model(extract_usage, explain_usage)
    models_used = sorted(by_model)

    known_costs = [t.cost_usd() for t in by_model.values()]
    total_cost = sum(c[2] for c in known_costs if c is not None) if any(c is not None for c in known_costs) else None
    all_priced = all(c is not None for c in known_costs)

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append("| Model provider | Anthropic |")
    lines.append(f"| Model(s) used | {', '.join(models_used)} |")
    lines.append(f"| Requests processed | {num_requests} |")
    lines.append(f"| Total LLM calls | {total_calls} |")
    lines.append(f"| Total input tokens | {total_in:,} |")
    lines.append(f"| Total output tokens | {total_out:,} |")
    lines.append(f"| Total tokens | {total_tokens:,} |")
    lines.append(f"| Average tokens per request | {total_tokens / num_requests:,.1f} |" if num_requests else "| Average tokens per request | n/a |")
    lines.append(
        f"| Estimated total cost | {_fmt_cost(total_cost)}"
        + ("" if all_priced else " (partial — see per-model table)") + " |"
    )
    if num_requests and total_cost is not None:
        lines.append(f"| Estimated cost per request | {_fmt_cost(total_cost / num_requests)} |")
    lines.append("")

    lines.append("## By module")
    lines.append("")
    lines.append("| Module | Calls | Input tokens | Output tokens | Total tokens |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| llm_extract (Module 6) | {len(extract_usage)} | {extract_in:,} | {extract_out:,} | {extract_in + extract_out:,} |")
    lines.append(f"| llm_explain (Module 7) | {len(explain_usage)} | {explain_in:,} | {explain_out:,} | {explain_in + explain_out:,} |")
    lines.append(f"| **Total** | {total_calls} | {total_in:,} | {total_out:,} | {total_tokens:,} |")
    lines.append("")

    lines.append("## By model")
    lines.append("")
    lines.append("| Model | Calls | Input tokens | Output tokens | Input cost | Output cost | Total cost |")
    lines.append("|---|---|---|---|---|---|---|")
    for model in models_used:
        totals = by_model[model]
        cost = totals.cost_usd()
        if cost is None:
            in_cost = out_cost = tot_cost = "unknown (model not in pricing table — check anthropic.com/pricing)"
        else:
            in_cost, out_cost, tot = cost
            in_cost, out_cost, tot_cost = _fmt_cost(in_cost), _fmt_cost(out_cost), _fmt_cost(tot)
        lines.append(
            f"| {model} | {totals.calls} | {totals.input_tokens:,} | {totals.output_tokens:,} | "
            f"{in_cost} | {out_cost} | {tot_cost} |"
        )
    lines.append("")

    lines.append(PRICING_NOTE_HEADER)
    for model in models_used:
        rates = PRICING_PER_MILLION_TOKENS.get(model)
        if rates:
            lines.append(f"- {model}: ${rates['input']:.2f} input / ${rates['output']:.2f} output")
        else:
            lines.append(f"- {model}: not in this file's pricing table — add it or check the live pricing page")
    lines.append("")

    lines.append(RUN_INSTRUCTIONS)
    return "\n".join(lines) + "\n"


def write_usage_report(
    path: Path,
    extract_usage: list[ExtractUsageRecord],
    explain_usage: list[ExplainUsageRecord],
    num_requests: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_usage_report(extract_usage, explain_usage, num_requests), encoding="utf-8")
