# September implementation plan

Status: proposed for Claude review; application implementation has not started.

Owner: participant. Planner/reviewer: Codex CLI. Implementer: Claude Code.

## 1. Objective and scope

Produce a runnable, explainable Buy or Wait? submission that follows `AGENTS.md` section 6 and `problem_statement.md`. Improve the weaknesses visible in August feedback: evidence support, taxonomy alignment, rationale consistency, operational bounds, and credible evaluation.

Read `docs/REPOSITORY_ANALYSIS.md` before implementation. September's three Python/report files are empty; the proposed modules below are new responsibilities, not a description of code that already exists. Re-inspect the repository at the start of each milestone in case another session has added working code. Adapt these responsibilities to existing modules instead of creating duplicates.

Keep the solution a Python batch CLI. Start with the standard library for CSV, dates, Decimal, dataclasses, hashing, JSON, and tests. Add one structured model/vision provider and a schema library only where useful. No web application, vector database, audio pipeline, live finance data, or multiple model providers are required. Do not pick model IDs or prices from the August source without current provider verification.

## 2. Architecture and ownership

```text
participant CSVs + image bytes
  → validated indexed dataset
  → request-scoped evidence candidates
  → structured message/image fact extraction
  → category alignment + provenance checks + conflict resolution
  → baseline financial state + conservative 90-day cash-flow projection
  → eligible full/partial/installment/wait/spending-change candidates
  → deterministic feasibility + ranking
  → decision + structured supporting facts
  → coherence/provenance validation → deterministic explanation
  → exact CSV + audit trace + final-run usage report
```

Model output is proposed evidence, never authority to change the financial contract. The deterministic planner owns money, eligibility, dates, status, method, schedule, and spending changes. A second model judging the first model's rationale is not the primary validation mechanism.

Suggested placement; consolidate further if responsibilities stay clear:

| Location | Responsibility |
| --- | --- |
| `code/main.py` | CLI, one request loop, row failure isolation, final artifact coordination |
| `code/buy_or_wait/schema.py` | Output constants and small typed records |
| `code/buy_or_wait/data.py` | Strict loaders, indexes, file manifest, typed parsing |
| `code/buy_or_wait/evidence.py` | Scoped retrieval, source registry, extracted fact validation, category alignment, conflict decisions |
| `code/buy_or_wait/model.py` | Structured extraction/vision, bounded tool dispatch, content cache, retries, budgets, usage |
| `code/buy_or_wait/forecast.py` | Cash-state reconstruction, recurrence, FX, time-ordered balances |
| `code/buy_or_wait/planner.py` | Candidate schedules, permitted spending adjustments, ranking |
| `code/buy_or_wait/validation.py` | Evidence/decision coherence, independent plan replay, output invariants |
| `code/buy_or_wait/output.py` | Explanations from verified facts, CSV serialization, atomic publication, audit serialization |
| `code/prompts/` | Versioned extraction policy and bounded tool descriptions |
| `code/evaluation/main.py` | Public-sample evaluation, baseline comparison, run reports |
| `code/tests/` | Targeted offline tests and synthetic fixtures |

This is a maximum initial decomposition, not a quota of modules. Prefer one understandable function over a framework or inheritance hierarchy.

## 3. Contracts to establish before model calls

Define only records needed by the first milestone, then extend them:

- `RequestContext`: request/profile plus scoped events, messages, images, and seller options. Retain the supplied request date.
- `EvidenceRef`: source kind, real source ID or composite CSV key, user/request scope, relevant field or text span, and availability metadata. FX references use `(rate_date, from_currency, to_currency)`; do not invent an FX row ID.
- `ExtractedFact`: field, typed proposed value, currency/date when relevant, supporting evidence references, target event or explicit user-level fact, and validation state. Unknown stays distinct from zero.
- `ResolvedState`: accepted financial facts, excluded/superseded records and reasons, recurrence provenance, and unresolved material uncertainties.
- `Forecast`: dated cash movements, minimum-balance checks, bottleneck dates, baseline safe capacity, and earliest full-payment date.
- `PlanCandidate`: method, schedule, seller option if applicable, total payable, spending actions, supporting fact references, and eligibility/feasibility results.
- `DecisionRecord`: the eight CSV fields plus internal proof facts and audit flags. Extra internal fields never become CSV columns.
- `RowTrace`: retrieved IDs, extraction results, conflict decisions, selected and rejected plans, validation failures, retries/fallbacks, cache provenance, and usage ledger references.

