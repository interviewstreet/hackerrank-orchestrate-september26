# Independent disposition of ADE's repository review

Reviewer: Codex CLI. Date: 2026-09-13. Scope: the current local checkout, not ADE's browser filesystem. Application code and frozen submission artifacts were not modified. No paid model calls were made.

Snapshot qualification: the tests and reproductions below completed before approximately 12:40 IST. During final status checking, concurrent edits appeared in `assist.py` and `evidence.py`; Codex did not make them. They add currency conversion, some scope/self-citation checks, numeric-run checks, and trace spans. Those in-progress changes are NOT covered by the 254-test result or approved by this review. Findings below describe the inspected pre-edit code; re-review the completed fix handoff rather than treating partially addressed items as still absent or already verified. New line numbers may differ.

One immediate regression remains in that in-progress numeric fix: `parse_fact_amount('500 plus 500')` returns `500500`, independently reproduced after the edit. Counting distinct numeric strings instead of numeric occurrences allows repeated equal numbers to be concatenated. Add that negative fixture; canonical numeric proposal values avoid this class of ambiguity. This observation is not a review approval of the rest of the concurrent patch.

## Verdict

ADE identified multiple real correctness and assurance gaps. Its blanket artifact-based P0 verdict does not describe this local checkout. Distinguish a portable/reproducible checkout defect from missing or mismatched local submission files. I would not sign off the broader evidence safety guarantees yet, but I would not discard the working financial core or undertake the proposed directory restructure.

My earlier 254-test/package verification established those particular checks, not comprehensive correctness. The additional reproductions below expose important coverage gaps those tests missed. ADE is right to challenge the strength of the earlier independent-replay and provenance claims.

## Checks run now

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"`: **254 tests, OK** (14.317 seconds).
- `py -3.12 -B code/evaluation/main.py --show-split`: **PASS**, fingerprint `ecafb49177d9`, 10 development / 15 reporting, disjoint.
- `py -3.12 -B code/main.py --mode audit --quiet`: **0 findings, 0 errors**.
- `py -3.12 -B docs/reviews/verify_ade_findings.py`: offline reproductions and artifact comparisons described below. This is a diagnostic script, not a passing regression suite for unfixed behaviors.
- Root output, final trace, and final usage hashes all match the existing final manifest. The suite did not replace root output. It did generate fake-provider test traces; two tests printed the same run directory, directly illustrating the second-resolution collision issue.
- No reporting evaluation was rerun or tuned. The seasonal example was checked against its input/context and detector only, not gold labels.

## Artifact findings: qualified, not blindly accepted

### A01 — Frozen split portability: confirmed; local split failure: not reproduced

Locations: `code/evaluation/main.py:81`, `code/evaluation/splits.py:123`.

Local sample SHA256 is `117bf2ab9e5f0054bae48afe8506f5daa35929559cb771f2c27dd4fe18da62f6`, matching the manifest. Converting only CRLF to LF produces exactly ADE's `1195bbe962e62a3eafa1118efc5fdef3f5fac0bf70009e6e59dab75b9228c5dc`. Passing that hash into the current split verifier raises `SplitError` with identical request IDs.

This is a real cross-platform reproducibility defect, not proof that labels or split membership were changed. Keep separate hashes for raw artifact identity and explicitly versioned canonical dataset content. A deliberate migration must prove unchanged parsed content AND unchanged dev/report IDs, retain the old fingerprint/hash mapping, and test both newline formats plus an actual changed cell. Never silently re-freeze the split. A line-ending-only migration does not inherently require another paid model run; existing trace replay can establish identical predictions.

### A02 — Output mismatch: explained exactly by newline conversion

Local output SHA256: `e445b252d90e158bf51b21f33f6003b5d93014b45aba694cc0a3c35d513cf1fa`, matching the final manifest. Converting only CRLF to LF produces EXACTLY ADE's `6694af1cec0d7fbd4d5d109a08c96a94c241738f853ec83800e4a0f1700f5958`.

Therefore ADE has not demonstrated different predictions. Its copy still fails strict byte identity against the manifest, which matters for that copy's bundle. Preserve raw final artifact hashes; do not make an artifact check ignore arbitrary differences. Transfer the archive/output as bytes or deliberately re-finalize the normalized bundle with provenance. Do not regenerate paid predictions merely to repair newline transport.

### A03 — Missing archive: false locally; plausible in a Git-only copy

Local `code.zip` exists, SHA256 `4af706001e2e71ce42ac1db453da9b732f1867cf23e9a12a18043343202a462f`. It is intentionally Git-ignored, so a clone/browser import may omit it. Missing a generated archive from source control is not itself an implementation defect. The actual submission still must include it. Clean archive verification was performed in the preceding finalization review; this turn verified identity/existence rather than claiming a second clean extraction.

