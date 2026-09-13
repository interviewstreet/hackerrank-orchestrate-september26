# Codex review checklist

Apply to the implemented milestone. Future milestones are outstanding scope, not automatically defects in an explicitly partial milestone. Mark every check pass, fail, not applicable, or not yet implemented; do not infer successful checks from a README.

## Review procedure

1. Read the milestone handoff and inspect current git status/diff, including untracked source files.
2. Identify the actual entry point, changed responsibility, data flow, and output path. Check for concurrent edits before proposing a patch.
3. Trace one ordinary case, one boundary/failure case, and one adversarial case through the changed behavior.
4. Run relevant offline tests. Use an independent expected calculation for financial logic; do not validate a solver only by calling that same solver again.
5. Inspect output and audit artifacts when the milestone produces them. Ensure sample labels and future evidence are not leaked into inference.
6. Report concrete findings by severity, then checks run and residual uncertainty. Leave implementation changes for Claude unless the participant asks Codex to fix them.

## Contract and data

- Exact September schemas and eight-column output; no notification labels/evidence column imported from August.
- Decimal/date parsing rejects invalid values; optional blanks retain unknown meaning.
- Required inputs and IDs validated, links scoped correctly, dataset path immutable.
- Pure finance modules import and test without credentials/provider/network access.
- No hardcoded request answers, organizer-only data, sample-label leakage, live FX, or unsupported financial assumptions.

## Evidence and explanations

- Retrieved candidate registry is request/user scoped and has a documented availability cutoff.
- Every cited source is real, retrieved, relevant, and supports the stated field/claim.
- Blank event links retrieve user-level evidence; missing image amounts never default to zero.
- Source amendments/cancellations/settlements have explicit conflict-resolution traces.
- Categories use the actual financial vocabulary; ambiguity cannot authorize spending changes.
- Rejected evidence invalidates dependent financial facts, decision, and rationale together.
- Explanations derive from accepted proof facts, cite material supporting message/image/event IDs, and do not exaggerate missing evidence as certainty.
- Prompt injections remain untrusted data and cannot alter schema, eligibility, protected categories, budgets, tools, or source registry.

## Financial safety

- Existing balance is not changed by replaying historical settled records.
- Pending debit reservation and eventual settlement count once; pending credits and unrealized values do not fund payments.
- Recurrence and future income have support; essential variable spending is conservatively reserved.
- FX direction and settlement date match supplied rates.
- Every plan passes prefix balance checks throughout the forecast, including the critical same-day/boundary behavior.
- Earliest full-payment date is baseline capacity, independent of method preference and optional cuts.
- Full/partial/installment/wait rules, total financing cost, deadlines, term limits, and tie-breaking match the contract.
- Spending cuts respect recurrence, flexibility, user category permission, protection, floor, and three-action limit.
- Status, method, explanation, schedule, and evidence tell the same story; uncertain fallback rows are identified in diagnostics.

## Operations and evaluation

- Tool calls are actually implemented, read-only, request bound, schema checked, and budgeted.
- All external calls, including vision, repairs, and SDK retries, share explicit timeout/call/token/cost accounting.
- Backoff obeys remaining deadline; auth/schema errors are not blindly retried as transient failures.
- Cache invalidates on content/model/prompt/schema/context changes and preserves usage provenance.
- One failed row cannot erase valid rows; systematic/programming errors cannot be presented as a clean run.
- CSV is validated before atomic publication, re-read with explicit checks, and protected against accidental dataset overwrite.
- Fixed development/report split exists; examples are not reused silently for both tuning and reporting.
- Baseline and assisted metrics use the same subset, distinguish currencies, and disclose public-sample exposure and degradation.
- Final output, run manifest, audit trail, and usage report match the same run and hashes; missing usage is not reported as known zero.
- Code archive has the required internal layout and an exercised clean setup/run path.

## Finding format

```text
[P1] Short concrete title — path:line
Trigger/reproduction:
Observed behavior:
Required behavior and impact:
Minimal correction:
Regression test:
```

Use P0 for release-blocking systemic unsafe behavior or invalid deliverables, P1 for material correctness/security defects, P2 for bounded reliability/measurement problems, and P3 for optional polish. Distinguish reproduced failures from risks inferred through code inspection. Do not manufacture findings to make a review look thorough.