Money uses `Decimal` parsed directly from source strings; reject NaN, infinity, malformed values, and invalid negative amounts. Specify currency precision/rounding based on the supplied amounts and output contract. Never round an affordable amount upward or change a seller's installment schedule to hide arithmetic errors.

## 4. Evidence and category safeguards

### Retrieval and time scope

Index by real keys and retrieve the user's relevant records. Include direct request/event links and relevant user-level messages when `related_event_id` is blank. A blank link means no one-to-one supplied event, not irrelevant evidence. Do not create fake event IDs for new user-level facts.

Check linked records remain in the same user scope. Apply the request scope to records that have a request ID; do not leak another request's evidence just because the user matches. Evidence available only after the request cannot justify a historical decision. Future scheduled events can be forecast when already supplied/confirmed; their future settlement date does not itself make them unavailable evidence. Messages have timestamps but requests have dates only: document a consistent date cutoff and do not invent a user timezone.

The current messages are one per user, so start with direct joins and pass all relevant message candidates. Keep material financial events available to the deterministic engine even when the model sees a compact subset. Never rank essential obligations out of the forecast to reduce tokens.

### Auditable facts and citations

1. Build the candidate/source registry deterministically before extraction.
2. Model responses reference only candidate handles supplied by the application; resolve handles to actual IDs in code.
3. Check each referenced source exists, was retrieved for this request, has the right scope, and supports the claimed field. A real ID is not proof of relevance.
4. Preserve a text span or image transcription/field location for extracted facts. For multilingual text, preserve the original supporting span alongside normalized values.
5. For structured CSV facts, validate the cited field/value directly. For extracted semantics, reject unsupported amounts/dates or ambiguous amendments; retain uncertainty rather than claiming a deterministic proof of arbitrary natural-language meaning.
6. Resolve conflicts with explicit cancellation/settlement/amendment first, then newer same-source evidence, then settled evidence, then the safer interpretation. Preserve why records were accepted and rejected.
7. Render each material explanation claim from accepted fact records. Include relevant `message_id`/`image_id` inline in `decision_explanation` when such evidence changes the result. Use event IDs for event-based claims. Do not add an August-style evidence column or force a message citation when none supports the decision.
8. If an evidence check fails, invalidate dependent claims, recompute state and plan, and regenerate the explanation. Never remove an ID while retaining the assertion it supposedly supports.

An audit JSONL sidecar under `code/evaluation/runs/<run_id>/` records the full derivation; keep the CSV explanation concise. Do not dump raw private configuration or entire provider exceptions into it.

### Taxonomy alignment

September messages have `source_type`, not `message_type`. Preserve source types and request types from their structured columns. Validate financial event categories against the dataset/profile vocabulary. Prefer the directly linked event category; use a small explicit alias mapping only for unambiguous paraphrases. Ambiguous mappings remain internal unresolved facts and cannot authorize spending cuts. Do not silently map unknown categories to `other`, protect everything by default, or import August's scam/spam taxonomy.

Spending eligibility requires the event's flexibility, the user's permitted stop/reduce category, recurrence evidence, and lack of protection. Model agreement alone is insufficient.

## 5. Financial engine and plan correctness

### Baseline state and forecast

- Start from `current_available_balance`. Historical settled events provide recurrence and context; do not replay them onto a balance that already represents current cash.
- Count every real future cash movement once. A lifecycle link is not a generic duplicate marker; distinguish representation updates from separate purchase and sale cash flows. Validate missing/cross-user/cyclic links.
- Reserve pending debits once; exclude pending credits, failed/cancelled events, non-cash/unrealized values, and uncertain windfalls. Ignore unconfirmed bonuses/refunds/investment gains until settled. Apply confirmed income on the supported settlement date.
- Infer recurring salary/expenses only from supporting history and relevant amendments. Avoid projecting seasonal contracts indefinitely or inventing income after a cancellation. Document recurrence thresholds and conservative variable-essential forecasts using development examples and synthetic cases.
- Convert a foreign cash event with the supplied settlement-date rate in the stated direction. Missing rates are unresolved data, never a reason to call a live FX API or guess a reciprocal.
- Use a documented 90-day interval anchored to `request_date`, including boundary tests. Specify intra-day ordering conservatively when no times exist; check balances after each essential movement/payment, not only month-end. Avoid double-counting pending reserves when a payment later settles.

