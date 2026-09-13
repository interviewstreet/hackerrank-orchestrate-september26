# Accuracy and evidence improvement handoff

Prepared by Codex CLI, 2026-09-13. Proposed incremental follow-up to the controlling `docs/IMPLEMENTATION_PLAN.md`, not a replacement architecture. Claude implements; Codex reviews. No paid calls were made for this investigation. The existing submission artifacts are preserved.

## Current architecture and measured baseline

The indexed dataset supplies request-scoped contexts. Assisted extraction optionally repairs facts in that context, then uses the same deterministic decision engine as baseline mode. The engine reconstructs cash state, detects recurrence, forecasts, generates eligible plans, validates them, and renders the eight-column CSV. Keep this shared decision path.

The previously frozen, exposed public reporting subset measured status 6/15 and method 8/15 for BOTH assisted and deterministic modes. This is not unseen-data accuracy and does not establish an assisted accuracy gain. Passing 254 existing tests and zero output gate failures do not prove the underlying forecast or evidence interpretation is correct.

`measure_accuracy_gaps.py` inspects inputs and original trace records, not evaluation labels. Its output is `ACCURACY_GAP_MEASUREMENTS.json`. Development diagnostics are limited to the ten frozen development requests.

Measured gaps:

- 189 of 250 evaluation requests have available messages but extraction was skipped. `assist.py:113` only investigates when an event amount is unknown. This is a coverage opportunity, NOT evidence that all 189 decisions are wrong or need API calls.
- 162 available evaluation messages have no direct event link. Supporting these requires explicit user/recurring-series semantics, not inventing event IDs.
- Development request_02 contains a confirmed future salary increase but has no blank amount, so extraction skips it. Request_14's salary-resumption message is also skipped.
- In development request_03, recurring salary and a smaller one-off promotion-arrears payment share the salary category. Category-only grouping selects the arrears amount as repeating income. Reading the missing payslip alone does not fix that grouping defect.
- Development request_13 has two household income streams but the current detector produces one 25-day series. Income grouping and calendar handling need independent correction.
- The original run's two degraded evaluation rows, request_64 and request_73, had image candidates but no resolved facts. Better target context is worth testing; successful extraction is not guaranteed.
- This audit found ZERO excluded images and ZERO exact confirmed/projected debit collisions in evaluation contexts under its stated matching rule. Do not present either hypothetical issue as a measured dataset defect.

## Reproductions

Run offline:

```powershell
py -3.12 -B docs/reviews/measure_accuracy_gaps.py
py -3.12 -B docs/reviews/accuracy_regression_probes.py
```

Eight probes currently fail, exposing:

1. Known-amount amendment messages never trigger investigation.
2. A structured event can be cited as proof of its own unsupported cancellation.
3. An extracted amount with the wrong currency is accepted.
4. A user-level fact can carry an event target and bypass target-relevance validation.
5. Money parsing joins multiple numbers: `2 invoices of INR 500` becomes `2500`.
6. Two independent salary streams merge into one.
7. Monthly salary on the 15th drifts to March 17 under fixed-day arithmetic.
8. Repeated historical refunds can become unsupported future recurring income.

These are review probes outside normal discovery, not a claim that the existing suite fails. Move the behavioral regressions into production tests while fixing them. The first probe observes a fake-provider call; a sound deterministic amendment resolver may instead test the resolved behavior without requiring a model call. Do not otherwise weaken expectations merely to obtain green tests.

## Phase A: close evidence authorization holes first

Ownership: `code/buy_or_wait/evidence.py`, extraction schema/prompt, evidence tests.

- Enforce scope invariants: event facts require a relevant event target; user-level facts cannot silently mutate one. A source's existence and ownership are necessary, not sufficient proof of its claim.
- Reject wrong-currency repairs unless an explicit, valid conversion is performed using the contract's exact directed settlement-date rate. Never apply the number while dropping its currency.
- Require canonical numeric values in model JSON. Keep source text separate. Reject ambiguous strings containing multiple amounts rather than concatenating digits.
- Do not let an event-only citation authorize a cancellation or amendment absent supporting source content. Preserve and check source spans for text claims, target relevance, effective dates, and explicit change semantics. Exact text occurrence alone is not complete semantic proof. Image claims need traceable image provenance and conservative validation; do not pretend text substring checks validate pixels.
- Record accepted facts separately from applied facts and decision-impacting facts. Preserve source spans in traces. Cite applied supporting evidence in the explanation, and explain material uncertainty rather than attaching an unsupported list of IDs.
- Unsupported facts must not increase certified affordability. An unresolved material liability/amendment must not silently become a confident baseline recommendation merely because its old amount is known.

Acceptance: probes 2–5 pass, plus negative tests for irrelevant spans, ungrounded cancellation, dates outside availability, and rejected facts never affecting predictions/citations. Preserve existing ownership/path/date checks.

## Phase B: investigate material evidence even when amounts are known