### A04 — Duplicated problem statement: not reproduced locally

`problem_statement.md:1` has one `# Buy or Wait?` heading and `problem_statement.md:239` has one token-usage heading. Git reports no modification to that file. ADE may have inspected a different copy; do not edit or revert our specification on this evidence.

## Financial and evidence findings

| Finding | Disposition and evidence | Targeted fix/test |
|---|---|---|
| Message-only extraction skipped | **Confirmed**, `code/buy_or_wait/assist.py:113`. Earlier local measurement found 189/250 evaluation requests with available messages skipped; not all are material. | Investigate material known-amount amendments/cessation too; test no-blank-amount cases and user-level effects. Validate effects before expanding extraction. |
| request_12 continues seasonal salary | **Not reproduced for that example.** It skips extraction, but the detector already returns **zero credit series** because history is lapsed. ADE correctly identifies the absent evidence path, but overstates this example's actual effect. | Use a synthetic cessation immediately after a regular salary, before lapse heuristics would stop it. Do not tune on this reporting example's gold. |
| Extracted currency ignored | **Confirmed**, `code/buy_or_wait/evidence.py:293`, `code/buy_or_wait/evidence.py:387`; prior wrong-currency regression probe fails. | Require explicit denomination compatibility or a valid exact-date directed conversion. A new Money class is optional; enforcing the invariant is essential. |
| Runtime replay shares planner implementation | **Confirmed**, `code/buy_or_wait/validation.py:239`. Unsafe fixture normally gets P1; replacing `Forecast.is_safe` with an erroneous true result leaves zero gate failures. Separate test oracle does not make runtime replay independent. | Small independent production replay over movements and serialized payments, with its own ordering/range/certification checks. Retain independent hand-computed/oracle tests rather than replacing one shared implementation with another shared oracle. This still cannot prove omitted forecast movements are correct. |
| Conflict resolution order dependence | **Confirmed**, `code/buy_or_wait/evidence.py:355`. Equal-recency amendment/cancellation selects amendment in one order and cancellation in reverse order. | Permutation-invariant resolution with grounded explicit effect precedence and same-source chronology. Do NOT blindly use ADE's universal cancellation-first rule: removing a disputed debit can be less safe. Unresolved ambiguity needs direction-aware conservative treatment. `cancelled=False` must not suppress a monetary fact. |
| Retry/usage accounting incomplete | **Confirmed by source**, `code/buy_or_wait/model.py:214`, `code/buy_or_wait/model.py:255`, `code/buy_or_wait/model.py:382`. No explicit SDK retry/timeout controls; missing usage becomes zero; errors are not counted as successful usage and attempts have no separate ledger. | Own retries once, count attempts pre-call, retain unknown usage as unknown, report actual response model, honor bounded retry delay. Test adapter configuration and partial/missing usage. Daemon timeout abandons a worker; it does not cancel server computation or prove zero billing. |
| Source spans dropped | **Confirmed**, `code/buy_or_wait/evidence.py:446`. Fact/cache objects have source_span, final trace serialization omits it. Same-user/source existence is not field-level proof. | Serialize and validate supporting text spans, preserve image provenance/field location without pretending image text is deterministically verified. Test unsupported same-user claims and rejected evidence not reaching explanations. |
| Spending validation incomplete | **Confirmed defense-in-depth gap**, `code/buy_or_wait/validation.py:139`, `code/buy_or_wait/spending.py:160`. Synthetic unrelated, other-user event with matching category/description can stop a projected debit and pass all gate checks. Actual planner/context restrictions limit reachability; this is not proof a shipped row uses a foreign event. | Gate requires request ownership, debit direction, accepted future-effective recurring-series membership, permissions/floors. Validate serialized actions against the actual series identity rather than description alone. |
| Malformed spending literals silently allowed | **Qualified.** `apply_literals` skips malformed strings, BUT validation already adds E3 before replay. This is not a standalone final-gate bypass for a malformed shape. Numeric finiteness/sign validation deserves its own fixtures. | Make helper behavior explicit/strict without claiming existing E3 is absent. |
| Internal rounding under-reserves | **Confirmed**, `code/buy_or_wait/recurrence.py:266`, `code/buy_or_wait/fx.py:84`. Synthetic 0.50/120 daily reserve becomes 0.00. FX similarly rounds internal values. | Retain precision or apply explicit conservative directional rounding; test boundary affordability after serialization too. Current forecast includes both endpoints (91 daily dates for a 90-day offset), so ADE's 0.375 example is a 90-charge illustration, not the exact full current loop total. No current FX loss measurement is claimed here. |
| Plans beyond forecast horizon | **Confirmed synthetic gate gap**, `code/buy_or_wait/validation.py:223`, `code/buy_or_wait/forecast.py:136`. Installments on days 95/105 with deadline day120 pass the gate despite horizon90. C17 constrains earliest-full date, not every payment. | Reject any payment outside certified horizon (smallest fix), or deliberately extend forecasting. Replay currently applies extra payments beyond horizon but has no ordinary expenses there; it does not simply ignore those payments. Do not reject all long deadlines when a safe earlier plan exists. |