For a complete baseline ledger, today's safe amount is the requested amount capped by the nonnegative minimum available headroom over the full forecast. A tentative formula is `min(requested_amount, max(0, min_t(balance_before_new_request(t) - minimum_balance)))`; use it only after verifying all baseline prefixes and reserves. If required debit information is missing and cannot be conservatively bounded, it cannot certify a positive safe amount.

For earliest full payment, search candidate dates chronologically with the complete safety check, including baseline feasibility before that date. Compute it without optional spending changes and independently of payment-method preferences. Do not report the end of an installment plan as the earliest date for a single full payment.

### Candidate generation and selection

- Full payment: require user acceptance and sufficient capacity. A payment safe only after permitted spending changes must be `affordable_with_plan`, not `affordable_now`.
- Partial payment: request allows it, user accepts it, and `0 < amount_safe_to_pay < requested_amount`. Exactly two payments: baseline safe amount on the request date and remainder on the baseline earliest full-payment date. The second date must meet the desired deadline. Independently replay both payments.
- Installments: use one supplied offer, preserving first date, payment count, frequency in days, fees, and total payable. Check the user's preferences, term limit, and completion deadline. Never truncate a long offer to fit the forecast or treat a 30-day cadence as calendar-month arithmetic. Specify how `max_installment_months` is interpreted and verify against development examples; do not assume count alone measures duration for arbitrary day intervals.
- Wait: require accepted full payment and a later safe full-payment date. Respect the deadline when recommending completion; a capacity date after the deadline can still be reported as capacity but does not make a late plan eligible.
- Spending changes: evaluate only future eligible recurring flexible events, at most three distinct actions. Honor `minimum_allowed_amount`; never stop and reduce the same event. Generate a bounded, documented set of reductions/stops from allowed amounts and the calculated shortfall, then replay the full forecast. Do not silently claim exhaustive optimization if the search is heuristic.
- Rank safe eligible plans using the specified order: completion by deadline, no spending changes, lowest total cost, earlier start, fewer payments, then lowest payment option ID. Define stable identifier ordering and test ties without depending on input row order.
- No safe eligible payment: use the contract's fallback method, explaining whether the obstacle is financial capacity, deadline, preference, or unresolved evidence. Do not manufacture an unsupported future date.

### Coherence and failure handling

Validate the decision's numeric facts, status, method, schedule, earliest date, spending actions, and cited claims together. Generate explanations from validated templates with fact references; avoid free-form advice that can contradict the planner. A syntactically valid model reply is not a valid decision.

When extraction fails, keep any independently verified baseline facts. Missing optional evidence should not destroy a complete calculation; missing a material unbounded debit should prevent approval. If no safe capacity can be established, emit a conservative schema-valid row with zero safe payment, no payment plan, and an explanation that evidence was insufficient to establish affordability. Mark the internal row as degraded, not a proved financial rejection. Do not count degraded rows as successful verified decisions.

Dataset-level failures such as missing required CSVs, duplicate evaluation IDs, or incompatible headers should fail the run clearly before publication. Per-row recoverable evidence/API failures may produce audited conservative rows. Unexpected programming errors must be prominent in the run summary and prevent a false claim of a clean final run.

## 6. Bounded model capabilities and runtime controls

Give the extraction model a small, real, read-only tool interface if it needs additional investigation:

| Capability | Model-facing description | Enforcement |
| --- | --- | --- |
| `get_evidence` | Inspect supplied message/event/image metadata by a candidate handle when a claim needs clarification | Handle must belong to the active request; return original source refs |
| `inspect_event_chain` | Inspect related records to distinguish amendment, cancellation, settlement, or separate cash movements | Same-user links only; visited set and traversal cap |
| `read_image` | Read a linked image when a financial field is missing or image evidence resolves a conflict | Resolve only an existing dataset image; hash and cache; charge vision usage to the same budget |

The application binds request/user scope; the model cannot supply a different user or arbitrary filesystem path. Responses are data, not executable instructions. No browser, shell, payment execution, arbitrary SQL, or remote finance tools. If a direct structured extraction already has sufficient context, skip tool turns. These capabilities should wrap tested functions, not require an agent framework. Test the dispatcher and its denied cases; documentation alone does not constitute implemented tools.

Use one provider-call wrapper for extraction and vision. Configure explicit call timeout, per-row elapsed-time/call/token limits, and a full-run budget. Candidate starting limits for Claude to test are 60 seconds per row, three provider attempts total per row including vision/repair/retries, and a bounded tool-turn count. They are engineering defaults to validate, not measured performance or permission to incur costs now.

