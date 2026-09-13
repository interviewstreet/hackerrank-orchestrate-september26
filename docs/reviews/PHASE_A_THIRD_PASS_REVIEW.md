# Phase A third-pass review

Codex CLI, 2026-09-13 13:40 IST. Narrow review of the decimal and sentence-authorization changes. No application changes or paid calls; frozen output/archive hashes unchanged.

## Verified fixes

R-A-06 decimal truncation and the specific R-A-07 question/bare-imperative reproductions are fixed. All seven previous review test methods pass. The existing Python 3.12 suite passes 273 tests, 14.312 seconds. Python 3.10 was not independently rerun for this snapshot.

## Remaining P1: authorization defaults to acceptance without a positive effect

Location: `code/buy_or_wait/evidence.py:342` (used by `code/buy_or_wait/evidence.py:357`).

The checker rejects enumerated negative cases, then returns True without requiring a completed-effect assertion. Both real linked source texts below still authorize proposed cancelled=true:

- `The cancellation policy is attached.`
- `Cancellation failed.`

These are not evidence that a payment ceased to be owed. The first merely mentions the topic; the second explicitly reports failure. The existing guard can therefore remove a future debit without a supported cancellation. This is the same unresolved R-A-01/R-A-04 authorization invariant, not a request to build comprehensive natural-language understanding or a new architecture.

Reproduction: the added test method in `docs/reviews/phase_a_review_probes.py` checks both cases. Running the file now reports eight methods, seven prior methods pass, and two failing subcases in the new method.

## Stop extending the blacklist

Given the remaining time, my recommended release policy is **disable model-proposed cancelled/amended_amount effects unless they pass a deliberately restricted, positively defined effect validator**. If that validator is not ready, reject these mutation types explicitly with an unsupported-effect reason, preserve structured events, and disclose the capability restriction. Do not clear or hide material uncertainty just because a proposal was rejected. Retain the reviewed amount-repair path; this recommendation does not require discarding working numeric/currency changes or the deterministic engine.

This bounded fallback is preferable to another patch that adds `policy` and `failed` to excluded words. The guard's default must be unsupported, not authorized whenever no known bad phrase is found. Future broader evidence support can deliberately expand supported effects with independent tests.

## Next work

1. Choose and implement that explicit restricted mutation policy, with end-to-end tests proving an unsupported mutation cannot remove a reserved debit or appear as applied evidence. Update the handoff to distinguish capability limitations from verified decisions.
2. Do not broaden Phase B extraction into this unresolved boundary yet. Independent deterministic work (replay/horizon/spending gates and Phase C recurrence) need not wait for a general-purpose text interpreter; keep its changes separately reviewable and do not imply these open findings have been fixed.
3. Resolve operational budget/cache/run-ID controls before another live run. Preserve the frozen predecessor until the final candidate is tested and packaged.

The specific submitted fixes deserve credit and are verified. Whole Phase A authorization is not approved as complete.
