# Phase A fourth-pass review: effect-to-target binding remains open

Codex CLI, 2026-09-13. No application edits or paid calls.

Verified: the eight prior probes pass; the Python 3.12 production suite passes 274 tests (14.968 seconds). Python 3.10 was not independently rerun for this snapshot. The new positive cancellation pattern is a meaningful improvement over default acceptance, but does not yet identify what was cancelled.

## P1: amendment number matching does not establish the number's role

Location: `code/buy_or_wait/evidence.py:428` and its caller.

Real linked message: `The amendment processing fee is ZAR 1.`
Proposed fact: amended_amount=1 ZAR for the linked payment.
Observed: accepted.

The number matches exactly, but it describes a fee, not the replacement amount of the underlying payment. This reproduces the handoff's supposedly theoretical limitation concretely. It is not a request to rewrite working numerical parsing; the missing check is the relationship between the amount and the claimed effect.

## P1: completed-effect grammar does not identify the affected object

Locations: `code/buy_or_wait/evidence.py:281`, `code/buy_or_wait/evidence.py:495`.

Real linked message: `Your cancellation request has been cancelled. The payment remains due.`
Proposed fact: cancelled=true for the payment.
Observed: accepted.

The completion pattern correctly recognizes a cancellation, but it is cancellation of a request, not cancellation of the payment. Selecting one qualifying sentence ignores the explicit continuing obligation in the next sentence. Event linkage means the message concerns the event; it does not mean every effect in the message applies to that event.

Both cases are now offline probes in `phase_a_review_probes.py`: ten methods, original eight pass, two new failures. No claim is made that these synthetic cases occur in the shipped output.

## Deadline decision

Do not spend another pass adding these example words to a blacklist. The previous recommendation remains: disable cancelled/amended_amount mutations by default until their effect, target, amount/currency and applicability are all supported by a deliberately restricted validator. Keep verified amount repair separate. If a material changed obligation cannot be resolved, preserve uncertainty and avoid certified approval; do not merely drop the evidence and call the result proven.

Choosing limited capability is an explicit participant tradeoff, not full implementation of the evidence contract. It is preferable to describing these defects as theoretical while leaving unsafe mutations enabled. Claude should document that policy and add a fake-provider integration test proving unsupported mutations cannot affect events, forecast or applied-evidence citations. Then prioritize independent replay/horizon/spending controls and recurrence work with the remaining time. A fully general language interpreter is not required for this release.

Review disposition: accept the specific previous reproduction fixes, but do not approve Phase A as a complete semantic authorization boundary. No new architecture or paid run is warranted by this review.
