# Token Usage & Cost Report

Generated: 2026-09-13 04:50:13 UTC — from the run that produced `output.csv`.

**No LLM calls were made in this run** (no `ANTHROPIC_API_KEY`/`LLM_API_KEY` was set, or no users had messages/images). `facts=[]` throughout and every `decision_explanation` used plan_selector's deterministic template.

## How to run

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
deterministic engine without spending any tokens.
