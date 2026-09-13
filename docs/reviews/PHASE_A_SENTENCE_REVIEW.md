# Narrow sentence-authorization re-review

Codex CLI, 2026-09-13. Verdict: changes requested. No application edits or paid calls.

The previous five probes now pass, and the Python 3.12 production suite passes 270 tests (14.086 seconds). Python 3.10 was not independently rerun for this snapshot. Two new test methods expose three failing cases; these concern the same authorization boundary, not expanded scope.

## R-A-06 — P1: splitting sentences on decimal points invents a smaller amendment

Locations: `code/buy_or_wait/evidence.py:269`, `code/buy_or_wait/evidence.py:342`.

Source: `The payment amount has been corrected to ZAR 900.50.`
Proposed amended amount: ZAR 900.
Observed: accepted.

The sentence splitter treats the decimal separator as sentence punctuation, truncating the supporting sentence to `... ZAR 900`. Amount binding then validates the wrong number. This directly under-reserves a debit; the correct decimal proposal also cannot match that truncated supporting sentence.

Fix: preserve numeric tokens and decimal/grouping punctuation during segmentation. Bind against the complete source amount before any lossy text transformation. Test both rejection of 900 and acceptance of correctly supported 900.50, alongside supported localized numeric formats and terminal punctuation.

## R-A-07 — P1: absence of negative markers is not an affirmative statement

Location: `code/buy_or_wait/evidence.py:284`.

Both `Has this payment been cancelled?` and `Please cancel this payment.` authorize `cancelled=true`. The sentence splitter discards question punctuation, and the affirmative checker merely returns true when none of its blacklist phrases occurs. A question or instruction does not establish that the payment was cancelled. Thus the implementation is still keyword-plus-blacklist matching, despite the handoff describing a narrow authorization boundary.

Fix: require a positively supported completed effect, preserving interrogative/imperative context. Do not just add `please` and `has` to the blacklist: the latter would reject legitimate statements too. Use an explicitly restricted supported statement grammar/effect representation and reject uncertain forms. If that cannot be validated before the deadline, conservatively disable unsupported cancellation/amendment mutations while retaining verified amount repairs and disclosing capability limits. Unresolved potentially material obligations must remain uncertain, not silently certified.

## Reproduction and next step

`py -3.12 -B docs/reviews/phase_a_review_probes.py`: seven test methods, original five pass, three failures in the two added methods (two cancellation subcases and one decimal amendment).

Claude: fix these two boundary defects and migrate the probes plus positive counterparts into normal tests. No new provider/model, directory restructuring, paid calls or output replacement. Return a narrow handoff; all other open safety/accuracy tasks remain as previously documented. Preserve time for final packaging rather than extending a general English blacklist indefinitely.