Use a monotonic deadline and pass remaining time to every external call. Retry only transient failures with bounded exponential backoff and bounded `Retry-After`; stop when the next attempt cannot fit. Permit at most one structured-output repair with explicit validation errors, inside the same budget. Do not retry authentication/configuration errors. Disable or account for SDK retries so layered retries cannot multiply calls unnoticed.

Before a paid run, set a documented monetary cap and verified provider/model pricing in configuration; do not invent current prices. If pricing is unavailable, report cost as unavailable and do not claim a hard dollar cap is enforced. Token/call/time limits remain enforceable independently.

Cache validated extraction by source-content hash, model ID, prompt version/hash, schema version, and relevant request/date context. Media identity alone is insufficient. Include original extraction run provenance; reject corrupt/stale cache entries. Record cache hits separately from billed calls.

Capture all provider-reported input/output tokens plus cache-read/write categories where applicable, failures with available usage, model/provider, stage, latency, retry count, and attributed request IDs. Avoid double-counting cache tokens according to the verified provider usage schema. Account for shared extraction once overall, with a documented per-request allocation. If usage is unavailable on an interrupted attempt, record that limitation instead of zeroing an unknown charge.

## 7. Evaluation and targeted tests

### Honest evaluation split

There are only 25 public solved examples. Before prompt tuning, create a stable split manifest using a documented fixed hash/seed and request/user IDs: proposed 10 development and 15 reporting examples, with no overlapping users. Demonstrations and tuning may use development examples only. Pass only request input columns to prediction code; keep expected output fields in the evaluator. The inference loader must not read sample labels or organizer-only files.

Public examples are not hidden ground truth, and prior agents may already have read them. Label final numbers as performance on a fixed public-sample reporting subset with disclosed exposure, not an unbiased hidden-test estimate. If reporting failures drive a fix, retain the previous result and label the revised score as post-inspection. Do not repeatedly tune on the reporting subset and keep calling it untouched.

Build a deterministic-only baseline using the same planner and supplied structured data, with the same explicit conservative handling of unresolved evidence and no model calls. Compare it with the evidence-assisted version on the identical frozen subset. An optional additional ablation can reuse fixed validated extraction to isolate planner changes; do not confuse that with the no-model baseline.

Report amount MAE and exact match per currency (raw INR and USD errors must not be averaged together), normalized amount error with zero-request handling, status/method accuracy and confusion counts, exact normalized schedule agreement, date agreement/error for valid pairs, spending-action validity, plan safety failures, citation validity and claim coverage, degradation rate, calls/tokens/cost, and latency. Report numerator/denominator and run configuration. Do not invent gold evidence precision/recall where September has no labeled evidence column; use deterministic provenance checks and a documented manual claim audit.

### Required targeted behaviors

| Test group | Essential cases |
| --- | --- |
| Loading | Exact headers, duplicate IDs, missing required CSV, invalid Decimal/date/enum, shuffled input, path outside dataset, no labels passed to inference |
| Retrieval | Same user/request, blank event link retained, future evidence excluded, known future settlement retained, fabricated/unretrieved/wrong-user ID rejected |
| Claim support | Real but irrelevant ID rejected; invalid citation removes dependent claim and triggers recomputation; structured field/value matches; multilingual span retained |
| Images | Missing amount never zero; unreadable debit blocks unsupported approval; unknown credit excluded; absent file; stale cache; malformed extracted amount |
| Injection/taxonomy | Embedded instructions cannot change preferences/schema; invented category rejected; ambiguous mapping cannot enable a cut; legitimate financial amendments remain usable |
| Cash state | History not replayed; pending debit reserved once; pending credit excluded; settlement deduplication; investment purchase/sale both handled; unrealized gain excluded |
| Recurrence/FX | Unsupported salary not extrapolated; cancelled/seasonal income stops; variable essentials reserved; directed date-specific FX; missing rate; cycle/cross-user link |
| Forecast | Later essential bill blocks payment today; exact minimum boundary; debit/credit same date; request-date and day-90 boundary; baseline breach before proposed pay date |
| Plans | Preference rejection; exact two-part schedule; fee-bearing installments; full supplied schedule; overlong term/deadline; earliest date independent of method; deterministic tie |
| Spending | Protected/fixed/nonrecurring events rejected; category permissions; minimum reduction floor; stop/reduce conflict; maximum three actions; safe amount remains pre-change |
| Coherence | Unsupported affordable-now rejected; unsafe schedule rejected; funded-after-cut wording correct; wait reason agrees with date; no citation padding or fabricated future date |
| Resilience | Fake-clock timeout/backoff; no retry on auth error; tool/call/token budget exhausted; retry/vision usage counted; optional versus material evidence failure |
| Output/evaluation | Eight exact columns; unique complete request set; CSV quoting/non-ASCII; no output inside dataset; partial file not published; audit/usage/output run IDs match; split isolation |

