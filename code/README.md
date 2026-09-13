# Buy or Wait? — AI-powered financial affordability agent

For each of the 250 requests in `dataset/requests.csv`, this agent reconstructs
the person's forward cash position from their profile, their financial-event
history, dated exchange rates, the seller's payment options, and any supporting
messages or receipt images — then decides whether to pay in full, pay part now,
take an installment offer, wait, or not proceed, and writes `output.csv`.

---

## 1. Setup

### Requirements

- **Python 3.11 or newer** (developed on 3.11.5; the code uses `X | Y` type
  syntax and `datetime.date` arithmetic only, no OS-specific calls).
- A **Groq API key**, for the model-backed paths. The deterministic path
  (`--no-llm`) needs no key and no network.
- Roughly 400 MB of disk for `sentence-transformers` + `faiss-cpu`, which run
  the few-shot retriever locally.

### Install

From the **repository root**:

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r code/requirements.txt
```

All dependencies are pinned in [requirements.txt](requirements.txt).

### Configure

Create a `.env` file at the **repository root** (never inside `code/`, never in
git):

```
GROQ_API_KEY=your_key_here
```

`GROQ_API_KEY` is the only setting. It is read from the process environment via
`pydantic-settings`, so exporting it in the shell works identically:

```bash
export GROQ_API_KEY=your_key_here
```

Nothing else needs configuring. Every path in [config.py](config.py)
resolves from the file's own location up to the repository root, so the agent
finds `dataset/` and writes `output.csv` correctly **from any working
directory**. No key is ever logged, printed, or written to the usage report.

### Verify the install

```bash
cd code
python tests/test_financial_rules.py      # 49 checks, no API calls, no network
python main.py --no-llm --limit 5         # end-to-end, no API calls
```

If both succeed, the environment is correct. Only then is an API key needed.

---

## 2. Run

```bash
cd code
python main.py                        # every request -> output.csv
python main.py --lean                 # evidence tools + deterministic engine
python main.py --no-llm               # deterministic engine only, zero API calls

python main.py --limit 10             # first 10 requests
python main.py --request-id request_42
python main.py --samples              # the 25 labelled samples instead
python main.py --resume               # continue after an interruption
python main.py --replay               # with --lean: reuse cached evidence, 0 tokens
python main.py --workers 3            # requests in flight at once (default 3)
python main.py --no-rag               # skip local few-shot retrieval
python main.py --output path.csv      # override the output path
python main.py --verbose              # per-request structured logs
```

### Three engines, one pipeline

| Mode | What runs | Tokens/request | When to use |
| --- | --- | --: | --- |
| default | full orchestrator tool-calling loop | ~10,000 | when the daily token budget allows |
| `--lean` | receipts + message resolution, then the deterministic engine | ~1,600 | a full 250-request run inside one day's quota |
| `--no-llm` | deterministic engine only | 0 | calibration, regression checks, offline runs |

`--lean` exists for a measured reason. On the labelled samples, resolving payroll
messages moved `recommended_payment_method` from 73% to 91%; the orchestrator's
multi-turn routing sat on top of that, costing about four extra calls per request
without moving the score. Lean mode keeps the evidence work — receipts are still
read by the vision model, messages still resolved — and hands the decision to the
deterministic engine, which needs no tokens at all. A request with no messages
and no missing amounts costs nothing whatsoever, because there is no evidence for
a model to interpret.

Requests are processed concurrently because the rate limits below are *per
model* and the orchestrator alternates across a pool of them, so concurrent
requests mostly draw on different token buckets. This converts time otherwise
spent waiting on the pacer into throughput without hitting any single model
harder. Rows are collected by their original index and re-sorted before writing,
so output order always follows the dataset, never completion order.

### Outputs

| Path | Contents |
| --- | --- |
| `output.csv` (repo root) | the submission file |
| `dataset/output.csv` | the same rows, filling the provided template |
| `code/evaluation/usage_report.md` | providers, calls, tokens, and cost for the run |
| `code/.cache/checkpoint.jsonl` | one line per completed request |
| `code/.cache/evidence.json` | resolved receipts and message amendments, for free replay |

Every request is checkpointed as it completes — to `checkpoint.jsonl`, or
`checkpoint_samples.jsonl` under `--samples` so the two scopes cannot
contaminate each other — and `--resume` never re-spends API budget on work
already done.

---

## 3. Verify

```bash
cd code
python evaluation/main.py                            # validate output.csv
python evaluation/main.py --against-samples \
    --output /path/to/sample_run.csv                 # and score it
python evaluation/calibrate.py                       # tune the forecast, no API calls
python evaluation/calibrate.py --show request_05     # dump one request's ledger

