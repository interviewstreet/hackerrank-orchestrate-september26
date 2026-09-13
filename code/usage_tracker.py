"""Module 8: usage_tracker.

Turns the UsageRecord lists produced by Module 6 (`llm_extract`) and Module 7
(`llm_explain`) into `evaluation/usage_report.md` — the token/cost accounting
the submission requires (AGENTS.md §6.5, problem_statement.md "Token Usage
and Cost Analysis"). Pure aggregation and formatting: no LLM calls happen
here, and nothing here feeds back into the deterministic decision logic.

`write_usage_report()` always overwrites the file with a complete, standalone
report reflecting whatever the most recent `python3 code/evaluation/main.py`
run actually did — including a "no calls were made" report when no API key
was set, so the file never goes stale relative to the output.csv it was
written next to.
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
```

Create the virtual environment once:

```bash
python -m venv .venv
```

Activate it — the command depends on which terminal you're using:

| Terminal | Activate command |
|---|---|
| Git Bash / WSL / macOS / Linux (bash, zsh) | `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (macOS/Linux/WSL) |
| PowerShell | `.\\.venv\\Scripts\\Activate.ps1` |
| cmd.exe | `.venv\\Scripts\\activate.bat` |

If PowerShell blocks `Activate.ps1` with an execution-policy error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, then retry. The prompt is prefixed with `(.venv)` once it's active.

To skip activation entirely, call the venv's Python directly: `.venv/Scripts/python.exe code/evaluation/main.py` (Windows) or `.venv/bin/python code/evaluation/main.py` (macOS/Linux).

```bash
# 1. Install dependencies
pip install -r code/requirements.txt
```

### Enabling LLM calls (optional)

The solution reads the key from a plain OS environment variable named
`ANTHROPIC_API_KEY` (`LLM_API_KEY` also works) — it does **not** read a
`.env` file by itself. Set it either way:

- **Directly in your shell**, for the current session only:
  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...    # bash/zsh/Git Bash
  $env:ANTHROPIC_API_KEY = "sk-ant-..."  # PowerShell
  ```
- **In a `.env` file** at the repo root (gitignored, never commit it), then
  load it into the shell before running — this repo's code doesn't auto-load
  `.env`, so the load step below is required:
  ```bash
  echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
  set -a; source .env; set +a   # bash/zsh/Git Bash, run before each session
  ```

Get a key at https://console.anthropic.com/ — it must be scoped to a
workspace with billing/credit enabled, or calls fail with a 400 error.
Optional: override the default model with `export LLM_MODEL=claude-sonnet-5`.

**With a key set**, Modules 6 and 7 call Claude automatically — nothing else
to configure. **Without a key**, the pipeline still runs completely
end-to-end; it just skips those two calls (see the note above this section
for exactly what that does and doesn't affect).

```bash
# Run the full pipeline
python3 code/evaluation/main.py
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
- Writes `output.csv` at the repository root and regenerates this report."""

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
            "**This run made 0 LLM calls — that's this run's configuration, not a limit of "
            "the solution.** Modules 6 (`llm_extract`) and 7 (`llm_explain`) call Claude "
            "automatically whenever `ANTHROPIC_API_KEY` (or `LLM_API_KEY`) is set in the "
            "environment; this run either had no key configured, or no request's user had any "
            "`messages.csv`/`images.csv` rows to extract facts from. See \"Enabling LLM calls\" "
            "below for exactly where to set the key. Every deterministic module still ran in "
            "full either way — loaders, event_normalizer, forecast_engine, plan_selector, "
            "output_writer — so `amount_safe_to_pay`, `affordability_status`, and the payment "
            "plan are unaffected by whether a key is set. Only two things fall back: "
            "`facts=[]` (Module 6 has nothing from messages/images to add to the timeline) and "
            "`decision_explanation` uses plan_selector's deterministic template sentence "
            "instead of Claude's phrasing (Module 7)."
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