Tests must be offline by default with synthetic fixtures, fake providers, and controllable clocks; do not require live keys just to import the financial engine. Use a small independent balance replay oracle or hand-computed fixtures for critical plan safety, rather than testing a function against itself. Add a metamorphic check that an extra protected debit cannot increase safe capacity.

Proposed commands, to become runnable as their milestones land:

```text
py -3.12 -m unittest discover -s code/tests -p "test_*.py"
py -3.12 code/main.py --mode deterministic --out code/evaluation/baseline.csv
py -3.12 code/evaluation/main.py --split dev --mode deterministic
py -3.12 code/evaluation/main.py --split report --compare-baseline
py -3.12 code/main.py --mode assisted --out output.csv
```

Provide equivalent `python` commands for portable setup. CLI flag names are proposed, not currently implemented. No September tests/evaluation currently exist to pass.

## 8. Implementation milestones and review evidence

| Milestone | Deliverable | Completion evidence |
| --- | --- | --- |
| M0: contract and measurement | Loaders, schemas, dataset audit, split manifest, CLI skeleton, test harness | Fixture tests pass; required input hashes recorded; no sample labels enter prediction context |
| M1: deterministic baseline | Cash-state reconstruction, recurrence/FX, forecast, basic full/wait/fallback, atomic eight-column output | Hand-computed cash-flow tests pass; one conservative row per evaluation request; baseline report saved |
| M2: evidence | Scoped retrieval, extraction/vision, taxonomy/provenance/conflict validation, cache, bounded calls/tools | Fake-provider and injection tests pass; all missing amounts either supported or explicitly unresolved; material-uncertainty cases cannot approve |
| M3: complete plans and explanations | Partial/installment/spending candidates, ranking, independent replay, claim-derived explanation | Schedule/preferences/protected-expense tests pass; invalid supporting facts cannot survive in explanation |
| M4: credibility and package | Frozen comparison, final run ledger, usage report, setup docs, package validation | Final artifact IDs/hashes match; zero structural/evidence/plan-safety violations; degradations disclosed; clean extraction smoke run |

Claude reviews this plan first, records any material changes with rationale, and implements the next coherent milestone. Each milestone includes its necessary tests before handoff. It does not need user confirmation for routine implementation choices within an authorized milestone. The agreed review boundary is a completed milestone, not every file edit. The participant may batch milestones explicitly if time requires.

After each handoff Codex reviews the actual diff, reruns applicable checks, traces representative decisions, and records severity-ranked findings. Claude fixes confirmed findings with regression tests. Do not change architecture just to satisfy an unverified review opinion. The participant decides substantive tradeoffs and remains able to explain the code.

Prioritize correctness over extra features. Reserve the final two hours before the challenge deadline for full-run validation and packaging; shrink optional features if necessary. Do not remove evidence validation, financial safety checks, or usage accounting to gain time. No promise about implementation duration is implied by this plan.

## 9. Submission completion definition

- Root `output.csv` has the exact eight specified columns and one row for every evaluation request; all decisions pass deterministic structural and safety validation or are explicitly audited conservative degradations.
- `dataset/` and the August reference remain unchanged; file hashes confirm input preservation.
- `code.zip` contains the runnable code package with README, required prompts/config, and `evaluation/usage_report.md` at the archive root's evaluation path. Do not accidentally nest it as `code/evaluation/usage_report.md` inside the archive.
- The usage report corresponds to the final full-dataset run: provider/model, calls, input/output/cache tokens with defined accounting, total/average tokens, estimated total/per-request cost, and uncertainty where applicable. Do not replace the empty placeholder with invented values before that run.
- Trace/run manifest links output hash, input hashes, code/prompt/config versions, split manifest, usage ledger, and cache provenance. Count only actual calls in that run; separately disclose previously billed cached extraction used to produce it.
- Package from an explicit allowlist. Exclude secrets, local settings, virtual environments, old outputs, and transcript logs from the code archive unless specifically required. Keep the transcript as its separate required artifact.
- Verify setup and a smoke run from a clean extracted package with a supplied dataset location. Record all commands, failures, fixes, and limitations in the handoff and shared log.
