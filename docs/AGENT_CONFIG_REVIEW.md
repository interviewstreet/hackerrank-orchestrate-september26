# Review of Claude agents and configuration

Date: 2026-09-12. Reviewer: Codex CLI. Verdict: **fix-first**.

Scope: all five `.claude/agents/*.md` files, their referenced `docs/PLAN.md`, root `AGENTS.md` and `CLAUDE.md`, shared/local settings, the September contract, and relevant participant data. This is a review of implementation instructions, not a claim that the defects already execute in application code. Both application/evaluation entry points remain empty. No implementation agent or paid model run was launched.

## Overall assessment

The responsibility split is useful: simulation, evidence, guardrails, evaluation, and an optional internal reviewer. Closed output enums, offline tests, explicit failure reporting, and bounded runtime calls are good directions. The files have distinct names, descriptions, model settings, tool lists, and nonempty prompts. Both settings files parse as JSON.

However, several instructions would produce incorrect financial behavior if implemented literally. The reviewer is also told to validate those same incorrect rules, so agreement between these agents would not independently establish correctness. Correct the shared contract first, then align the agent prompts with it.

## Findings

### R01 — P1: Unresolved debits can disappear from the safety calculation

Source: `.claude/agents/evidence-engineer.md:45`, `docs/PLAN.md:569`, `docs/PLAN.md:579`.

The evidence agent must exclude an event when an image is missing, OCR fails, or a broad median-based plausibility check rejects its amount. The failure matrix says the row continues. Budget exhaustion likewise proceeds using the evidence collected so far. None of those instructions requires a conservative bound for a missing obligation.

There are **15 blank debit amounts** in this dataset. An unresolved debit is not equivalent to no debit. For a synthetic balance of 1,000, minimum 200, request 500, and unreadable essential bill of unknown size, removing the bill creates apparent headroom of 800 without proving it exists.

Correction: keep material unresolved obligations in the state. Approve only if a justified conservative bound establishes safety; otherwise emit the audited conservative fallback. Unknown credits may be excluded without adding buying power. Do not downgrade an invalid target, failed required investigation, or unknown salary amendment into a financially neutral `no_effect` automatically. Median comparisons must use compatible currency and event context and must not erase liabilities.

Required test: an unreadable essential debit and a budget-exhausted required investigation cannot produce a positive safe payment without an independently supported bound. A failed optional investigation may preserve an otherwise complete decision.

### R02 — P1: The simulation agent inherits an unsupported FX rule

Source: `.claude/agents/sim-engineer.md:27`, `docs/PLAN.md:303`, `docs/PLAN.md:692`.

The plan requires the nearest prior 15th's rate and labels it conservative. `AGENTS.md` section 6.1 instead requires the settlement-date rate in the supplied direction. Choosing an older rate is not necessarily conservative for either credits or debits.

Recheck: all **132 settled foreign-currency events** have an exact directed settlement-date rate. The fact that rate records currently occur on the 15th does not authorize carrying them forward to arbitrary dates.

Correction: use exact date/pair lookup. Treat a missing required rate as unresolved evidence; do not invent a carry-forward conversion or future exchange-rate assumption.

Required test: an event with only an earlier rate available cannot silently use it. Exact-date and reverse-direction cases must be tested separately.

### R03 — P1: Spending actions are incorrectly treated as evidence citations

Source: `.claude/agents/guardrail-engineer.md:19`, `.claude/agents/invariant-reviewer.md:23`, `docs/PLAN.md:101`, `docs/PLAN.md:403`.

`spending_changes_needed` specifies financial interventions. It is not September's replacement for August's evidence field. A fully affordable request can have no spending changes while depending critically on a payroll message or image. Comparing intervention count to August citation cardinality can encourage unnecessary spending cuts or suppress necessary evidence.

The listed E1–E14 rules primarily protect changed event IDs and installment offers. They do not establish that every explanatory message/image reference was retrieved and supports its associated claim. A valid message ID with irrelevant content is still invalid support.

Correction: separate (1) allowed spending actions and their event targets from (2) claim-level provenance for all material financial facts. Validate source existence, request/user scope, retrieved membership, availability, and field/claim support. Carry message/image/event references through the calculation into the explanation. Do not require the action-count distribution to match public examples.

Required test: a full-payment decision justified by an unretrieved, wrong-user, or irrelevant message fails even when `spending_changes_needed=none`. Removing the support must invalidate/recompute the dependent claim and decision.

The diagnosis of August over-citation should also be qualified: comparing 30 sample labels with 110 different prediction rows cannot establish the cause or numerical effect on precision/recall. The cited 0.480 is a particular historical run; another August journal reports 0.526. Neither is a fresh September measurement.

### R04 — P1: The closed message-effect vocabulary cannot represent supplied income cessation

Source: `.claude/agents/evidence-engineer.md:29`, `docs/PLAN.md:500`, `docs/PLAN.md:518`.

The agent must use the plan's allegedly verified closed archetype set. The table has no explicit way to stop future recurring income when a seasonal contract ends. This is not hypothetical: `message_09` says the contract ended and no off-season income or renewal is confirmed. Treating this as `no_effect` can leave inferred future salary funding purchases.

