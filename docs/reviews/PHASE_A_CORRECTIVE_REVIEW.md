# Phase A corrective review — authorization still incomplete

Codex CLI, 2026-09-13, approximately 13:05 IST. No application edits or paid calls. Frozen output/archive hashes remain unchanged.

## Disposition

- R-A-02 repeated-number concatenation: fixed for the reviewed case; `500 plus 500` now rejects.
- R-A-03 converted currency/provenance: fixed for the reviewed case; normalized currency now matches the converted value and conversion_note records source amount/currency, direction, rate and date. Underlying FX rounding remains a separate open issue.
- R-A-01 unsupported cancellation/amendment: the silent-message reproduction is fixed, but the authorization invariant is NOT fixed. The replacement keyword test is a routing heuristic, not proof of an actual financial change.

## R-A-04 — P1: negation, conditions and pending refunds authorize cancellation

Location: `code/buy_or_wait/evidence.py:284`.

All of these real message texts authorize a proposed `cancelled=true` for their linked event:

- `This payment has not been cancelled. It remains due.`
- `If you cancel next month, please notify payroll.`
- `Your refund request is pending; the payment remains due.`

The check searches substrings such as cancel/refund without validating polarity, certainty, effective date or actual effect. These examples can remove a real debit instead of reserving it. A refund is not generally cancellation of the original transaction, and pending refunds cannot fund affordability.

Fix: use keywords only to identify evidence requiring investigation. Require an explicit affirmative, applicable effect before mutating the event. Unsupported, negated, conditional or future-uncertain changes must not authorize removal of obligations. Do not build an ever-growing substring blacklist: implement a small supported effect contract and fail closed outside it. If reliable mutation validation cannot be finished within the deadline, disable uncertain cancellation/amendment effects and disclose the limitation rather than approving them through keyword matching. A potentially material unresolved liability change must remain marked uncertain, not silently treated as fully certified baseline data.

## R-A-05 — P1: amendment language does not bind the proposed amount

Locations: `code/buy_or_wait/evidence.py:342`, `code/buy_or_wait/evidence.py:362`.

Real source text `The payment amount has been corrected to ZAR 900.` accepts a proposed amended_amount of ZAR 1. The source_span in the reproduction is an exact copy of the real text; even a correct span does not establish the proposed number. The gate merely checks that an amendment keyword exists somewhere and then parses the model's unrelated amount.

Fix: bind the normalized amount, currency, target and effective date to the supported amendment, with deterministic numeric correspondence and exact conversion provenance where needed. Preserve original structured values when unsupported; reject the proposed effect. Add amount-mismatch, old-versus-new amount, currency mismatch, and future-effective amendment cases, including application/forecast checks.

## Image fallback limitation

`code/buy_or_wait/evidence.py:288` explicitly falls back to keyword matching in the model's own source_span for image-only evidence. That is not independent corroboration. Do not claim that fabricated spans cannot authorize changes universally: the fix only consults ground-truth text when a message is present. Image extraction remains model-derived evidence with uncertainty; destructive effects must follow the same conservative policy. Do not fabricate independent OCR/pixel verification.

## Verification

- Python 3.12 existing suite: **268 tests, OK**, 13.571 seconds. Python 3.10 was not rerun for this corrective snapshot.
- `py -3.12 -B docs/reviews/phase_a_review_probes.py`: original three probes pass. Two added test methods expose four failures (three cancellation subcases plus wrong amendment amount).
- No evidence these synthetic defects changed a particular frozen output row is claimed. They demonstrate invalid facts can be accepted by the current authorization boundary.

## Next action

Return this narrow authorization fix to Claude before opening the message-only extraction gate. The remaining conflict, independent replay, spending/horizon, precision and operational issues in `PHASE_A_REVIEW.md` remain open. Do not spend remaining time reorganizing modules or claim that 268 green tests closes these invariants.

Claude instruction: reproduce R-A-04/R-A-05 using the existing review probes, migrate the behavioral assertions into normal tests, and fix the supported-effect boundary rather than extending keyword lists. Retain the now-correct numeric/currency fixes. If a conservative restricted capability is chosen for the deadline, document it explicitly. No paid calls or frozen-artifact replacement; hand back for review.