Ownership: `assist.py`, `evidence.py`, `model.py`, `code/prompts/`, shared prediction integration.

- Replace the blank-amount-only gate with request-scoped investigation of potentially material available messages/images. Irrelevant or corroborating evidence may produce a validated no-op; do not mutate facts merely to raise coverage.
- Send source linkage and relevant target metadata: event ID, description, existing amount/currency, cash state, event/settlement dates, category, and linked-event relationship. Current sources expose message text/image bytes but insufficient structured target context.
- Add a small typed representation for forward-looking recurring-income/expense amendments: confirmed amount or a supported percentage change, effective date, affected stream, source IDs. Resolve it into the existing forecast inputs; do not fork the decision engine or overwrite settled cash balances.
- Handle blank event links honestly. If the affected series cannot be established, keep the amendment unresolved rather than manufacturing a target. Respect explicit cancellation/amendment and same-source recency; compare parsed times, not arbitrary timestamp strings across unrelated sources.
- Keep the actual dataset categories. No August taxonomy or invented category alias layer. Apply or reject each supported fact type explicitly; accepting a category fact that is silently unused is not coverage.
- Version the prompt/schema/cache. Old cached responses must not masquerade as outputs from the improved extractor.
- Broader coverage will change cost. Before any live rerun, test attempt counting, failures, SDK retry controls, and result retention at the budget boundary. A post-response token ledger is not a guaranteed hard monetary ceiling. Do not simply reuse a 60-call budget and silently skip newly relevant evidence after exhaustion.

Acceptance: known-amount salary/rent amendment, user-level message with no target, irrelevant evidence no-op, injection, missing image, unresolved material expense, and evidence-to-recurrence integration tests. Verify extraction on development examples with fake providers first. A subsequent bounded live development run requires explicit authorization; inspect actual responses, repairs, and usage, not merely `provider: configured`.

## Phase C: improve recurrence without tuning constants to answers

Ownership: `code/buy_or_wait/recurrence.py`, forecast integration, engine tests.

- Separate independently supported income streams. Do not group every credit in one category together; equally, do not blindly split every description variation into a new stream. Use observed cadence and meaningful stream identity, with explicit ambiguity handling.
- Keep one-time arrears/bonuses/refunds/gains out of recurring salary. Historical settlement does not confirm a future refund. Preserve legitimately confirmed salary and supported new-job income.
- Model demonstrated calendar-monthly recurrence as calendar-monthly, preserving day-of-month or supported month-end behavior. Retain weekly/fortnightly behavior where history supports it. Median gaps alone are not proof of recurrence.
- Apply validated amendments to future occurrences on the effective date. Do not replace historical amounts or cash balances to simulate a raise or rent increase.
- Independently replay expected dated movements and balance troughs. Keep exact FX lookup, pending debit reservation, minimum balances, user preferences, and payment-option constraints intact.

Acceptance: probes 6–8 plus month-end/leap-year, weekly, fortnightly, interrupted income, one-off arrears, two salaries, scheduled next salary, effective-date raise, and no duplicate confirmed/projected movement fixtures. Measure the ten development rows before/after, including safe-amount errors by currency and dates, without adding request-specific rules.

## Defer unless time remains

Variable flexible-spending series currently fall into category averages and are not necessarily actionable by the fixed-series spending-change planner. Investigate this separately after the evidence and income work; do not solve it by globally lowering reserves. Avoid a new model, vector store, larger agent architecture, or arbitrary calibration multipliers.

## Review and release gate

1. Implement A first, then B/C in small reviewable changes. Log decisions and rejected alternatives in `docs/IMPLEMENTATION_STATUS.md`.
2. Run the full offline suite on Python 3.10 and 3.12, plus the new regressions. Preserve no-provider fallback behavior where evidence is genuinely nonmaterial; disclose necessary safety-driven changes.
3. Write candidate predictions/traces to separate paths. Preserve the frozen root output, final usage report, and archive until replacement is explicitly chosen.
4. Compare development results to a reproducible predecessor. Distinguish source availability, inspected sources, accepted/applied facts, decision-impacting citations, unresolved material facts, and actual accuracy. More citations is not itself an improvement.
5. Freeze code before another reporting run. Disclose prior public-sample exposure; do not iterate on reporting mismatches. Do not promise an accuracy percentage from these fixes.
6. Only after Codex review and an authorized real run: revalidate all 250 rows, regenerate the final-run usage report, build and test the archive, and export/redact the actual transcript. Reserve time for packaging; a partially validated improvement should not replace the frozen submission.

### Suggested Claude instruction

Read this handoff and the controlling plan. Reproduce all eight probes offline. Implement Phase A first and hand back the focused diff and tests for Codex review; then proceed with authorized B/C work. Preserve the shared deterministic decision engine, do not tune on reporting labels, do not overwrite frozen artifacts, and do not make paid calls without authorization. Report remaining unsupported evidence explicitly rather than calling the milestone complete merely because tests pass.
