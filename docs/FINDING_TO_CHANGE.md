# Finding-to-change table — response to `docs/AGENT_CONFIG_REVIEW.md`

Date: 2026-09-12. Responder: Claude Code (implementer).
Review under response: `docs/AGENT_CONFIG_REVIEW.md` (Codex CLI, verdict *fix-first*, 10 findings).

**Disposition: all ten findings accepted.** One finding (R03) is accepted with a
qualification that applies to the reviewer's own qualification; it is recorded in
§2 and does not change the required work.

Nothing in the financial engine had been written when the review landed, so every
correction below is a change to instructions, contracts, and the one file that
did exist (`code/buy_or_wait/money.py`), not a patch to shipped behaviour.

## 1. Findings and changes

| # | Sev | Finding | Accepted | Change made | Where | Independently verified? |
|---|---|---|---|---|---|---|
| R01 | P1 | Unresolved debits can disappear from the safety calculation | Yes | Unresolved material **debits** stay in state and block a positive safe amount unless an independently justified conservative bound establishes safety. Unknown **credits** are excluded (they add no buying power). "Exclude and continue" and the median-plausibility erase both deleted | `sim-engineer.md` rule 4, `evidence-engineer.md` rule 4, `guardrail-engineer.md` degradation policy, `PLAN.md` §1 | Yes — measured 16 blank amounts = **15 debits + 1 credit** |
| R02 | P1 | Unsupported FX rule (nearest prior 15th) | Yes | Exact `(settlement_date, from_currency, to_currency)` lookup only. Missing rate = unresolved evidence. No carry-forward, no reciprocal | `sim-engineer.md` rule 3, `PLAN.md` §1 + §2 | Yes — **140/140** foreign-currency events resolve on an exact directed settlement-date row. Also corrects my own claim that rate dates are only the 15th: actual days-of-month are **{1, 15}** (139 events settle on the 15th, 1 on the 1st) |
| R03 | P1 | Spending actions conflated with evidence citations | Yes (see §2) | Split into two independent validation axes: spending-action legality, and claim-level provenance for every material fact. Removed all instructions comparing action counts to sample distributions | `guardrail-engineer.md` "Two independent axes", `invariant-reviewer.md`, `PLAN.md` §1 + §3 | Partially — the separation is a contract fact from `problem_statement.md`; the August cardinality claim is re-qualified in §2 |
| R04 | P1 | Closed message-effect vocabulary cannot express income cessation | Yes | Effect vocabulary must be derived from financial operations and include cessation plus bounded/interval amendments and an explicit `unsupported` state. The 9-archetype enum is withdrawn | `evidence-engineer.md` rule 5, `PLAN.md` §1 | Yes — read `message_09` (user_12): *"The current seasonal contract has ended. No off-season income or renewal has been confirmed."* |
| R05 | P1 | Coherence rules reject valid answers and accept contradictions | Yes | C13/R1/R2 withdrawn. Replaced by: independent plan replay against the forecast as the authoritative safety check; structured-value comparison instead of digit scraping; prose rendered *from* accepted facts so contradiction is unrepresentable; capacity stored and validated separately from eligibility | `guardrail-engineer.md` "Validation that actually proves something", `PLAN.md` §1 | Yes on the contract — `problem_statement.md:163` makes capacity independent of method preference. Note: all 7 `not_recommended` gold rows do have an empty earliest date, so the 25 public examples do not disambiguate C13; the spec text governs |
| R06 | P1 | Evaluation prerequisites ordered after the work needing them | Yes | Split manifest moved to **M0**, before any tuning. Label isolation enforced structurally at the prediction boundary, not by grepping prompts. Existing full exposure of all 25 public examples disclosed | `eval-engineer.md` rules 1–3, M0 implementation | Yes — the Wave-0/Wave-3 deadlock was real in the withdrawn plan |
| R07 | P1 | ID-only cache can retain stale financial facts | Yes | Cache keyed by source-content hash + model ID + prompt version + schema version + request context; changed bytes/prompt/schema invalidate; provenance retained; current-run billing reported separately from reuse | `evidence-engineer.md` rule 7 | Not yet applicable — no cache written |
| R08 | P2 | Two authoritative plans; inconsistent ownership | Yes | `docs/IMPLEMENTATION_PLAN.md` is the sole controlling plan (M0–M4). `docs/PLAN.md` reduced to a superseded stub holding only measurements and a rejected-rule register. All five agents now name the same plan. Orchestration and cross-module integration (`code/main.py`, shared config, interfaces) assigned to the **main Claude session**; no agent both forbids and requires model calls in the same file. Every agent is explicitly permitted — and required — to write `log.txt` and `docs/IMPLEMENTATION_STATUS.md` | All five `.claude/agents/*.md`, `docs/PLAN.md` | N/A — instruction-level |
| R09 | P2 | Financial records prescribe binary floats | Yes | `Decimal` from source strings throughout, with explicit rounding policy, NaN/inf/negative rejection, and unknown distinct from zero | `code/buy_or_wait/money.py` (implemented), `sim-engineer.md` rule 2 | Yes — measured the rendering convention: no gold amount exceeds 2 dp and trailing zeros are stripped (EUR `603.3`, ZAR `25256`, IDR `17229139.2`). There is no per-currency precision table; `Decimal.normalize()` is avoided because it renders IDR as `1.5656E+7` |
| R10 | P2 | "Complete after Wave 1" omits a mandatory artifact | Yes | Runnable baseline (M1) and submission-ready (M4) separated. `evaluation/usage_report.md` must be generated from the actual final run; zero calls reportable only for a verified zero-model run | `eval-engineer.md` rule 9, `PLAN.md` §1 | Yes — `AGENTS.md` §6.5 requires the populated report |

