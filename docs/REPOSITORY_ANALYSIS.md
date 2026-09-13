# September repository analysis and August lessons

Inspected: 2026-09-12. Author: Codex CLI. Scope: September planning and configuration; August is a read-only reference.

## Conclusion

September is still an unimplemented starter. There is no existing financial architecture to refactor. Preserve its contract, dataset, entry-point locations, and logging; build the missing behavior incrementally. August has a useful hybrid pipeline, but its notification decisions, taxonomy, fallback, and output writer cannot be transferred unchanged.

The supplied feedback contains truncated text and a literal “668 lines hidden” marker. This analysis covers the visible feedback and inspected source; it does not reconstruct the missing feedback. Older audit documents are historical claims, not fresh validation results.

## September: what exists now

| Area | Observed state |
| --- | --- |
| Runtime entry point | `code/main.py`, zero bytes |
| Evaluation entry point | `code/evaluation/main.py`, zero bytes |
| Mandatory usage report | `code/evaluation/usage_report.md`, zero bytes |
| Requirements | Root `AGENTS.md`, `README.md`, and `problem_statement.md` |
| Application modules / prompts / tools / tests | Not present |
| Claude instructions | `CLAUDE.md` originally imported only `AGENTS.md` |
| Claude local settings | Existing PowerShell permissions, including temporary-script paths; preserved |
| Generated submission | No root `output.csv` or `code.zip` |
| Smoke run | `py -3.12 code/main.py` exits successfully without output |

Python 3.12 is available through `py -3.12`; the `python` alias did not run in this sandbox. Installed Claude Code reports version 2.1.269. These are observations about this machine, not deployment prerequisites to hardcode.

## September data inspection

| File | Rows | Principal join |
| --- | ---: | --- |
| `requests.csv` | 250 | `request_id`, `user_id` |
| `sample_requests.csv` | 25 | Public examples, separate request IDs |
| `financial_profiles.csv` | 275 | `user_id` |
| `financial_events.csv` | 25,342 | `event_id`, `user_id`, `linked_event_id` |
| `request_payment_options.csv` | 790 | `request_id`, `payment_option_id` |
| `messages.csv` | 215 | `user_id`, optional `request_id` and `related_event_id` |
| `images.csv` | 16 | `image_id`, `user_id`, `request_id`, `related_event_id` |
| `exchange_rates.csv` | 134 | Date and directed currency pair |
| `output.csv` template | 250 | Evaluation request IDs; prediction fields blank |

Measured structural checks passed: unique combined evaluation/sample request IDs, unique event IDs, profile coverage for requests, linked-event existence, image-file existence, two-to-four options per request, settled foreign-event rate coverage, and output-template ID alignment. This is not a semantic audit of every financial record or image.

Important characteristics:

- All 16 blank event amounts have linked image files: **15 debits and one credit**. Treating unreadable images as zero would under-reserve obligations.
- There are 176 messages without a direct event link. All 215 messages currently belong to different users. User-scoped retrieval is sufficient at this size; TF-IDF or a vector database has no demonstrated need. Do not bake the one-message-per-user observation into an API assumption.
- Events include 25,148 settled, 71 pending, 70 scheduled, 22 cancelled, 21 failed, and 10 unrealized records. There are 140 foreign-currency events.
- Combined request dates span 2019-09-03 through 2026-09-04. The challenge date is not the financial evaluation date.
- Payment options contain only `full_payment` and `installments`; partial payment is permitted separately by the request and profile contract.
- Supplied installment offers can reach 24 payments. Of all options, 428 installment schedules end more than 90 days after the request, while the largest request deadline offset is 86 days. An available offer is often ineligible; reject offers that miss the deadline instead of truncating their schedules.
- All supplied option amounts currently satisfy `payment_amount * number_of_payments == total_payable_amount` using decimal arithmetic. Validate this at runtime, rather than silently repairing an inconsistent offer.
- There is no September `message_type`, `action`, `confidence`, `message_history.csv`, or `evidence_message_ids` output column.

Observed taxonomy:

- Request types: `purchase`, `travel`, `education`, `family_transfer`, `debt_repayment`, `investment`, `housing`, `emergency_expense`, `other`.
- Event types: `debt_payment`, `expense`, `income`, `investment_purchase`, `investment_sale`, `investment_valuation`, `refund`, `subscription`.
- Cash directions: `credit`, `debit`, `non_cash`.
- Flexibility: `fixed`, `reducible`, `reducible_or_stoppable`, `stoppable`.
- Source types: `bank`, `employer`, `financial_service`, `merchant`, `service_provider`.
- Event categories: `cloud_storage`, `debt_repayment`, `delivery_membership`, `dining`, `education`, `entertainment`, `family_support`, `groceries`, `gym`, `healthcare`, `housing`, `insurance`, `investment`, `music_subscription`, `rent`, `salary`, `shopping`, `streaming`, `transport`, `utilities`, `windfall`, `work_expense`.

Derive event-category validation from supplied data and profile category lists. The inventory above documents this checkout; it must not become request-specific prediction logic.

## August: actual architecture

