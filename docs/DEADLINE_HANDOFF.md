# Deadline handoff: restricted evidence, deterministic improvements, release

Prepared by Codex CLI, 2026-09-13 ~14:07 IST. Deadline 18:00 IST. Participant owns tradeoffs; Claude implements and Codex reviews. This is a deadline-scoped supplement to the implementation plan, not an architecture replacement.

## Phase A disposition

Accept the default-disabled cancelled/amended_amount gate as a **restricted capability**, not full semantic evidence support. The ten current review probes pass. Do not re-enable these fields or continue extending language heuristics before submission. Existing amount repairs remain separate.

The new guard stops mutation application; it does not establish that the untouched baseline is financially correct when material contrary evidence exists. A validated/relevant but unresolved material adverse change must remain explicit uncertainty. Do not count arbitrary rejected model hallucinations as verified adverse facts either. Keep this distinction in explanations and documentation; no blanket claim of complete message coverage or proven accuracy.

## Scope and hard stop

- No broad Phase B, new model/provider, regex expansion, directory restructure or new architecture.
- Preserve root output.csv, existing code.zip and frozen final-run files until reviewed replacement artifacts exist. Use candidate paths.
- No paid calls as part of tests. A new live run requires a specific bounded authorization.
- Target code freeze **16:00 IST**. If a block is unfinished then, omit that unverified improvement from the release; never quietly release half a fix. Reserve 16:00–17:30 for review, artifact generation, clean extraction checks and actual transcript export/redaction. Target submission by 17:30, not 18:00.

## Block 1 — safety/release patch, first priority (~60 minutes)

Keep the patch small and run targeted tests after each change:

1. Independent production replay: apply ordered movements and serialized proposed payments without calling Forecast.walk/is_safe. Enforce certification, opening/minimum balance and every payment's request-date/horizon bounds. Preserve existing debit → credit → voluntary payment ordering. Test a faulty planner safety method cannot bypass validation.
2. Spending-action gate: require owned debit IDs belonging to the actual eligible future recurring series, with permitted category/flexibility/floor; reject nonfinite/negative reduction values. Do not match only category/description. Test a same-description unrelated event cannot authorize a cut.
3. Preserve prior output on unexpected programming errors: quarantine failed candidates and return nonzero before final publication. Expected unavailable evidence is not the same as a programming failure.
4. Portable split verification: add explicit versioned canonical content identity, retain raw-byte identity separately, and prove frozen memberships/content are unchanged during migration. Test LF/CRLF equivalence and actual value-change rejection. Do not silently regenerate the split. This is needed for Linux/browser evaluation, not cosmetic cleanup.

Hand back one compact list of changed files, tests and known limits. Do not claim passing replay proves missing forecast inputs are correct.

## Block 2 — bounded Phase C, only with time (~45 minutes)

Priority order:

1. Correct demonstrated calendar-monthly recurrence without breaking weekly/fortnightly or month-end schedules.
2. Separate supported independent income streams and exclude one-off arrears/refunds/gains from recurring salary. Preserve supported new-job confirmed income. Avoid both category-only merging and blind description-only fragmentation.
3. Address internal under-reserving rounding with explicit precision policy; ensure rendered payment amounts also satisfy the safety boundary. Do not lower reserves or tune arbitrary constants to sample answers.

Use `docs/reviews/accuracy_regression_probes.py` recurrence cases and independent hand-computed fixtures. Measure only the ten frozen development examples. Do not tune against reporting examples or hardcode request/category aliases. If a general income-stream rule cannot be tested within this block, document and defer it rather than invent a rushed one.

## Before any further paid run

Fix provider attempt accounting/SDK retry controls, token-budget boundary result retention, corrupt-cache schema handling and unique run IDs. Tests must use fake providers. Unknown usage must remain unknown, not zero. A daemon timeout is not cancellation of server billing. If these controls are not ready, do NOT initiate a new paid full run; choose an explicitly disclosed deterministic candidate or a demonstrably valid offline replay of existing responses.

Mixed cancellation/amendment conflict ordering is lower priority while those effects are disabled. Do not claim conflict resolution is universally fixed; re-enabling mutations requires fixing it first. Still reject unsupported facts and preserve provenance in any remaining amount repairs.

## Release procedure after review

1. Run offline tests on available supported Python versions. Report actual results, not inherited claims.
2. Generate a candidate 250-row output through the reviewed shared prediction path; exact header, order, unique IDs, bounds, dates/plans/preferences, independent safety checks and grounded explanations. Do not overwrite the fallback while debugging.
3. Freeze candidate source before a reporting pass; disclose prior sample exposure. Do not iterate on reporting mismatches. Compare against a clearly identified predecessor, not a renamed baseline with new behavior.
4. Create final-run trace/usage/manifest from the actual producing path. If using cached prior responses, separate original inference usage/provenance from current cache-only processing; do not relabel old usage numbers as a fresh model run.
5. Build candidate archive from reviewed code, verify actual raw output/trace/usage hashes, extract and test cleanly, and confirm evaluation/usage_report.md is at archive root. Existing finalization scripts are available but must be checked for assumptions about the frozen original run before reuse.
6. Prepare actual chat_transcript, redact the exposed credential and any other secrets, and verify all required uploads are ready. A partial local log is not automatically the full required transcript. Participant performs the final submission.

## Copyable Claude instruction

Follow this deadline handoff. Keep event mutations disabled and stop Phase A language-rule work. Start Block 1 now, then Block 2 only if the 16:00 code-freeze target remains realistic. Preserve frozen artifacts, no paid calls, no broad Phase B, no rewrites. Add targeted negative/positive tests and record concise reviewable results. Stop feature work at the freeze and hand back for Codex release review. Flag any blocker immediately rather than consuming the remaining budget on another heuristic patch cycle.
