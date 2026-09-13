# M2 implementation review

Date: 2026-09-13. Reviewer: Codex CLI.

## Verification

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"` — 239 tests, OK.
- Deterministic mode remains unchanged and assisted mode without credentials
  produces the same rows as deterministic mode.
- No provider call was made during review.

## Fix-first findings

### R-M2-01 — Evidence dates bypass the strict input contract

`evidence.resolve_fact()` calls `date.fromisoformat()` directly for
`ProposedFact.value_date`. On Python 3.11+, compact and ISO-week forms such as
`20240303` and `2024-W09-7` are accepted, despite M0's exact `YYYY-MM-DD`
contract. Reuse the strict parser or an explicit shape check and add negative
fixtures for both forms.

### R-M2-02 — Per-row timeout is not a hard wall-clock bound

`model.BoundedCaller.call()` creates a `ThreadPoolExecutor` in a `with` block.
After `future.result(timeout=remaining)` raises, context-manager shutdown waits
for the provider worker to finish. A hung provider can therefore exceed the
advertised row timeout and delay the full run. Use non-waiting shutdown or an
executor lifecycle that cannot block the caller, and test with a provider that
never returns.

### R-M2-03 — Provenance is not integrated into the output explanation

`assist.extract_facts()` records accepted citations in `RowTrace`, but
`main.run_predictions()` passes only `Decision` to `output.to_row()`. The final
`decision_explanation` therefore contains no accepted `message_id`/`image_id`
references, even when evidence changed the decision. The September feedback
requires final cited IDs to be auditable and the rationale to refer to them.
Add a claim/evidence rendering path (or an explicit trace-derived explanation)
that includes only accepted, retrieved IDs; validate that every emitted ID exists
in the row trace and history. If no supported evidence exists, state that
evidence is insufficient rather than inventing a citation.

## Disposition

M2 is **not yet accepted as submission-complete**. The retrieval, extraction,
category, conflict, cache, and fail-closed foundations are good and may remain
in place. Fix the three findings with targeted tests, then rerun the full suite
and perform an assisted-mode fake-provider integration test before M4.
