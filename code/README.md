# Buy or Wait? — AI-powered financial affordability agent

For each request in `dataset/requests.csv`, this agent reconstructs the person's
forward cash position and decides whether to pay in full, pay part now, use an
installment offer, wait, or not proceed — then writes `output.csv`.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r code/requirements.txt
```

Put your Groq key in a `.env` file at the repository root (never in the code):

```
GROQ_API_KEY=your_key_here
```

The key is read from the environment via `pydantic-settings`. Nothing else is
configured; all paths resolve relative to the repository, so the agent runs from
any working directory.

## Run

```bash
cd code
python main.py                        # every request -> output.csv
python main.py --limit 10             # first 10 requests
python main.py --request-id request_42
python main.py --samples              # the 25 labelled samples instead
python main.py --resume               # continue after an interruption
python main.py --workers 3            # requests in flight at once (default 3)
python main.py --no-llm               # deterministic engine only, zero API calls
```

Requests are processed concurrently because the limits below are *per model*
and the orchestrator alternates across a pool of them, so concurrent requests
mostly draw on different token buckets. This turns time otherwise spent waiting
on the pacer into throughput without hitting any single model harder. Rows are
collected by their original index and re-sorted before writing, so output order
always follows the dataset, never completion order.

Output is written to both `output.csv` (submission) and `dataset/output.csv`
(the template the task asks you to fill). Token usage lands in
`code/evaluation/usage_report.md`.

Every request is checkpointed as it completes — to
`code/.cache/checkpoint.jsonl`, or `checkpoint_samples.jsonl` under `--samples`
so the two scopes cannot contaminate each other — and `--resume` never re-spends
API budget on work already done.

## Verify

```bash
cd code
python evaluation/main.py                            # validate output.csv
python evaluation/main.py --against-samples \
    --output /path/to/sample_run.csv                 # and score it
python evaluation/calibrate.py                       # tune the forecast, no API calls
python evaluation/calibrate.py --show request_05     # dump one request's ledger
```

```bash
python tests/test_financial_rules.py   # 31 checks on the financial rules
python package.py                      # build ../code.zip for submission
```

`package.py` archives the contents of `code/` so `evaluation/usage_report.md`
sits where the submission expects it, excludes `.env`, caches and virtualenvs,
and refuses to build if anything resembling a credential is present.

`evaluation/main.py` re-checks schema, coverage, enums, ranges, formats,
internal consistency, and re-simulates every recommended plan against the
90-day forecast. `evaluation/calibrate.py` scores the deterministic engine
against the labelled samples using no API calls at all, which is what made
forecast tuning affordable under the rate limits described below.

## How it works

```
requests.csv ─▶ safety gate ─▶ orchestrator agent (tool-calling loop)
                                 │
                                 ├─ load_context      profile, series, options, baseline
                                 ├─ read_receipt      vision OCR for blank amounts
                                 ├─ resolve_messages  amendments, delays, cancellations
                                 ├─ run_forecast      90-day simulation
                                 ├─ evaluate_plans    candidates, safety-checked, ranked
                                 ├─ suggest_spending_changes
                                 └─ submit_answer ──▶ deterministic validator
                                                          │
                                                          ▼
                                              output.csv + usage_report.md