The declared `MessageEffect` also has only one effective date, although the table promises bounded temporary changes. That needs a defined representation for the affected occurrence or interval; confidence is not a substitute.

Correction: derive a small complete internal effect schema from financial operations, including cessation/cancellation and bounded amendments, and preserve unknown/unsupported interpretations explicitly. Distinguish these internal effect kinds from dataset event categories. Do not force every message into a convenient but financially inaccurate existing kind.

Required test: a synthetic contract-ended message prevents unsupported recurring salary after cessation. A one-pay-cycle reduction affects only its supported period.

### R05 — P1: The mandated coherence rules can reject valid answers and accept contradictions

Source: `.claude/agents/guardrail-engineer.md:47`, `.claude/agents/invariant-reviewer.md:30`, `docs/PLAN.md:471`, `docs/PLAN.md:478`.

All agents are required to implement/review the plan's C/R rules literally, but those rules are not a sound substitute for the September contract:

- C13 forces `earliest_date_for_full_payment` empty for every `not_recommended` decision. Capacity is independent of payment preference (`problem_statement.md:163`). A user can have enough cash today but accept only an unsafe installment offer; no eligible payment does not erase the known capacity date.
- R1 regex-extracts every numeral but permits only a short amount list. Valid dates, message/event IDs, installment counts, and fees can introduce other numerals. For example, a truthful `message_198` reference must not fail merely because 198 is not a payment amount.
- R2 uses keyword membership. “Do not pay today; wait” contains “today” and can pass the full-payment keyword rule while contradicting that method.
- Passing E/C/R as listed does not independently prove minimum-balance safety after every essential movement or completion of every selected installment by the deadline. Matching an offered schedule alone is insufficient.

Correction: validate typed fields and independently replay the payment plan against the forecast, then render prose from accepted proof facts. Preserve capacity separately from eligibility. Compare structured claim values rather than arbitrary digit or keyword sets. Revise incorrect rules before adding tests that cement them.

Required tests: known capacity with no eligible method; valid cited ID/date/count in an explanation; contradictory prose containing expected keywords; exact seller schedule that nevertheless breaches the minimum or misses the deadline.

### R06 — P1: Evaluation prerequisites occur after the work that requires them

Source: `.claude/agents/sim-engineer.md:47`, `.claude/agents/eval-engineer.md:8`, `docs/PLAN.md:343`, `docs/PLAN.md:491`.

Simulation is Wave 0, and its agent must stop calibration when `splits.py` does not exist. The evaluation agent creates that file in Wave 3. The written ordering therefore blocks the earlier core/calibration work or encourages ad hoc use of all examples.

The plan also explicitly says rationale rules were reverse-engineered from all 25 labeled examples. A subsequently selected reporting subset is not untouched holdout data. Grepping prompt files for holdout IDs cannot detect copied answers with IDs removed, labels embedded in fixtures, or label fields passed into inference.

Correction: establish split ownership and the fixed manifest before tuning. Pass only request input columns into prediction code. Record the existing sample exposure and distinguish public-sample regression/reporting from an unbiased holdout claim. Keep a deterministic baseline and report degradations separately; if using a failure-penalized metric, label it separately from ordinary prediction-vs-label accuracy.

Required tests: split disjointness by request/user; no expected-output fields reach the prediction boundary; baseline runs without a provider or API key. Do not tune action counts or wording on the reporting subset.

### R07 — P1: ID-only caches can silently retain stale financial facts

Source: `.claude/agents/evidence-engineer.md:49`, `docs/PLAN.md:143`.

The agent is told to cache by ID and port the old cache unchanged. Reusing an image/message ID after its content changes, or changing the extraction model/prompt/schema, can return old amounts without a new validation or provider call. The promise that reruns “cost nothing” also ignores planner/explanation calls and invalidated entries.

Correction: key by content hash, model, prompt/schema version, and relevant request context. Revalidate cached records and preserve their original run provenance. Report actual current-run billing separately from historical cached extraction costs and any unknown usage.

Required test: changed image bytes, message text, prompt, or schema invalidate a same-ID cache entry; unchanged validated input can reuse it with provenance.

### R08 — P2: Two plans and incompatible ownership boundaries leave integration undefined

Source: `CLAUDE.md:6`, `.claude/agents/sim-engineer.md:12`, `.claude/agents/sim-engineer.md:23`, `.claude/agents/evidence-engineer.md:41`, `.claude/agents/eval-engineer.md:33`.

Root instructions direct work through `IMPLEMENTATION_PLAN.md` and its M0-first handoff. All five new agents instead treat `PLAN.md` and its Wave 0–4 ordering as their contract. They differ in schemas, modules, CLI flags, split sizes, and financial policies. Merely choosing different package names is fine; leaving both authoritative is not.

Ownership is also internally inconsistent. The simulation agent owns `main.py` but forbids model calls anywhere in its scope, while the evidence agent requires `main.py` to execute model tools. The evaluation agent is told to write calibrated constants into simulation-owned `config.py`. There is no explicit integration owner or handoff for those shared files.