## Operational and evaluation findings

| Finding | Disposition and qualification | Recommended action |
|---|---|---|
| Corrupt cache crashes assisted setup | **Confirmed**, `code/buy_or_wait/model.py:499`, `code/main.py:180`. Truncated JSON raises JSONDecodeError; setup is before per-row isolation. Valid JSON with wrong shape is also unchecked. | Catch decoding/schema problems, mark corrupt cache and treat as a miss or clear runtime failure without replacing valid output. Test truncated JSON and wrong shapes. |
| Evaluation lacks model ID header | **Confirmed**, `code/evaluation/main.py:112`. Header says assisted/deterministic, not actual model identity. | Print requested and observed response models, plus provider/no-provider status. Do not mistake this metadata gap for wrong arithmetic. |
| Unexpected errors still publish | **Confirmed behavior**, `code/main.py:266`, `code/main.py:296`. Conservative fallback rows publish before nonzero return. | Existing behavior is explicit failure disclosure, not silent success; nevertheless quarantine programming-error runs and preserve prior output. Distinguish expected evidence failures from programming exceptions. Test injected exception with a pre-existing output sentinel. |
| Run IDs collide within a second | **Confirmed**, `code/main.py:271`; two fake-provider CLI tests in this turn printed the same trace directory. | Unique per-run ID and exclusive creation; test fixed clock producing two runs. |
| Lifecycle checker unused | **Confirmed unused helper**, `code/buy_or_wait/state.py:177`; current zero-risk measurement is not evidence of a current duplicated cash movement. | Audit potential ambiguity, but never fail/deduplicate every linked pair: a purchase and sale, or debit and refund, legitimately both affect cash. Classification must use status/direction/lifecycle evidence. ADE's blanket check would be unsafe if applied without that qualification. |
| Missing evaluation measures | **Largely confirmed**, `code/evaluation/main.py:187`, `code/evaluation/metrics.py:48`. Label accuracy/date errors/currency MAE exist, but claim coverage, citation validity, spending validity, latency and independent plan-safety rates are not fully reported. Relative MAE excludes zero-gold rows without its own printed denominator. | Add explicit metric definitions and denominators; separate syntactic citation validity from semantic support. Preserve sample-exposure disclosure and do not invent evidence gold labels. |

The recorded report subset remains status6/15, method8/15, plan6/15, date3/15 for both modes. It demonstrates **no measured gain on that subset**, not proof evidence assistance can never help. Also, the evaluator's phrase “degraded rows counted as wrong” is misleading: the current scorer uses ordinary label comparisons rather than automatically marking every degraded row incorrect. This was already disclosed in finalization notes and should be corrected in the evaluator text/policy.

An additional already-known budget issue remains relevant: `model.py:425` checks `>=` AFTER recording a successful response as well as before the next call. A result landing exactly on the ceiling can be discarded. Retain that completed result while preventing any subsequent attempt; test both behaviors separately.

## Architecture and release recommendations

1. **Do not do the proposed directory reorganization now.** Current module boundaries already separate data, evidence, forecast, planner, validation, provider and publication. Renaming them into six layers does not repair these defects and creates packaging/import risk.
2. First implement focused currency/scope/provenance/conflict fixes and independent replay/horizon/spending validation. Reproduce before fixing and add normal-suite regressions.
3. Fix portable split identity with an explicit migration, corrupt-cache handling, unique run IDs, error-publication policy and provider accounting before another broad paid run.
4. Then expand material evidence routing and typed recurring effects, alongside the income/calendar fixes in `ACCURACY_IMPROVEMENT_PLAN.md`. A run context or typed effects can be small dataclasses in existing modules; a new framework is unnecessary.
5. Preserve the current output/archive as a frozen predecessor. After reviewed code changes, evaluate development cases, freeze code, and only then perform an authorized final model run/reporting pass if needed. Do not launch ADE's assisted evaluation command as an “offline verification” command: it can spend money.
6. Generate final traces/usage from the exact producing run and build/verify the package after the last change. The repository already has finalization and archive-verification scripts; consolidate carefully rather than create a second incompatible finalizer. Newline-only transport repair does not justify fabricating a new run or changing usage provenance.

## Bottom line for the participant

Accept ADE's substantive code concerns, reject/qualify its local-artifact claims, and avoid the architectural rewrite. The best next Claude task is the bounded safety/validation patch set with reviewable regressions, followed by the already-planned accuracy work. An existing valid CSV and green test suite are useful foundations, not evidence that all financial/provenance claims are proven.
