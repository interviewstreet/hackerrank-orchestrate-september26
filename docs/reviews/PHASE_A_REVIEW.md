# Phase A review — changes requested

Codex CLI, 2026-09-13. Reviewed the completed four-file Phase A diff and its handoff. No application changes or paid calls were made. Root output and archive retain their previously recorded hashes.

## Findings

### R-A-01 — P1: linked evidence is still mistaken for proof of cancellation

Locations: `code/buy_or_wait/evidence.py:282`, `code/tests/test_evidence.py:204`.

The new check correctly rejects event-only self-citation, but a linked message/image ID alone still authorizes cancellation or amendment. Neither the message content nor source_span is checked. The new positive cancellation test uses message_01, whose entire text is `Your February payslip is attached. Ref EMP-0001.` It does NOT document cancellation. The fixture therefore codifies the unsafe assumption rather than proving a legitimate positive case.

Reproduction: propose cancellation of event_04 citing message_01, with fabricated source_span `This payment has been cancelled.` The fact is accepted. Changing a future debit to cancelled on such evidence could manufacture safe capacity. Source membership checks do not establish semantic support, and adding an unverified span to the trace does not fix that.

Required correction: make the positive fixture contain an actual explicit cancellation and a supporting span. Add rejection fixtures for attachment-only text, unrelated/absent/fabricated spans, negated cancellation, and unsupported amendments. Require a validated effect for destructive changes; if the source cannot establish the effect, retain uncertainty rather than remove the obligation. Text-span membership is necessary but not sufficient: `not cancelled` must not authorize cancellation. Keep image evidence handling distinct from deterministic text matching.

### R-A-02 — P1: repeated equal numbers still concatenate into invented money

Location: `code/buy_or_wait/evidence.py:213`.

`distinct_runs` counts unique strings, not number occurrences. `parse_fact_amount('500 plus 500')` returns Decimal('500500'), because the two numeric runs collapse to one set member and the old cleaner joins their digits. The new different-number fixture passes but misses this variant.

Required correction: reject multiple numeric occurrences, or preferably constrain model proposal values to a canonical decimal representation and keep localized source text in its own field. Do not solve this with another example-specific exclusion. Cover repeated equal numbers, repeated decimal amounts, separated numbers, and supported single localized amounts.

### R-A-03 — P1: converted facts retain the wrong currency and lose conversion provenance

Locations: `code/buy_or_wait/evidence.py:316`, `code/buy_or_wait/evidence.py:337`.

The exact-date conversion calculates 100 EUR -> 2000.00 ZAR in the fixture, but the returned ExtractedFact and RowTrace say value=2000.00, currency=EUR. The test asserts only the new number, not its currency. The event receives the target-currency value, so this is NOT evidence of a second conversion in the current engine; it is a false audit record and an unsafe representation for later consumers/conflict logic. Original value/rate/direction/date are also not preserved with the converted fact.

Required correction: normalized money must carry the target currency. Preserve the original extracted amount/currency and exact rate/date/direction separately so an auditor can reconstruct conversion. Test the fact, serialized trace, and applied event together. Alternatively, reject mismatched-currency facts for now rather than supporting an incomplete conversion representation. Never relabel a converted number as its original denomination. Exercise missing currency explicitly: define when reliable target/source context establishes it, otherwise reject ambiguity.

## What is improved

- Event-only cancellation/amendment self-citations are rejected.
- user_level can no longer carry a non-null event target.
- Wrong currency without an exact rate is rejected.
- Different numeric runs such as `2 invoices of INR 500` are rejected.
- Accepted/rejected trace entries now include source_span.

These are useful incremental fixes. They do not satisfy the whole Phase A acceptance contract yet. In particular, field support, effective change semantics, and accepted-versus-applied/decision-impacting evidence remain incomplete. Do not report “all authorization holes closed” based solely on probes 2–5 passing.

## Verification

`py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"`: 264 tests, OK, 12.699 seconds.

`py -3.12 -B docs/reviews/phase_a_review_probes.py`: three tests, all fail as described above. These independent review probes intentionally remain outside normal discovery until Claude migrates the corrected behavioral tests.

Python 3.10 initially could not launch through the WindowsApps interpreter in the sandbox. The approved outside-sandbox retry completed: 264 tests, OK, 14.859 seconds. Both existing suites are green; the three new review probes expose behaviors those suites do not establish.

## Remaining ADE findings and next sequence

Phase A did not claim to implement the items below, and the diff does not fix them. They are not new regressions caused by this patch, but they still require action before stronger safety/accuracy claims.

| Issue | Next action |
|---|---|
| Message-only evidence skipped | Phase B: broaden material-evidence investigation only after authorization fixes, with explicit recurring-income/expense effects; removing the gate alone is insufficient. |
| Order-dependent conflict resolution | Fix before Phase B broadens available conflicting facts. Permutation tests, same-source chronology, grounded effect precedence, and conservative unresolved ambiguity; no unconditional cancellation-first rule. |
| Shared production replay | Add a small independent replay implementation in existing module structure; faulty planner-safety injection must not bypass the gate. |
| Spending validation/horizon gaps | Independently check series membership, ownership, debit direction and future applicability; reject every payment outside the certified forecast range. |
| Internal under-reserving rounding | Preserve internal precision or use explicit conservative directional rounding, including the published payment boundary. Add tiny daily-expense and FX cases. |
| Corrupt caches | Reject invalid JSON/schema safely without replacing the last valid output. |
| Retry accounting/budget boundaries | Own retries once, ledger attempts separately, retain unknown usage honestly, retain completed results exactly at the cap, and stop later calls. Fix before the next paid run. |
| Colliding run directories | Unique run IDs/exclusive creation, with fixed-clock collision test. |
| LF/CRLF split portability | Deliberately version canonical content identity while preserving raw artifact hashes and frozen memberships; no silent split regeneration. |
| Publishing after programming errors | Preserve previous final output or quarantine the failed candidate; distinguish expected evidence failure from programming errors. |

Recommended sequence:

1. Claude fixes R-A-01 through R-A-03 and completes the missing Phase A negative tests; Codex re-reviews. Keep B/C and paid calls on hold for this short corrective pass.
2. Address conflict/replay/spending/horizon safety checks as a bounded follow-up. These protect broader evidence handling and catch unsafe candidates, but cannot prove recurrence completeness.
3. Implement B/C in the existing architecture: material evidence and typed future effects, separate income streams, one-off exclusions, calendar recurrence. Measure only frozen development examples while tuning.
4. Resolve operational/publication/portability controls before a new live run. Freeze reviewed code, run any authorized evaluation with exposure disclosed, regenerate final-run usage and artifacts, and verify the actual package. Do not rerun paid calls just for byte/newline transport differences.

Do not restructure the project into ADE's suggested directory tree. These fixes belong in existing modules. Keep the earlier output/archive as a fallback until a replacement has passed review; the old archive does not automatically include this new source diff.

## Claude handoff

Read this review and reproduce the three tests in `docs/reviews/phase_a_review_probes.py`. Fix the confirmed findings without weakening the assertions or inventing supporting evidence. Correct the false positive cancellation fixture. Preserve normalized currency and conversion provenance together, or reject unsupported conversion. Add targeted production tests and run both interpreter suites. Update IMPLEMENTATION_STATUS with remaining Phase A requirements and return for Codex review before broadening extraction. No paid calls or replacement of frozen submission artifacts.
