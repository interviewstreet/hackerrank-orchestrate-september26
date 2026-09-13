# Block 1 release review

Codex CLI, 2026-09-13 ~14:33 IST. Recommendation: defer Block 2, finish the narrow check below, and move directly to release preparation. No application code or frozen output/archive was modified by this review; no paid calls.

## Verified

- Python 3.12 full suite: **290 tests, OK**, 16.355 seconds. Python 3.10 was not independently rerun in this review.
- Full deterministic smoke run to a temporary candidate file: **250 rows, 0 gate failures, 2 degraded rows, exit 0**; input audit 0 findings/errors. Methods: full_payment 53, installments 32, not_recommended 147, partial_payment 7, wait 11. This is execution/validation evidence, not measured hidden-test accuracy or the final submission artifact.
- Production independent replay reconstructs signed movements and ordering without Forecast.walk/is_safe; payment-horizon and certification checks are present. The faulty-planner regression is included in the passing suite.
- Crashed prediction rows return before publish, preserving previous output; positive and negative publication tests pass.
- Split v2 verifies, fingerprint `730cdc20ae17`. Git diff confirms dev/report memberships, salt and algorithm are unchanged; raw v1 sample hash is retained separately and canonical sample identity is its LF-normalized equivalent. LF/CRLF and real value-change tests pass. Raw frozen artifact hashes must remain raw, not be normalized to hide transport differences.
- Spending membership/permissions and nonfinite/negative reduction checks are useful improvements. They do not yet independently establish every ownership precondition.

## R-B1-01 — missing independent cited-event ownership check

Location: `code/buy_or_wait/validation.py:217`.

The gate now validates the event ID against recurrence.fixed, but does not look up and verify that the supplied cited FinancialEvent belongs to request.user_id/profile.user_id and is itself a debit. The later replay independently resolves the same ID from the events sequence. Reproduction using the existing M3GateTests spending fixture: replace the supplied events' user_id with another_user while preserving recurrence/decision; validation.check returns an empty failure list.

The real loader currently supplies same-user contexts, so this is a missing defense-in-depth guarantee, not evidence of a cross-user row in the dataset or a new exploitable input-loader bypass. It was nevertheless explicitly part of Block 1's independent spending-citation requirement.

Minimal fix: alongside series membership, require an actual cited event in the supplied event registry, matching request/profile ownership and debit direction. Check series/event identity consistency and that the series has a projected occurrence in the certified window before claiming a future cut. Test foreign-user, missing, and credit records plus the valid existing spending case. No new architecture required.

Reproduction command:

```powershell
py -3.12 -B -c "import sys; sys.path.insert(0,'code'); from dataclasses import replace; from tests.test_engine import M3GateTests; from buy_or_wait.validation import check; req,prof,fc,events,decision,rec=M3GateTests()._spending_setup(); foreign=tuple(replace(item,user_id='another_user') for item in events); print([f.rule for f in check(decision,req,prof,fc,(),foreign,rec)])"
```

Observed before fix: `[]`.

## Release direction

Do NOT start Block 2 now. Treat this as a safety-hardened, capability-limited release rather than claim forecast accuracy improved. Monthly drift, income-stream grouping, message-only effects, internal rounding and operational limits remain disclosed limitations, not completed work.

Claude: make the small cited-event check and its tests, then prepare a candidate release through the reviewed shared prediction path. Keep mutations disabled; no more language-rule work. Use candidate output/archive/manifest paths and preserve the frozen predecessor until verification succeeds. Do not overwrite the only copy while testing.

Before another paid run, the outstanding provider retry/budget accounting controls still apply. Prefer deterministic generation or an explicitly provenance-preserving, network-disabled replay of prior extraction responses if sufficient; do not silently use a configured key. Any reuse must revalidate proposed facts under current code, not inject formerly accepted facts around the new guards.

Regenerate the final report/manifest for the actual chosen producing path. Old public reporting scores and usage belong to their old code/run and must be labelled as such unless remeasured. Record split v1->v2 migration without relabelling historical fingerprints. Build the new archive only after source/README/report freeze; verify its exact contents, raw hashes and clean extraction. Export/redact the real transcript. Target participant submission by 17:30 IST.

No general financial-safety signoff is implied by Block 1 tests: replay checks the supplied forecast, not whether recurrence omitted an obligation or counted unsupported income.
