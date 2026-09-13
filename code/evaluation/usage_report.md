# Token Usage & Cost Report

> **Status: not yet run with a live API key.** Everything below Section 2 is a
> template — follow Section 1, run the pipeline once with your own
> `ANTHROPIC_API_KEY`, then replace Section 2 with the real numbers `code/main.py`
> prints at the end of the run. This file must reflect the **final full-dataset
> run** that produced the submitted `output.csv` (AGENTS.md §6.5 / problem
> statement "Token Usage and Cost Analysis").

## 1. How to run

```bash
cd hackerrank-orchestrate-september26

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
  `messages.csv` or `images.csv` (about 200 of the 250 requests), makes **one**
  Claude call combining all of that user's messages and images (images sent as
  inline vision input — 16 total across the dataset) to extract structured
  facts. A user with no messages/images costs nothing — no call is made.
- **Module 7 (`llm_explain`)**: for every one of the 250 requests, makes one
  short Claude call to phrase the already-decided numbers as 1-2 sentences.
  If the model's text uses a number or date not present in the decision data,
  it is rejected and the deterministic template is used instead — this never
  changes `amount_safe_to_pay`, dates, or the recommended method, only the
  wording of `decision_explanation`.
- Writes `output.csv` at the repository root.
- Prints a summary line like:

  ```text
  Wrote 250 rows to .../output.csv in 12.34s
  llm_extract: 200 calls, 48213 input / 9120 output tokens
  llm_explain: 250 calls, 31500 input / 6875 output tokens
  Total: 79713 input / 15995 output tokens across 450 calls
  ```

Without an API key set, `python3 code/main.py` still runs end-to-end
(deterministic-only: `facts=[]`, template-based explanations) and prints
`No LLM calls made (no ANTHROPIC_API_KEY/LLM_API_KEY set)` instead — useful for
sanity-checking the deterministic engine without spending any tokens.

## 2. Final run results — fill in after running with a real key

| Field | Value |
|---|---|
| Date of final run | _fill in_ |
| Model provider | Anthropic |
| Model name(s) | _fill in — from `LLM_MODEL` or the default printed above_ |
| `llm_extract` calls | _fill in_ |
| `llm_extract` input tokens | _fill in_ |
| `llm_extract` output tokens | _fill in_ |
| `llm_explain` calls | _fill in_ |
| `llm_explain` input tokens | _fill in_ |
| `llm_explain` output tokens | _fill in_ |
| Total calls | _fill in_ |
| Total input tokens | _fill in_ |
| Total output tokens | _fill in_ |
| Total tokens | _fill in_ |
| Average tokens per request (250 requests) | _fill in — total tokens / 250_ |
| Estimated cost (input) | _fill in — input tokens × your model's per-token input price_ |
| Estimated cost (output) | _fill in — output tokens × your model's per-token output price_ |
| **Estimated total cost** | _fill in_ |
| Estimated cost per request | _fill in — total cost / 250_ |

Current per-token pricing for whichever model you used is published at
<https://www.anthropic.com/pricing> — use the rate in effect on the date of
your final run.

## 3. Notes

- Only the **final** run that produced the submitted `output.csv` needs to be
  reported here — re-runs during development don't count.
- No API keys or credentials are recorded in this file or anywhere else in the
  repo; only the environment variable *name* (`ANTHROPIC_API_KEY`) is
  documented.
- If you swap in a different provider/model, update Section 1's example
  command and Section 2's "Model provider"/"Model name(s)" rows accordingly —
  the rest of the pipeline is provider-agnostic as long as `llm_extract.py`
  and `llm_explain.py`'s API-call sections are adapted to match.