Reference root: `D:/Project/AugustOrchestrate/hackerrank-orchestrate-august26`.

```text
code/main.py
  DataStore.load → select/render few-shot examples
  for each incoming message:
    build_context → image/voice understanding → extract_signals
    deterministic phishing gate OR trim_candidates → run_reasoner
    validate → serialize row
  write_output → verify CSV IDs and columns
```

`DataStore` indexes CSV dictionaries. `ContextBundle` and `EvidenceCandidate` are dataclasses. `RouteDecision` is a Pydantic model with literal action/type enums. `reasoner_system.md` carries policy, category precedence, untrusted-content rules, and evidence instructions. Claude returns a structured decision; AssemblyAI handles audio. These are fixed pipeline calls, not a model-selected investigative tool loop.

`evaluation/evaluate.py` selects examples not included in the few-shot block, invokes the router, and computes action/type accuracy, macro-F1, evidence P/R/F1, and confidence Brier score. Its iteration journal records prompt revisions and model comparisons on that same evaluation pool.

## Findings connected to evaluator feedback

Paths below are relative to the August reference root.

| Finding | Source evidence | September consequence |
| --- | --- | --- |
| Citation existence was already partly guarded, but claim support was not | `code/router/validator.py:14` filters evidence IDs without rebuilding `reason` | Preserve candidate membership; also bind every material claim to validated facts and regenerate dependent prose after rejection |
| Gate evidence can be loosely related | `code/router/safety_gates.py:27` accepts any reported/muted candidate, or the same business/sender | Source existence and shared user are necessary but insufficient; require claim-level relevance |
| Evidence ordering does not match its recency description | `code/router/context_builder.py:68` sorts timestamps ascending | Make sorting explicit, stable, and covered by tests; apply explicit amendments before general recency |
| No historical-time cutoff in candidate construction | `code/router/context_builder.py:39` excludes the current ID but does not filter future timestamps | Separate evidence available as of the request from future scheduled cash flows already confirmed in that evidence |
| Output enums exist, but intermediate taxonomy is permissive | `code/router/schema.py:46` uses literals; `code/router/media/image_understanding.py:41` uses a free string with a descriptive list | Validate intermediate financial facts and category mappings, not only CSV enums |
| Contradiction checks depend on prompting | `code/router/validator.py:14` has no action/type/reason consistency check | Make decisions and rationales derive from the same verified financial calculation |
| Retries do not implement explicit operational budgets | `code/router/reasoner.py:186` immediately retries all exceptions; client construction does not set a project timeout | One retry policy, classified errors, bounded backoff, deadlines, and usage accounting; account for SDK retries too |
| Cache identity is too weak for reproducible changed inputs | `code/router/media/cache.py:13` keys by kind and media ID | Key financial extraction cache by content hash, model, prompt, and schema versions |
| Global fallback is a notification-specific choice | `code/router/validator.py:24` always returns digest/unknown | Missing debit evidence must not become approval; retain only facts and capacity already proved |
| Write verification occurs after replacing the destination | `code/router/output_writer.py:14` writes directly, then uses `assert` | Validate in memory, write a temporary file, re-read with explicit exceptions, then replace atomically |
| Reported holdout was reused during iteration | `code/evaluation/evaluate.py:36` excludes demonstrations, but `code/evaluation/eval_journal.md` records repeated tuning/model comparison | Separate development from final reporting and disclose prior sample exposure |
| September output path differs | `code/router/config.py:31` defaults to `dataset/output.csv` | September must generate root `output.csv` and leave input data untouched |

The August audit reports action accuracy 0.920 and evidence F1 0.526. Those are historical reported numbers, not September results or independently reproduced measurements. An attempted read-only run of its three DND tests failed during import because this Python environment lacks `pydantic`; no tests reached execution. No paid August evaluation was launched.

## Reuse judgment

Carry forward the ideas of indexed loading, a typed context bundle, untrusted multimodal extraction, pure deterministic logic, structured model boundaries, per-row failure isolation, and exact-schema writing. Audit any copied utility independently. Do not copy notification taxonomy, phishing heuristics, audio support, automatic digest fallback, old model IDs/pricing, dataset-output paths, or sample-specific tuning.

For September, the model should primarily extract financial facts from messages/images. Deterministic code should resolve conflicts, forecast cash, compare payment plans, validate evidence, and render explanations. This places the most consequential behavior in code that can be tested and explained.

## Configuration basis

The root `CLAUDE.md` continues importing `AGENTS.md`; Claude-specific role instructions live below that import. This matches the documented [Claude memory/import mechanism](https://code.claude.com/docs/en/memory). Shared project settings belong in `.claude/settings.json`; machine-local settings remain separate, following [settings scope documentation](https://code.claude.com/docs/en/settings).

The project setting uses `Edit(/dataset/**)` to protect input files through Claude's file tools. `Edit` covers built-in file editing, including Write; a path-specific `Write(...)` rule is not the documented mechanism. This is not a filesystem sandbox for arbitrary Python subprocesses, so dataset hashes and writer path validation remain required. See [Claude permissions](https://code.claude.com/docs/en/permissions).