python tests/test_financial_rules.py   # 49 checks across 13 rule groups
python package.py                      # build ../code.zip for submission
```

`evaluation/main.py` re-checks schema, coverage, enums, ranges, formats,
internal consistency, and re-simulates every recommended plan against the
90-day forecast. The re-simulation replays the evidence each decision was made
with, read from `code/.cache/evidence.json`. Without that replay the check is
evidence-blind — it rebuilds the forecast from the raw CSV rows, misses a salary
a payroll message raised, and reports a breach that never existed. Where a
request's evidence is unavailable the safety result is reported as *unverified*
rather than as a failure.

`evaluation/calibrate.py` scores the deterministic engine against the labelled
samples using no API calls at all, which is what made forecast tuning affordable
under the rate limits described in §6.

`package.py` archives the contents of `code/` so `evaluation/usage_report.md`
sits where the submission expects it, excludes `.env`, caches and virtualenvs,
and refuses to build if anything resembling a credential is present.

---

## 4. Approach

### The core idea: the model never does arithmetic

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

The split is deliberate. The model decides *which* evidence a particular request
needs, judges what that evidence *means*, picks among plans the tools have
already verified, and writes the explanation. Every number comes from a
deterministic tool, and `submit_answer` re-simulates the chosen plan
independently before accepting it — so a reasoning slip cannot produce a plan
that breaches the minimum balance. If validation fails, the specific errors go
back to the model to correct, and after two rejections the request escalates to
a stronger model.

This is why the deterministic engine is not a fallback bolted on late: it is the
same engine the agent path calls through its tools. The LLM's contribution is
narrow and auditable — evidence interpretation and explanation — which is
exactly the part where the rules are ambiguous and a model helps.

### Reconstructing the cash position

1. **Load and index** all nine dataset CSVs into typed Pydantic models
   (25,342 events, 275 profiles, 790 payment options, 215 messages, 16 images).
2. **Classify each event's cash state.** `cancelled` and `failed` rows never
   move money. `non_cash` / `unrealized` investment valuations are not cash.
   Pending **debits** are reserved; pending **credits** are ignored until they
   settle, as are unapproved bonuses, commissions on open deals, and refunds in
   flight.
3. **Detect recurrence from history only**, grouped by `(direction, category)`
   rather than description — variable essentials arrive under many labels
   ("Local market purchase", "Fresh food shop") but are one economic series. A
   confirmed future salary also counts as evidence of cadence. Observed gaps are
   snapped to real rhythms: weekly, fortnightly, or calendar-monthly on the same
   day-of-month.
4. **Project forward 90 days.** Income projects at its most recently confirmed
   figure; variable spending at its mean, conservatively. A series whose latest
   row is described as final ("Final employer payroll") is not projected at all.
5. **Convert foreign currency** at the rate dated on the event's settlement date,
   in the stated `from`→`to` direction, with a nearest-date fallback.

### Deciding

`plan_generator` builds every candidate the request actually permits — full
payment, partial payment, each supplied installment option — filters them
against the user's `payment_methods_user_will_consider` and
`max_installment_months`, simulates each one against the forecast, discards any
that would drop the balance below `minimum_balance_to_keep` on any day, and
ranks the survivors: completes by the deadline first, then avoids spending
changes, then minimizes total cost, then starts earlier, then uses fewer
payments.

`amount_safe_to_pay` and `earliest_date_for_full_payment` are always computed
**before** optional spending changes. Changes may only make a *plan* viable —
they never inflate the safe amount. `spending_optimizer` searches only
non-protected, flexible events in categories the profile permits, respects each
event's `minimum_allowed_amount`, and proposes at most three actions.

### Untrusted evidence

Messages and images are treated as hostile input throughout. Each is screened by
regex and by a purpose-built injection classifier, wrapped in
`<untrusted_message>` delimiters, and the prompts instruct the model to read them
for *facts* while ignoring any embedded instruction. A modification referencing
an identifier the model was never shown is discarded. Conflicts resolve in the
order the spec requires: an explicit cancellation, settlement or amendment
first; then the newer record from the same source; then the settled event; then
the financially safer reading.

A receipt that cannot be read leaves the amount **unknown, never zero** — a zero
would silently make an unaffordable request look free.

### Module map

| Path | Responsibility |
| --- | --- |
| `main.py` | CLI, concurrency, checkpointing, output writing |
| `config.py` | Settings from env, model ids, pricing, path resolution |
| `agents/orchestrator.py` | The tool-calling loop, tool dispatch, escalation, fallback |
| `agents/lean_runner.py` | Evidence tools + deterministic engine, the low-token path |
| `agents/prompts.py` | System prompts and the seven tool schemas |
| `tools/dataset_loader.py` | Load and index all nine CSVs into typed models |
| `tools/balance_forecaster.py` | Recurrence detection and the 90-day simulation |
| `tools/plan_generator.py` | Candidate plans, eligibility, safety, ranking |
| `tools/spending_optimizer.py` | Permitted stop/reduce search |
| `tools/decision_engine.py` | Deterministic end-to-end solver and fallback |
| `tools/message_resolver.py` | Messages → typed event modifications |
| `tools/image_extractor.py` | Receipt OCR, cached by `image_id` |
| `tools/exchange_converter.py` | Dated FX with nearest-date fallback |
| `tools/evidence_cache.py` | Records resolved receipts and amendments for free replay |
| `tools/safety_gate.py` | Prompt-injection screening and delimiting |
| `tools/retriever.py` | Local FAISS few-shot and series matching |
| `validators/schemas.py` | Pydantic models for every boundary |
| `validators/output_validator.py` | Seven check groups plus safety re-simulation |
| `utils/llm_client.py` | Groq access, structured output, retries |
| `utils/rate_limiter.py` | Sliding-window token pacing per model |
| `utils/token_tracker.py` | Usage ledger, budget guard, usage report |
| `utils/logger.py` | Structured logging bound to a request id |

---

## 5. Models

| Role | Model | Why |
| --- | --- | --- |
| Orchestrator | `qwen/qwen3.8-27b` | Tool calling at ~30–66 output tokens per turn |
| Orchestrator (alternate) | `openai/gpt-oss-120b` | Requests alternate across both by `request_id` hash, so the two token buckets add up; also the escalation target after two validator rejections |
| Receipt OCR | `qwen/qwen3.6-27b` | The only other vision-capable model here, so OCR sits on its own daily bucket, away from the text work; its 1000 output-token ceiling is ample for a receipt |
| Message resolution | `openai/gpt-oss-20b` and `openai/gpt-oss-safeguard-20b` | Strong on bilingual payroll notices; split across two buckets because the resolver's 2000-token ceiling is expensive against TPM |
| Injection screening | `meta-llama/llama-prompt-guard-2-86m` | Purpose-built, 14,400 requests/day |
| Policy screening | `openai/gpt-oss-safeguard-20b` | Second-stage check on anything the classifier flags |
| Embeddings | `all-MiniLM-L6-v2` (local) | No API key, no quota, runs on CPU |

`qwen/qwen3.6-27b` is deliberately kept **off** the orchestrator pool: it
enforces a hard 1000 output-tokens-per-minute ceiling that rejects any request
asking for more, and it spends roughly 150 tokens per call on reasoning traces
that `qwen3.8-27b` does not need. It earns its place on receipt OCR only,
where the output is short and the separate bucket is worth having.

`openai/gpt-oss-20b` is likewise kept off the orchestrator pool, and
`gpt-oss-120b` off the resolver pool: sharing a model between two roles
exhausted its daily allowance and was measurably provoking 429s.

---

## 6. Rate limits shape the design

Measured from `x-ratelimit-*` response headers on this account: about **1000
requests per day per model** and an **8000-token-per-minute** bucket, plus the
`qwen3.6` output ceiling noted above. Cost is not the constraint — quota is.

There is a fourth limit the headers do **not** expose: **200,000 tokens per day,
per model**. It surfaces only as a 429 reading
`on tokens per day (TPD): Limit 200000`. At roughly 10,000 tokens per request the
full orchestrator loop needs ~2.5M tokens for 250 requests, which exceeds the
entire account's daily allowance across every model — so a one-day full run has
to go through `--lean`.

Four consequences, all visible in the code:

1. **Work is routed across models** so the per-model buckets add up instead of
   competing: the orchestrator alternates between two models by `request_id`
   hash (`config.py::orchestrator_pool`), which roughly halves the wall-clock
   time of a full run. The resolver does the same across its own pool.
2. **`utils/rate_limiter.py`** paces calls against a sliding 60-second window per
   model and honours the server's own `retry-after` on a 429, turning a burst of
   failures into steady progress.
3. **The deterministic engine needs no API calls**, so `evaluation/calibrate.py`
   can iterate on forecast accuracy for free.
4. **Tools return the whole picture their evidence produces**, so no turn is
   spent recomputing. `load_context` carries a baseline forecast and ranked
   plans, and `read_receipt` / `resolve_messages` return the updated ones — an
   evidence-free request costs 2 calls, an evidence-bearing one 3 turns rather
   than 5. The conversation is compacted between turns (`_compact`), since every
   tool result is otherwise resent on each subsequent turn. Receipt OCR is cached
   by `image_id`, and `utils/token_tracker.py` refuses a call once a model's
   allowance is spent rather than failing mid-run.

---

## 7. Robustness

- Max 6 agent iterations (`config.py::max_iterations`); the loop cannot spin.
  Four turns is the minimum for an evidence-bearing request — context, resolve,
  forecast + plans, submit — leaving room for one validator correction.
- Validation failures are returned to the model with the specific errors, for
  self-correction; two rejections escalate to `gpt-oss-120b`.
- Transient errors retry with exponential backoff; 429s wait as instructed.
- If the loop cannot finish — budget spent, model unavailable, iterations used —
  the deterministic engine's answer is emitted with a grounded templated
  explanation. **Every request gets a valid row.**
- Concurrency is bounded and checkpointed, so an interrupted run resumes without
  re-spending budget.

## 8. Determinism

`temperature=0` everywhere, pinned dependencies, sorted iteration, and an
independent validator. The deterministic path (`--no-llm`) is fully
reproducible; the agent path is stable but not bit-identical, since the models
are sampled remotely.