Correction: reconcile the contract differences and designate one implementation plan, marking the other superseded or mapping its milestones explicitly. Keep provider-free financial modules, but give the main Claude session ownership of orchestration and cross-module integration. Define interfaces and handoffs before delegating dependent work. An internal Claude review can supplement, but should not replace, the participant's requested Codex review.

Acceptance check: every agent names the same controlling plan and milestone, shared files have one integration owner, and the first milestone has all prerequisites available. No unsolicited background delegation is necessary to use these role descriptions.

### R09 — P2: Financial record types prescribe binary floats

Source: `.claude/agents/sim-engineer.md:13`, `docs/PLAN.md:242`, `docs/PLAN.md:269`, `docs/PLAN.md:274`.

The proposed core stores event amounts, reductions, safe amounts, and installment amounts as `float`, while requiring exact plan equality, totals, and threshold decisions. Values such as 0.1 and 0.2 do not sum exactly to 0.3 in binary floating point. Boundary comparisons can reject valid schedules or overstate available headroom after rounding.

Correction: use `Decimal` from source strings for monetary values and FX arithmetic with an explicit rounding policy. Reject NaN/infinity and avoid rounding safe capacity upward. Update agent instructions and shared schemas together.

Required test: fractional payment totals and a payment leaving exactly the minimum balance behave correctly, including after currency conversion.

### R10 — P2: “Complete after Wave 1” omits a mandatory submission artifact

Source: `docs/PLAN.md:295`, `docs/PLAN.md:346`, `docs/PLAN.md:697`.

The plan calls Wave 1 complete/submittable and says later work is optional for validity. The required final-run usage report is not generated until Wave 3. An empty report does not meet `AGENTS.md` section 6.5 even for a zero-model baseline. Packaging also needs the required archive layout and reproducible setup.

Correction: separate a runnable baseline milestone from submission readiness. The minimum shippable milestone must include final-run usage accounting/reporting, required package contents, output verification, and disclosure of unresolved evidence. Zero calls/tokens can be reported only for an actual verified zero-model run.

Required check: the archive contains a populated `evaluation/usage_report.md` tied to the generated output and the actual run.

## Configuration and operational notes

- Shared `.claude/settings.json` remains the previously added `Edit(/dataset/**)` rule. The existing `.claude/settings.local.json` hash is unchanged: no new broad shell allow rule or permission bypass was introduced.
- The five files follow the documented Markdown/frontmatter shape. `model: opus` is a supported alias, not a syntax error. No `maxTurns` is set; this is optional, but a bounded per-task limit can help control coding-agent work. These coding-agent settings are separate from the submission's per-request runtime budget. See [Claude subagent configuration](https://code.claude.com/docs/en/sub-agents).
- `invariant-reviewer` is read-only by instruction, not strictly by capability: it has both PowerShell and Bash. Likewise, prose file-ownership lists are not enforced filesystem boundaries. Test commands may write files. Use the main session for test execution or a narrowly enforced command policy if stronger isolation is required; do not claim dropping Write/Edit tools alone guarantees no writes. The dataset Edit rule does not sandbox arbitrary subprocess file access. See [Claude permissions](https://code.claude.com/docs/en/permissions).
- The evidence agent's instruction to port August's untrusted rule verbatim also imports notification-routing and spam/scam language. Retain the data-versus-instruction boundary, but write it for financial extraction. Delimiters alone are not the strongest security guarantee; scoped capabilities and validated facts are essential.
- Do not impose a target that most requests need zero tools. **198 of 250 evaluation users have messages**. Whether those messages have no financial effect is something to establish, not assume before reading them. Test selectivity on a truly evidence-free synthetic row and measure the actual distribution.
- Each custom agent should explicitly follow the shared logging/handoff requirements, including its actual parent identity. “Only edit these source files” should allow mandatory logging and milestone reporting. Otherwise ownership prose conflicts with the root requirements.

## Checks performed and limits

- Read every agent definition and its referenced plan; compared instructions with the September contract and existing workflow.
- Checked all five files for distinct required frontmatter names/fields and nonempty bodies using a local structural check. This was not a full YAML parser or a live Claude dispatch test.
- Parsed both settings files as JSON and confirmed the machine-local configuration hash remains unchanged.
- Rechecked blank debit count, all settled foreign-event exact FX lookups, and evaluation message coverage from participant CSVs.
- Verified both application/evaluation entry points remain zero bytes. There is no implemented test suite against which to run these proposed behavior checks.
- No agent definition, settings file, implementation file, or dataset was modified for this review. Only this review artifact and the mandatory shared log were written.

## Claude correction handoff

First reconcile R01–R08 into one controlling plan and update the five agent prompts so they cannot reintroduce the rejected rules. Fix Decimal types and submission completion criteria at the same time. Keep the useful role separation and offline-test expectations. Return the revised instructions and a short finding-to-change table for Codex review before implementing the financial engine.

VERDICT: fix-first