```

The split is deliberate. **The model never does arithmetic.** It decides which
evidence this particular request needs, judges what that evidence means, picks
among plans the tools have already verified, and writes the explanation. Every
number comes from a deterministic tool, and `submit_answer` re-simulates the
chosen plan independently before accepting it — so a reasoning slip cannot
produce a plan that breaches the minimum balance. If validation fails, the
errors go back to the model to correct.

### Module map

| Path | Responsibility |
| --- | --- |
| `main.py` | CLI, checkpointing, output writing |
| `config.py` | Settings from env, model ids, pricing, path resolution |
| `agents/orchestrator.py` | The tool-calling loop, tool dispatch, fallback |
| `agents/prompts.py` | System prompts and the seven tool schemas |
| `tools/dataset_loader.py` | Load and index all nine CSVs into typed models |
| `tools/balance_forecaster.py` | Recurrence detection and the 90-day simulation |
| `tools/plan_generator.py` | Candidate plans, eligibility, ranking |
| `tools/spending_optimizer.py` | Permitted stop/reduce search |
| `tools/decision_engine.py` | Deterministic end-to-end solver and fallback |
| `tools/message_resolver.py` | Messages → typed event modifications |
| `tools/image_extractor.py` | Receipt OCR, cached by `image_id` |
| `tools/exchange_converter.py` | Dated FX with nearest-date fallback |
| `tools/safety_gate.py` | Prompt-injection screening and delimiting |
| `tools/retriever.py` | Local FAISS few-shot and series matching |
| `validators/schemas.py` | Pydantic models for every boundary |
| `validators/output_validator.py` | Ten checks plus safety re-simulation |
| `utils/llm_client.py` | Groq access, structured output, retries |
| `utils/rate_limiter.py` | Sliding-window token pacing per model |
| `utils/token_tracker.py` | Usage ledger, budget guard, usage report |

### Financial rules the forecaster enforces

- `cancelled` and `failed` rows never move money; `non_cash` / `unrealized`
  investment valuations are not cash.
- Pending **debits** are reserved. Pending **credits** are ignored until settled,
  as are unapproved bonuses, commissions on open deals, and refunds in flight.
- Recurrence is inferred from history only, per `(direction, category)` — variable
  essentials arrive under many descriptions ("Local market purchase", "Fresh food
  shop") but are one economic series. A confirmed future salary also counts as
  evidence of cadence.
- Observed gaps are snapped to real rhythms — weekly, fortnightly, or calendar
  monthly on the same day-of-month.
- Income projects forward at its most recently confirmed figure; variable spending
  at its mean. A series whose latest row is described as final ("Final employer
  payroll") is not projected at all.
- Foreign-currency events convert at the rate dated on settlement.
- `amount_safe_to_pay` and `earliest_date_for_full_payment` are always computed
  **before** optional spending changes; changes may only make a *plan* viable.

## Models

| Role | Model | Why |
| --- | --- | --- |
| Orchestrator + vision | `qwen/qwen3.8-27b` | Tool calling and images in one model, at ~30–66 output tokens per turn |
| Orchestrator (alternate) | `openai/gpt-oss-120b` | Requests alternate across both by `request_id` hash, so the two token buckets add up; also the escalation target after two validator rejections |
| Message resolution | `openai/gpt-oss-20b` | Strong on bilingual payroll notices, and kept on its own bucket because its 2000-token ceiling is expensive against TPM |
| Injection screening | `meta-llama/llama-prompt-guard-2-86m` | Purpose-built, 14,400 requests/day |
| Embeddings | `all-MiniLM-L6-v2` (local) | No API key, no quota, runs on CPU |

`qwen/qwen3.6-27b` is deliberately **not** used: it enforces a hard 1000
output-tokens-per-minute ceiling that rejects any request asking for more, and it
spends roughly 150 tokens per call on reasoning traces that `qwen3.8-27b` does
not need.

## Rate limits shape the design

Measured from `x-ratelimit-*` response headers on this account: about **1000
requests per day per model**, an **8000-token-per-minute** bucket, and the
`qwen3.6` output ceiling noted above. Cost is not the constraint — quota is.

Four consequences, all visible in the code:

1. **Work is routed across models** so the per-model buckets add up instead of
   competing: the orchestrator alternates between two models by `request_id`
   hash (`config.py::orchestrator_pool`), which roughly halves the wall-clock
   time of a full run.
2. **`utils/rate_limiter.py`** paces calls against a sliding 60-second window per
   model and honours the server's own `retry-after` on a 429, turning a burst of
   failures into steady progress.
3. **The deterministic engine needs no API calls**, so `evaluation/calibrate.py`
   can iterate on forecast accuracy for free.
4. **Tools return the picture their evidence produces**, so no turn is spent
   recomputing. `load_context` carries a baseline forecast and ranked plans, and
   `read_receipt` / `resolve_messages` return the updated ones — an evidence-free
   request costs 2 calls, an evidence-bearing one 3 turns rather than 5. The
   conversation is also compacted between turns (`_compact`), since every tool
   result is otherwise resent on each subsequent turn. Receipt OCR is cached by
   `image_id`, and `utils/token_tracker.py` refuses a call once a model's
   allowance is spent rather than failing mid-run.

## Robustness

- Max 4 agent iterations; the loop cannot spin.
- Validation failures are returned to the model for self-correction.
- Transient errors retry with exponential backoff; 429s wait as instructed.
- If the loop cannot finish — budget spent, model unavailable, iterations used —
  the deterministic engine's answer is emitted with a grounded templated
  explanation. Every request gets a valid row.
- A receipt that cannot be read leaves the amount **unknown, never zero**.
- Messages and images are treated as untrusted throughout: screened by regex and
  a classifier, wrapped in `<untrusted_message>` delimiters, and the prompts
  instruct the model to read them for facts while ignoring any embedded
  instruction. Modifications referencing an identifier the model was never shown
  are discarded.

## Determinism

`temperature=0` everywhere, pinned dependencies, sorted iteration, and an
independent validator. The deterministic path (`--no-llm`) is fully
reproducible; the agent path is stable but not bit-identical, since the models
are sampled remotely.
