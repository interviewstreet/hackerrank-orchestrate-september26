# Token Usage & Cost Report

Generated: 2026-09-13 09:32:09 UTC — from the run that produced `output.csv`.

**This run made 0 LLM calls — that's this run's configuration, not a limit of the solution.** Modules 6 (`llm_extract`) and 7 (`llm_explain`) call Claude automatically whenever `ANTHROPIC_API_KEY` (or `LLM_API_KEY`) is set in the environment; this run either had no key configured, or no request's user had any `messages.csv`/`images.csv` rows to extract facts from. See "Enabling LLM calls" below for exactly where to set the key. Every deterministic module still ran in full either way — loaders, event_normalizer, forecast_engine, plan_selector, output_writer — so `amount_safe_to_pay`, `affordability_status`, and the payment plan are unaffected by whether a key is set. Only two things fall back: `facts=[]` (Module 6 has nothing from messages/images to add to the timeline) and `decision_explanation` uses plan_selector's deterministic template sentence instead of Claude's phrasing (Module 7).

## How to run

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
| PowerShell | `.\.venv\Scripts\Activate.ps1` |
| cmd.exe | `.venv\Scripts\activate.bat` |

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
- Writes `output.csv` at the repository root and regenerates this report.