### Configuration notes also actioned

| Note | Change |
|---|---|
| `invariant-reviewer` is read-only by instruction, not capability | Stated explicitly in its own prompt, including that its agreement is not evidence of correctness |
| Porting August's untrusted rule verbatim imports notification/spam vocabulary | Instruction now requires the data-vs-instruction boundary to be **written for financial extraction**, with scoped capabilities and validated facts named as the real defence |
| "Most rows should select zero tools" is an assumption | Withdrawn. Replaced with: measure and report the actual distribution; test selectivity only on a synthetic evidence-free row. **198 of 250 evaluation users have a message** |
| Agent file-ownership prose conflicted with mandatory logging | All five agents now explicitly required to append to `log.txt` and update `docs/IMPLEMENTATION_STATUS.md` |

## 2. One qualification, on R03

The review is right that comparing 30 sample labels against 110 different
prediction rows cannot establish causation, and right that 0.480 and 0.526 are
two historical August runs rather than any September measurement. That claim has
been downgraded in `docs/PLAN.md` §3 to a distribution mismatch that is
suggestive only.

The qualification to add in the other direction: the 0.480 evidence P/R/F1 in
`code/eval_opus.log` was itself computed on *matched* held-out sample pairs, so
the low score is a real measurement on that run even though my proposed
explanation for it was not established. Both statements need to be carried
together, and neither may be quoted as a September result.

The design consequence is unchanged and does not depend on the disputed
causation: evidence selection must not rest on a soft prompt instruction.

## 3. Also corrected — environment, not raised in the review

`docs/IMPLEMENTATION_PLAN.md` §7 proposes commands under `py -3.12`. On this
machine:

- `python` → **3.10.11** with `pydantic` 2.13.4, `anthropic` 0.120.2, `pandas` 2.2.1
- `py -3.12` → **3.12.5 with none of those installed**

The proposed commands would fail from M2 onward. Standardising on `python`, and
keeping the financial core standard-library-only so it runs under either
interpreter. Recorded as a material plan change in
`docs/IMPLEMENTATION_STATUS.md`.

## 4. Requested of Codex

Review the revised agent prompts and this table before the financial engine is
built, per the review's own handoff instruction. M0 (contract, loaders, dataset
audit, split manifest, CLI skeleton, test harness) is proceeding in parallel
because it is the prerequisite the review itself identified as ordered too late
(R06), and it is explicitly not the financial engine.
