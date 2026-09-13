# Implementation status

Implementer: Claude Code. Controlling plan: `docs/IMPLEMENTATION_PLAN.md`.
Review standard: `docs/REVIEW_CHECKLIST.md`.

---

## M0 — contract and measurement (complete; hardened after code review)

**Milestone and status:** M0 complete, including the input-boundary cleanup
required by `docs/reviews/M0_CODE_REVIEW.md`. M1 not started, by instruction.
Current suite: **106 tests, passing on Python 3.10.11 and 3.12.5.**
The M0 section below describes the original pass; the cleanup is recorded after it.

**Problem solved and observable behavior:**
The repository had three zero-byte Python files and no contract, loaders, tests,
or split. It now loads and validates the whole dataset strictly, audits it across
rows, freezes the development/reporting split, and exposes two CLIs. Both
prediction modes are wired and deliberately refuse to run until M1, so no
placeholder row can be mistaken for a baseline.

```
python code/main.py                           -> dataset audit, 0 findings, exit 0
python code/main.py --mode deterministic      -> refuses, writes nothing, exit 2
python code/evaluation/main.py --show-split   -> audit header + frozen split, exit 0
python -m unittest discover -s code/tests -t code -p "test_*.py"  -> 77 tests, OK
```

**Files changed and why:**

| File | Responsibility |
|---|---|
| `code/buy_or_wait/money.py` | `Decimal` parsing, rounding policy, dataset rendering convention. Rejects NaN/inf/negative; blank stays `None` |
| `code/buy_or_wait/schema.py` | Output contract (8 columns), closed input vocabularies, typed records |
| `code/buy_or_wait/data.py` | Strict loaders, exact-header checks, indexes, request scoping, sha256 input manifest |
| `code/buy_or_wait/audit.py` | Cross-row structural/referential audit, findings A01–A12 |
| `code/buy_or_wait/__init__.py` | Package doc and module map |
| `code/main.py` | CLI: audit / deterministic / assisted, exit codes 0/1/2 |
| `code/evaluation/splits.py` | Frozen split manifest: compute, write once, thereafter verify only |
| `code/evaluation/labels.py` | The only module permitted to read expected outputs |
| `code/evaluation/main.py` | Evaluation CLI and the pre-metric audit header |
| `code/evaluation/split_manifest.json` | The frozen split (generated once) |
| `code/tests/fixtures.py` | Synthetic contract-valid dataset builder + single-cell mutators |
| `code/tests/test_{money,data,audit,splits}.py` | 77 offline tests |

Also: `docs/PLAN.md` reduced to a superseded stub, `docs/FINDING_TO_CHANGE.md`
added, all five `.claude/agents/*.md` rewritten (see the review response below).

**Contract/architecture decisions, including alternatives rejected:**

1. **`money.py` added** beyond the plan's suggested decomposition. The plan's §3
   mandates `Decimal` with an explicit rounding policy; concentrating it in one
   module keeps the convention testable and stops it being re-derived per caller.
2. **Rendering convention is measured, not tabulated per currency.** Rejected a
   per-currency precision table: across all 25 gold rows no amount exceeds two
   decimals and trailing zeros are stripped (EUR `603.3`, ZAR `25256`, IDR
   `17229139.2`). `Decimal.normalize()` is avoided because it renders IDR as
   `1.5656E+7`.
3. **Two separate category vocabularies, only one of them gating.**
   `expense_categories_to_protect` / `_reduce` / `_stop` are validated strictly
   against the 22 event categories, because they authorize interventions.
   `financial_priorities` is accepted as-is and only reported by the audit,
   because a priority authorizes nothing. Rejected the alternative of validating
   both against one set — it would reject 278 legitimate tokens
   (`emergency_savings`, `retirement_investment`, `travel` are goals, not
   categories). This surfaced as a real failure: my first constant listed seven
   priority tokens and the data has eight (`healthcare` was missing).
4. **No category alias layer.** Measured: every protect/reduce/stop token is
   already an exact event category, and every user's willing-to-change tokens
   match at least one of their own events. An alias map would be speculative
   complexity with nothing behind it.
5. **Booleans accept case variants, reject everything else.** `TRUE`/`True` are
   formatting; `1`, `yes`, blank are semantic guesses. This column decides
   `allows_partial_payment` on 80 requests.
6. **Prediction modes exit 2 rather than emitting rows.** Per
   `docs/CLAUDE_HANDOFF.md`: an `output.csv` of zeros is not a baseline.
7. **Split is hash-ordered, not seeded-random**, so it reproduces on any machine
   and Python version without depending on RNG stability.

**Tests and exact commands, with results and failures:**

```
$ python -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 77 tests in 4.293s
OK
```

Four failures were hit and fixed during the pass, not papered over:
- 3 × `DataError: 'healthcare' is not a known priority` — root cause was my
  incomplete constant; fixed by the design change in decision 3 above.
- 1 × boolean test asserted rejection of `TRUE` while the code accepted it —
  docstring and code disagreed; resolved in favour of decision 5 and the test
  split into two (rejects semantic guesses / normalizes case).

Coverage highlights: strict parsing and every rejection path; blank amount is
`None` and never `0`; row-order independence; request scoping does not leak
another request's message; label isolation (structural + behavioural + a grep
asserting `buy_or_wait/` never imports `evaluation`); audit defects A04 cross-user
link / dangling / self-link / cycle, A05, A06, A07, A08, A09, A10, A11; split
determinism, order-independence, disjointness, and refusal to regenerate after a
hand edit.

**Evaluation run IDs, split and metrics:** No metrics — scoring is M1. The split
is frozen at fingerprint `ecafb49177d9`, 10 development / 15 reporting,
disjoint by request **and** by user, containing no evaluation request id.

**Evidence/financial safety checks completed:**
- Real dataset audit: **0 findings, 0 errors**, 250 requests / 275 profiles /
  25,342 events / 790 options / 215 messages / 16 images.
- 16 unknown amounts confirmed as **15 debits + 1 credit**; every one has a
  linked image; an unknown amount with no image is a hard A07 error.
- **140/140** foreign-currency events resolve on an exact directed
  settlement-date rate — verified in a test, which is what makes "exact lookup,
  no fallback" safe rather than aspirational. A test proves an earlier-dated
  rate does not satisfy a later settlement date.
- All 790 payment offers satisfy `payment_amount × n == total_payable_amount`
  under `Decimal`; a mismatch is an A06 error, never repaired.
- Input file hashes recorded; `git status dataset/` clean.
- Secret scan of `code/` returns nothing.

**Known limitations and degraded cases:**
1. **Sample exposure is real and disclosed.** All 25 public examples were read
   during planning, before the split existed — including rows that landed in the
   reporting subset (`request_06`, `request_11`, `request_19`, `request_21` were
   quoted with their gold values in planning documents). Reported numbers must be
   labelled *fixed public-sample reporting subset, prior exposure disclosed*,
   never "held-out". Re-drawing the split to move quoted rows into development
   was rejected as exactly the manipulation the manifest exists to prevent.
2. `code/evaluation/usage_report.md` is still empty. It is an M4 deliverable and
   must be generated from the actual final run.
3. The audit is structural. It makes no financial judgement and does not
   semantically verify image contents.
4. `messages.sent_at` is validated as ISO-8601 and kept verbatim; no user
   timezone is assumed. The request-date availability cutoff is M2's decision.
5. Environment: `python` is 3.10.11 with `pydantic`/`anthropic`/`pandas`;
   `py -3.12` is 3.12.5 with **none** of them. The plan's `py -3.12` commands
   would fail from M2. M0 is standard-library-only and runs under both.

**Next milestone:** M1 — cash-state reconstruction, recurrence, FX, forecast,
full/wait/fallback, atomic eight-column output.

**Review requested from Codex:** Yes. Please review this diff against
`docs/IMPLEMENTATION_PLAN.md` §3–§4 and `docs/REVIEW_CHECKLIST.md` "Contract and
data". Specific things worth attacking: the gating/non-gating vocabulary split
(decision 3), the rendering convention (decision 2), the exit-2 behaviour
(decision 6), and whether the request-scoping rule in
`data.DataSet.request_context` is the correct availability boundary before M2
adds a time cutoff.

---

## M1 — deterministic financial core (complete, ready for Codex review)

**Milestone and status:** M1 complete and model-free. No provider imports, no
network, no API key. Runs on Python 3.10.11 and 3.12.5.

**Problem solved and observable behavior:** the engine now reconstructs cash
state, converts currency, detects recurrence, forecasts 90 days, decides
`full_payment` / `wait` / `not_recommended`, gates every row, and publishes the
eight-column `output.csv` atomically.

```
$ python -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 150 tests in 6.979s          OK      (3.10.11)
Ran 150 tests in 6.571s          OK      (3.12.5, py -3.12 -B)

$ python code/main.py --mode deterministic
audit: 0 finding(s), 0 error(s)
wrote 250 rows to <repo>/output.csv
method distribution: full_payment=53, not_recommended=186, wait=11
degraded rows: 2 | gate failures: 0 | unhandled errors: 0

$ python code/evaluation/main.py --split dev
affordability_status      : 5/10
recommended_payment_method: 5/10
```

**Files added:** `code/buy_or_wait/{config,fx,state,recurrence,forecast,planner,validation,output}.py`,
`code/evaluation/metrics.py`, `code/tests/{oracle,test_engine}.py`.
**Files changed:** `code/main.py` (prediction path + `decide_one`),
`code/evaluation/main.py` (scoring).

**Core routing function:** `main.decide_one(context, rates)` —
`state.reconstruct` → `recurrence.detect` → `forecast.build` →
`planner.choose` → `validation.check`, with a conservative fallback on any gate
failure. Every request takes exactly this path.

### Contract decisions, including alternatives rejected

1. **Recurrence is modelled in two parts, not one.** Fixed commitments (constant
   amount, regular cadence) project as discrete dated movements, because *when*
   they land decides whether the balance dips. Everything else is reserved as a
   per-category daily rate built from what the user actually spent.
   An earlier single-model version was wrong in both directions at once:
   requiring three occurrences dropped 12 of 25 real series for `user_13`
   (under-reserving), while taking the maximum observed amount over-reserved the
   ones it kept. Using observed totals over the observed window is
   self-calibrating. DEV method accuracy 3/10 → 5/10 on this change alone.
2. **Income needs two occurrences, spending needs three**, and income groups by
   *category* rather than description. `user_01`'s salary appears as "Prorated
   first salary" then "Next confirmed salary" — one cadence under two names.
   Requiring three description-matched occurrences forecast no salary at all and
   made an `affordable_now` row look unaffordable.
3. **Lapsed income is not carried forward.** A series silent for more than one
   full period has stopped. This is the deterministic half of the ended-seasonal-
   contract case (`message_09`); M2 adds the message-driven half.
4. **Intra-day order is existing debits → credits → proposed payment.**
   Obligations first is conservative (the user does not control when a direct
   debit clears). A *proposed* payment goes last because the user chooses when to
   pay. This is evidence-driven, not aesthetic: gold
   `earliest_date_for_full_payment` values are repeatedly the salary date itself,
   which is unreachable if a voluntary payment must precede that day's credit.
   Ranking the payment first shifted every such answer one day late.
5. **Recurring `investment` contributions are not reserved as essential.**
   `problem_statement.md` defines safety as covering *essential* expenses; a
   recurring contribution is the user moving money into savings. Confirmed future
   investment debits are still reserved — this affects projection only.
   CALIBRATED on DEV: ZAR normalized MAE 0.123 → 0.061, mean date error 17.5 →
   14.6 days.
6. **An unquantified debit blocks every recommendation.** `Forecast.certifiable`
   is False while any obligation cannot be quantified, which forces
   `amount_safe_to_pay` to 0 and suppresses all candidates. Implements review
   finding R01. A bug found by the gate during the first run: the planner was
   generating `full_payment` from `is_safe()` without consulting `certifiable`.
7. **Safety is proved by replay, never by shape.** `validation.check` re-walks
   the forecast with the chosen schedule injected (rule P1). Tests compare
   against `code/tests/oracle.py`, an independent replay written from the
   contract, plus hand-computed fixtures.

### Verification

150 tests, all offline. Notable: forecast agrees with the independent oracle
across three payment scenarios; hand-computed balance; landing exactly on the
minimum is safe and one cent below is not; same-day debit/credit ordering;
a later bill blocks a payment that looks affordable today; window boundaries at
day 0 and day 90; the metamorphic check that an extra debit can never increase
capacity; unquantified debit forces zero; every settled debit is counted exactly
once (no event feeds both a series and a rate).

Independent check of the published `output.csv`: exact header, 250 rows in
requests.csv order, unique ids, and **0 invariant violations** across bounds,
enum membership, plan chronology, plan totals, deadline compliance,
`affordable_now` date rule, status/method agreement, and non-empty explanations.

### Known limitations and degraded cases

1. **74% of rows are `not_recommended`, and most of that is missing capability,
   not genuine refusal.** `installments`, `partial_payment` and spending changes
   are M3. On DEV, 2 of the 5 remaining failures are exactly this — and the
   forecast behind them is accurate (`request_17`: our 243798.78 vs gold
   243849.58, a 0.02% difference, refused only because the user does not accept
   `full_payment`). **This output.csv is a partial-capability baseline and must
   not be reported as a finished submission.**
2. **2 rows are degraded** (unquantified obligation → zero safe amount). Both
   need M2's image extraction. `request_16` is the DEV example.
3. **`request_03` is silently under-forecast**, and this is the most interesting
   M2 dependency: its salary is one of the 16 blank amounts, so recurrence builds
   a 1,964,250/month series when the linked payslip says 4,365,000. The row is
   *not* marked degraded — correctly, because the unknown event is settled and
   historical, so it is already inside `current_available_balance`. The balance
   is right; the projection is not. M2 must feed resolved image amounts into
   recurrence, not only into cash state.
4. **Two spec ambiguities the 25 samples cannot settle**, flagged rather than
   guessed:
   - We report `earliest_date_for_full_payment` even on `not_recommended` rows
     when capacity exists within the window (`problem_statement.md:163`;
     corrected C13). All 7 gold `not_recommended` rows have an empty date, but in
     all 7 capacity never arrives, so gold is consistent with either reading.
     `request_32` in the current output is an example of the divergence.
   - `wait` is rejected when the capacity date falls after
     `desired_completion_date`, per `IMPLEMENTATION_PLAN.md` §5. All 6 gold
     `wait` rows meet their deadline, so this too is untested by the samples.
5. **DEV exposure**: constants in decisions 5 and 2 were chosen against the
   development subset only. The reporting subset has not been scored.
6. `evaluation/usage_report.md` remains empty — M4, and correct for a run with
   zero model calls until that run is the final one.

**Next milestone:** recommend **M3 before M2**. M3 covers ~24% of gold rows
(installments 20%, partial 4%); M2's images cover 16 of 275 requests (~6%). The
forecast is already accurate enough that M3 is mostly candidate generation
against `request_payment_options.csv`, which is fully supplied data.

**Review requested from Codex:** yes. Worth attacking specifically: the intra-day
ordering choice (decision 4), the `investment` exclusion (decision 5), the
two-part recurrence model's claim that every settled debit is counted exactly
once, and whether the two ambiguities in limitation 4 are resolved the way you
read the contract.

---

## M3 — partial payment, installments, spending changes (complete, ready for Codex review)

**Milestone and status:** M3 complete and model-free, per the Codex-relayed
next action: partial-payment candidates, supplied installment-option matching,
spending-change candidates, eligibility/preference/deadline/term checks, replay
validation for every candidate, and negative tests for each rule. No provider
imports, no network, no API key added.

**Problem solved and observable behavior:** the M1 core only produced
`full_payment` / `wait` / `not_recommended`. The engine now also generates
`partial_payment` (two-payment schedules for requests that allow it),
`installments` (schedules that exactly match a supplied `request_payment_options.csv`
row and respect `max_installment_months`), and `full_payment` augmented by up to
three `spending_changes_needed` actions (`stop:<event_id>` /
`reduce_to:<event_id>:<amount>`) drawn only from non-protected, user-permitted,
flexible `FixedSeries` debits. Every candidate — including spending-change ones —
is proved safe by an independent replay before it may compete or be published.

```
$ python -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 185 tests in 6.649s          OK      (185 total; 79 in test_engine.py, up from 150/50)

$ python code/main.py --mode deterministic --quiet
audit: 0 finding(s), 0 error(s)
wrote 250 rows to <repo>/output.csv
method distribution: full_payment=53, installments=32, not_recommended=147, partial_payment=7, wait=11
degraded rows: 2 | gate failures: 0 | unhandled errors: 0

$ python code/evaluation/main.py --split dev
affordability_status      : 6/10  macro-F1 0.608
recommended_payment_method: 6/10  macro-F1 0.608
payment_plan (exact)      : 5/10
```

**Files added:** `code/buy_or_wait/spending.py` (spending-change eligibility,
combination search, and the single `apply()` used by both the planner and the
validation replay).
**Files changed:** `code/buy_or_wait/planner.py` (partial-payment, installment,
and spending-change-augmented `full_payment` generators in `generate()`;
`Candidate` gained `spending_changes`/`replay_forecast`; `choose()` replays
against `candidate.replay_forecast or forecast`), `code/buy_or_wait/validation.py`
(rules C5–C10, E1–E7; P1 rewritten to call `spending.apply_literals` so replay
proves the *published* row, not the candidate object), `code/buy_or_wait/output.py`
(explanation templates for `partial_payment`/`installments`, and for
`full_payment` with spending changes), `code/main.py` (`decide_one` passes
`payment_options`/`events` through to `planner.choose`/`validation.check`).

### Contract decisions, including alternatives rejected

1. **A spending action cites the series' most recent real event row, not the
   synthetic future occurrence.** A future occurrence of a `FixedSeries` is a
   `forecast.build`-created movement with an id like
   `projected:category:description:date`, which is not a real CSV row and
   cannot be cited. `series.event_ids[-1]` is the real row the series'
   `flexibility`/`minimum_allowed_amount` were read from, and the action is
   applied to every future occurrence of that `(category, description)` pair
   within the window. Rejected inventing a synthetic id for the projected
   occurrence — it would not resolve against `events_by_id` during the
   independent replay, defeating the point of the check.
2. **Spending changes are scoped to `recurrence.fixed` debit series only**,
   never `recurrence.rates` (the per-category daily-rate essentials). A rate
   series is the sum of many different transactions with no single `event_id`
   to cite as `stop:<event_id>`/`reduce_to:<event_id>:<amount>`; representing
   it at that grain would be a citation the row cannot actually prove.
3. **`apply()` is the single production implementation of "what a spending
   change does to a forecast."** The planner builds live `SpendingAction`
   objects and calls `apply()` directly; the validation gate reconstructs
   actions independently from the *published CSV strings* via
   `spending.from_literal`/`apply_literals` and calls the same `apply()`. This
   is a deliberate midpoint between full duplication (risk the two arithmetics
   drift apart) and zero independence (the gate would just be re-trusting the
   planner) — the gate is independent about *what the row says*, not about
   *how a stop/reduce changes a balance*.
4. **Installment term is `(last_payment_date - first_payment_date).days / 30`
   as a `Decimal`, not calendar-month arithmetic.** Verified empirically
   against the 5 real requests with both accepted and rejected installment
   offers (`request_02/07/12/17/22`, `max_installment_months` 7/12/11/3/6): this
   formula reproduces the accept/reject split gold implies; calendar-month
   differencing does not.
5. **Partial payment always lands its second payment on the same globally
   reported `earliest_date_for_full_payment`**, never a remainder-specific
   earlier date. `problem_statement.md`'s two-payment rule ties the second
   payment to that one figure, and reusing it keeps `amount_safe_to_pay` and
   `earliest_date_for_full_payment` single sources of truth rather than each
   method computing its own capacity date.
6. **`Candidate.replay_forecast` carries a candidate's own adjusted forecast**
   (set only for spending-change candidates) so `choose()`'s verification loop
   can replay each candidate against the forecast it was actually proved safe
   under, while every other candidate still replays against the shared base
   forecast. Rejected mutating a single shared forecast across candidates —
   two spending-change candidates in the same call must not see each other's
   cuts.
7. **The validation gate's P1 rule reconstructs spending effects from the
   published strings, not from `decision`'s originating candidate object.**
   Otherwise a bug that produces a wrong-but-plausible-looking spending literal
   would be validated by the same code path that produced it. This is the same
   principle M1 already applied to plan replay, extended to cover the new
   spending-change dimension.

### Verification

185 tests total (150 → 185), all offline, none touching a provider. The 35 new
tests: `PartialPaymentTests` (5), `InstallmentTests` (5), `SpendingChangeTests`
(3), and `M3GateTests` (19 negative/positive gate cases covering every C5–C10
and E1–E7 rule plus a spending-change-specific P1 replay case), plus the
`GateTests`/`PlannerTests` base classes were left untouched and still pass with
the new default arguments (`recurrence=_NO_RECURRENCE`, `payment_options=()`,
`events=()`) — confirming the M1 call sites needed no changes.

Independent check of the published `output.csv`: exact header, 250 rows in
`requests.csv` order, unique ids, 0 invariant violations, method distribution
now spans all five methods (`full_payment=53, installments=32,
not_recommended=147, partial_payment=7, wait=11`).

### Known limitations and degraded cases

1. **The DEV-split method mismatches present before M3 are unchanged by it, and
   one (`request_02`) is now newly visible as an installment case.** All four
   are traced to forecast-accuracy limits already flagged in the M1 write-up,
   not to M3's candidate generation or gating:
   - `request_02` (installments expected): the engine correctly finds and
     replays `payment_option_05`, but the replay genuinely breaches the
     minimum balance on `2025-09-10` against our forecast — the candidate
     logic and replay are doing their job; the disagreement is upstream, in
     how conservatively that month's essential spending is projected.
   - `request_23` (wait expected): capacity arrives `2025-07-17`, two days
     after the `2025-07-15` deadline — a small forecast timing error, same
     class as the "mean date error 14.2 days" already reported for M1.
   - `request_03` (wait expected) and `request_16` (full_payment expected):
     both already documented in the M1 section as M2 (image extraction)
     dependencies — a blank salary amount under-forecasts income
     (`request_03`), and an unknown rent amount degrades the row entirely
     (`request_16`).
   None of these were "fixed" by adjusting M3 logic to match gold, since doing
   so would mean tuning candidate generation against 4 known rows rather than
   the contract.
2. **Only `full_payment` carries spending-change candidates.** The plan and
   `problem_statement.md` describe spending changes as a way to make a request
   affordable; `wait`, `partial_payment`, and `installments` do not currently
   try spending-change variants if their unmodified form is unsafe. This
   matches every gold example seen (spending changes only co-occur with
   `full_payment`), but is a scope decision worth Codex confirming rather than
   an settled reading of the spec.
3. **`evaluation/usage_report.md` remains empty** — M4, unaffected by M3.

**Next milestone:** M2 — evidence extraction (messages/images), per the
participant's stated order (M3 before M2, now complete).

**Review requested from Codex:** yes. Worth attacking specifically: the
event-id citation choice for a projected occurrence (decision 1), the
day/30 installment-term formula (decision 4) against any installment requests
outside the 5 already checked, whether spending changes should also be tried
for `wait`/`partial_payment`/`installments` (limitation 2), and whether the
four DEV mismatches are correctly attributed to M1 forecast accuracy rather
than to a gap in M3's own logic.

---

## M2 — evidence extraction and provenance (complete, ready for Codex review)

**Milestone and status:** M2 complete. A bounded, auditable evidence layer
extracts structured, cited facts from messages/images and repairs unknown
`FinancialEvent.amount` values before the unmodified M1/M3 deterministic core
runs. No change to `planner.py`, `forecast.py`, `recurrence.py`, `state.py`,
or `validation.py`; `main.decide_one` is called identically in both modes.
`--mode assisted` runs end to end and, with no provider configured (the only
state exercised so far — no paid model run has been made per the standing
instruction not to start one), produces byte-identical output to
`--mode deterministic` on the full 250-request dataset.

**Problem solved and observable behavior:** two DEV-split rows
(`request_03`, `request_16`) and any future unresolved-debit row were
previously stuck degraded or under-forecasting because a `FinancialEvent`
had an unknown amount with no way to resolve it from its linked
message/image. `evidence.py` now retrieves the exact request/user-scoped,
time-bounded candidate set for a request; `model.py` calls a provider (real
or fake) under a bounded timeout/retry/budget/cache wrapper to propose facts
from that evidence; every proposed fact is independently validated for
citation reality, ownership, relevance, category exactness, and amount
parseability before being accepted; conflicting facts for the same event are
resolved by explicit precedence (amendment/cancellation > newer same-source
evidence > financially safer amount); and only accepted facts patch
`FinancialEvent.amount` (never overwriting a known amount, only repairing an
unknown one, or applying an explicit amendment/cancellation) before the
existing deterministic pipeline runs unchanged.

```
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 239 tests in ~8.5s          OK      (239 total; 54 new: 28 in test_evidence.py,
                                          15 in test_model.py, 11 in test_assist.py)

$ python code/main.py --mode deterministic --quiet
audit: 0 finding(s), 0 error(s)
wrote 250 rows to <repo>/output.csv
method distribution: full_payment=53, installments=32, not_recommended=147, partial_payment=7, wait=11
degraded rows: 2 | gate failures: 0 | unhandled errors: 0

$ python code/main.py --mode assisted --quiet --out <tmp>/assisted_full.csv
assisted mode provider status: unavailable        (no ANTHROPIC_API_KEY set)
wrote 250 rows to <tmp>/assisted_full.csv
$ diff output.csv <tmp>/assisted_full.csv
                                                    (no output: files identical)
```

**Files added:** `code/buy_or_wait/evidence.py` (candidate retrieval with the
documented availability cutoff, `ProposedFact`/`ExtractedFact`, citation
validation, exact-taxonomy category alignment, free-text amount parsing,
conflict resolution, `apply_facts_to_events`, `RowTrace`);
`code/buy_or_wait/model.py` (`Provider` protocol, `FakeProvider` for offline
tests, `AnthropicProvider` gated by `ANTHROPIC_API_KEY` + optional `anthropic`
import, `BoundedCaller` — `ThreadPoolExecutor`-based per-row timeout, bounded
retry/backoff against a monotonic deadline, never retrying `AuthError`,
per-row/full-run budgets via `UsageLedger` — and `ExtractionCache`, content-hash
keyed by source content + model + prompt/schema version + request context);
`code/buy_or_wait/assist.py` (`AssistConfig`, `extract_facts` — the fail-closed
orchestration entry point); `code/prompts/extraction_v1.md` (the versioned
extraction policy: untrusted-content rules, candidate-handle-only citation
instructions, exact-taxonomy instructions, "return unresolved rather than
guess"); `code/tests/test_evidence.py`, `code/tests/test_model.py`,
`code/tests/test_assist.py` (54 new tests).
**Files changed:** `code/main.py` (`--mode assisted` now builds a provider via
`_build_provider()` — catching `ProviderUnavailable` to `None` — constructs an
`AssistConfig`, calls `assist.extract_facts` per request, patches the context
via `evidence.apply_facts_to_events` + `dataclasses.replace`, then calls the
same `decide_one`; writes a `trace.jsonl`/`usage.json` pair per run under
`code/evaluation/runs/<UTC timestamp>/`); `code/buy_or_wait/__init__.py`
(module map extended; the "nothing imports a model provider" claim narrowed to
name `model.py` as the sole, guarded exception).

### Contract decisions, including alternatives rejected

1. **`evidence.py` never imports `model.py`.** `ProposedFact` (the shape a
   provider returns) lives in `evidence.py` so the pure validation logic —
   citation/category/amount/conflict rules — is importable and testable with
   zero provider dependency. `model.py` imports `evidence.ProposedFact`, and
   `assist.py` is the only module that imports both. Rejected putting
   `ProposedFact` in `model.py`: that would force every offline evidence test
   to import provider machinery it does not need.
2. **The message/image availability cutoff is a message's `sent_at` *date*,
   compared verbatim to `request_date`, with no timezone shift.** This was
   flagged as M2's open decision in the M0 write-up. A request carries only a
   date, so assuming a timezone to convert a UTC `sent_at` into "the user's
   day" would be an invented fact. An image carries no timestamp at all; its
   availability is instead derived from its `related_event_id`'s date when
   linked (a future-dated linked event makes the image unavailable for the
   same reason a future message would be), and available unconditionally
   otherwise. Rejected treating every image as always available regardless
   of link: that would let evidence for a not-yet-happened event leak into a
   decision as if already known.
3. **A future *scheduled* financial event is not "unavailable evidence."**
   Only messages/images have an availability cutoff; a structured
   `FinancialEvent` row is confirmed data already handled by
   `recurrence.py`/`forecast.py` regardless of its date, and remains citable.
   Conflating the two would incorrectly suppress citations for legitimate
   future-dated structured records.
4. **Category alignment is exact-match only, no alias table.**
   `docs/IMPLEMENTATION_STATUS.md`'s M0 decision 4 measured that every
   protect/reduce/stop token in the shipped data is already an exact
   `EVENT_CATEGORIES` member, and there is no `other` category to fall back
   to. A paraphrased or invented category (`"fast_food"`, `"food and drink"`)
   is rejected outright. Rejected building a fuzzy/alias mapping: the review
   checklist explicitly requires ambiguity to never authorize a spending
   change, and a hand-built alias table is exactly the kind of invented
   mapping the milestone forbids.
5. **`amount`, `amended_amount`, and `cancelled` are conflict-grouped
   together per target event, not kept in separate per-field groups.**
   Discovered while writing `ConflictResolutionTests`: without this, an
   amendment/cancellation and a plain `amount` fact for the same event would
   both remain `accepted` in the trace (even though `apply_facts_to_events`
   already applies them in the correct precedence order), losing the
   "preserve accepted and rejected provenance" guarantee the plan requires.
   Fixed in `evidence.resolve_conflicts` by grouping on a shared
   `"amount_or_status"` key for those three fields.
6. **`apply_facts_to_events` only repairs an `amount` fact onto an event
   whose amount is currently `None`; it never overwrites a known amount from
   a plain `amount` fact.** Only `amended_amount`/`cancelled` — which the
   conflict resolver has already ranked as an explicit correction — may
   override a known value. Rejected letting any accepted `amount` fact
   override a known value: a model restating an already-known amount
   (correctly or with a transcription slip) must never silently outrank the
   structured CSV row.
7. **`BoundedCaller` shares one monotonic deadline across all retry attempts
   for a row, and never retries `AuthError` or an exception it cannot
   classify as `TransientError`.** Retrying an unclassified exception would
   risk multiplying calls against an unknown failure mode (this was one of
   the August lessons in `docs/REPOSITORY_ANALYSIS.md`: "Retries do not
   implement explicit operational budgets ... immediately retries all
   exceptions"). `ThreadPoolExecutor` + `future.result(timeout=...)` was used
   for the per-call timeout instead of `signal.alarm`, since this
   environment is Windows (`win32`) and `SIGALRM` is not available there.
8. **The extraction cache key hashes source content + model id + prompt
   version + schema version + request context, not media identity alone.**
   August's cache keyed only by kind and media id
   (`docs/REPOSITORY_ANALYSIS.md`: "Cache identity is too weak for
   reproducible changed inputs"); the same image under a different prompt or
   schema version must miss, not silently reuse a stale extraction.
9. **`assist.extract_facts` catches every exception at its outer boundary and
   always returns a `RowTrace` plus (possibly empty) accepted facts; it never
   raises.** One row's extraction failure (timeout, budget exhaustion,
   provider error, or an unexpected bug) must degrade only that row to the
   deterministic result, matching `run_predictions`'s existing per-row
   `try/except` in `main.py` — assisted mode adds a second failure-isolation
   boundary rather than replacing the first.
10. **No separate "assisted" code path duplicates `decide_one`.** Assisted
    mode calls the identical `main.decide_one(context, rates)` used by
    deterministic mode, on a context whose `events` tuple has been patched
    via `dataclasses.replace`. This was the explicit instruction ("this is
    the core routing function; every request takes exactly this path") and
    was verified directly: `--mode assisted` with no provider configured
    produces byte-for-byte identical `output.csv` rows to `--mode
    deterministic` on the full 250-request dataset.

### Tests and exact commands with results

```
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 239 tests in 8.5s   OK

$ python code/main.py --mode deterministic --quiet
audit: 0 finding(s), 0 error(s)
wrote 250 rows to output.csv
degraded rows: 2 | gate failures: 0 | unhandled errors: 0

$ python code/main.py --mode assisted --quiet --out <tmp>.csv
assisted mode provider status: unavailable
wrote 250 rows to <tmp>.csv
degraded rows: 2 | gate failures: 0 | unhandled errors: 0
$ diff output.csv <tmp>.csv   ->   no differences
```

New test files and what each covers against the milestone's required-tests
list: `code/tests/test_evidence.py` (28 tests) — same-user/cross-user/blank-
request-id scoping, future message/image exclusion, future scheduled-event
non-exclusion, fabricated/unretrieved/wrong-user/irrelevant citation
rejection, invalid-citation invalidates the whole claim, exact/invented/
ambiguous category handling, multilingual/formatted numeric parsing,
amendment/cancellation conflict precedence, resolved-amount state repair,
plain-amount-never-overwrites-known-amount, prompt-injection text cannot
forge a category or bypass citation checks. `code/tests/test_model.py` (15
tests) — `AnthropicProvider` fails closed without a key, successful call
usage accounting, transient-error retry-then-succeed, `AuthError` never
retried, persistent-timeout bounded-attempt exhaustion, deadline-aware
backoff stopping retries early, per-row and full-run budget exhaustion,
unclassified-exception non-retry, cache miss/hit/key-sensitivity to source
content/model id/prompt version, and a stored record under a mismatched key
never being served. `code/tests/test_assist.py` (11 tests) — no-provider and
`provider=None` fail-closed paths, no-unresolved-amounts skip, successful
extraction repairing an event, fabricated-citation leaving an event
unresolved, prompt-injection rejection at the orchestration layer, cache-hit
avoiding a second provider call, provider-error and unhandled-exception
fallback to no facts (never a crash), and an end-to-end integration pair
proving a resolved fact clears `forecast.certifiable`/degradation through the
*unmodified* `state.py`/`recurrence.py`/`forecast.py`/`planner.py` pipeline
while an unresolved future debit keeps it degraded — the exact seam described
in the M1 write-up's limitation 2/3.

All new tests build synthetic fixtures via `code/tests/fixtures.py`
(`edit`/`append`), run entirely offline (`FakeProvider`, injectable
clock/sleeper — no `time.sleep`, no network, no credentials), and assert
dataset-directory byte-hash equality before/after to confirm no dataset
mutation.

### Evaluation run info

Not re-run for M2: the DEV/reporting split, label isolation, and
`code/evaluation/main.py` scoring are M1/M3 concerns unaffected by this
milestone, and no provider call (paid or otherwise) has been made against the
real dataset, per the explicit instruction not to start a paid model run.
`--mode assisted` was smoke-run against the full 250-request dataset with no
provider configured only, confirming the fail-closed path and the
`trace.jsonl`/`usage.json` sidecar writer; those run artifacts were deleted
after inspection rather than committed, since they contain no facts (every
row's `provider_status` was `"unavailable"`).

### Evidence and financial safety checks completed

- Retrieved candidate registry is request/user scoped (`data.py`'s existing
  structural scoping) with the added, documented time-availability cutoff.
- Every cited source is checked for reality (retrieved-set membership),
  ownership (same user), and relevance (actually references the target
  event) before a fact can be accepted.
- Blank-`request_id` user-level messages are retained and retrievable across
  that user's requests; verified directly in `RetrievalScopingTests`.
- A missing/unreadable image amount is never defaulted to zero: an
  unresolved unknown amount stays `None`, and `state.ExcludedRecord
  .is_unfunded_obligation` / `Forecast.certifiable` (unmodified) continue to
  block a positive `amount_safe_to_pay` for an unresolved future debit —
  proven by the `DeterministicCoreIntegrationTests` pair.
- Explicit amendment/cancellation facts win over a plain `amount` fact for
  the same event, with the superseded fact's rejection reason preserved in
  the trace rather than the fact being dropped.
- Categories are validated against the actual `schema.EVENT_CATEGORIES`
  vocabulary only; an invented or ambiguous category is rejected, never
  silently mapped.
- Rejecting a citation rejects the entire dependent fact (not a partially
  accepted amount), and `assist.extract_facts` never lets an unhandled
  exception propagate into `run_predictions`'s row loop.
- Prompt-injection text embedded in a message/image is treated as ordinary
  untrusted content by every check; `resolve_fact`'s citation/relevance/
  category checks reject an injected claim regardless of its wording, and
  `extraction_v1.md` documents this instruction to the model as a second,
  independent layer (not the layer actually relied on for safety).

### Known limitations and degraded cases

1. **No live provider call has been exercised against the real dataset.**
   `AnthropicProvider` is implemented and unit-constructible (fails closed
   without a key) but `messages.create` itself has not been called, per the
   standing instruction not to start a paid model run. `request_03`'s blank
   salary amount and `request_16`'s unknown rent amount (flagged as M2's job
   in the M1 write-up) are therefore still open in the current `output.csv`
   — the mechanism to resolve them is implemented and tested via
   `FakeProvider`, but resolving those two specific rows requires an actual
   authorized model run, which this pass does not perform or estimate the
   cost of.
2. **`_pick_winner`'s financially-safer tie-break assumes a single value
   type within a group.** When an explicit group mixes an `amended_amount`
   (Decimal) and a `cancelled` (bool) fact for the same event and neither is
   uniquely newest, the direction-based tie-break (`isinstance(..., Decimal)`)
   does not apply to the boolean case and falls through to `group[0]` (first
   by no defined order). Not exercised by real or synthetic data seen so far
   (no fixture produces two *different* explicit fact types for one event in
   the same call); flagged rather than fixed speculatively, since a
   synthetic tie-break rule for an unobserved case would be exactly the kind
   of unsupported invented behavior the milestone prohibits.
3. **`evaluation/usage_report.md` remains empty.** Unaffected by M2, since no
   provider call has been made; M4 is responsible for populating it from a
   real `usage.json` once an authorized run happens.
4. **`code/evaluation/runs/<timestamp>/` and `code/evaluation/extraction_cache.json`**
   are created by `--mode assisted`; both were added to `.gitignore` in this
   pass so an assisted smoke run does not leave artifacts to accidentally commit.

**Next milestone:** M4 packaging (per the explicit instruction, not started
this pass) — code archive layout, `evaluation/usage_report.md`, and README
run instructions — plus, at the participant's discretion, an authorized
paid-model run of `--mode assisted` against the full dataset to attempt
resolving `request_03`/`request_16` and produce real usage numbers.

**Review requested from Codex:** yes. Worth attacking specifically: the
availability-cutoff decisions (2, 3) against any real message/image whose
implications were not obvious from the synthetic fixtures, the conflict-
grouping fix (decision 5) for any grouping case not covered by
`ConflictResolutionTests`, whether `BoundedCaller`'s deadline/backoff
behavior (decision 7) matches the plan's "60 seconds ... three provider
attempts total" language precisely enough, the cache-key composition
(decision 8), and limitation 2's unresolved tie-break gap.

---

## M0 cleanup — response to `docs/reviews/M0_CODE_REVIEW.md` (fix-first, 8 findings)

**Status:** R-M0-01 … R-M0-08 all fixed, all reproduced first, all covered by
negative regression tests. Verdict accepted in full; no finding disputed.

**Verification:**

```
$ python -m unittest discover -s code/tests -t code -p "test_*.py"     # 3.10.11
Ran 106 tests in 6.854s
OK
$ py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py" # 3.12.5
Ran 106 tests in 7.352s
OK
$ python code/main.py
audit: 0 finding(s), 0 error(s)          (exit 0, 16 media hashes now listed)
```

29 tests added (77 → 106), of which 26 are the new negative fixtures in
`code/tests/test_input_boundary.py`.

| Finding | Fix | File | Regression test |
|---|---|---|---|
| R-M0-01 surplus/truncated CSV rows | `read_rows` sets `restkey`/`restval` sentinels and rejects any row whose width differs, naming file, row and surplus cells | `data.py` `read_rows` | `RowWidthTests` ×4 |
| R-M0-02 image path traversal | `parse_safe_id` rejects non-component ids at load; `safe_media_path` re-validates the id *and* proves `resolved.parent == media_dir`; `DataSet.media_path()` is the single resolver M2 must use | `data.py` | `MediaPathTests` ×3 (incl. `..`, `a/b`, `/etc/passwd`, `C:file`) |
| R-M0-03 cross-user request refs | new audit code **A13**: a message/image whose `request_id` is owned by another user is an error. `request_context` re-checks ownership when admitting request-linked evidence | `audit.py`, `data.py` | `CrossUserReferenceTests` ×4 |
| R-M0-04 load-time rounding | `parse_amount` replaced by `parse_decimal`, which never rounds. `quantize` is now explicitly the *output* policy. New audit **A14** warns if supplied precision exceeds the 2-dp rendering convention | `money.py`, `data.py`, `audit.py` | `RatePrecisionTests` ×5 |
| R-M0-05 media not in manifest | `DataSet.media_manifest` hashes all 16 PNGs, kept distinct from the CSV manifest; printed by the audit CLI | `data.py`, `main.py` | `MediaManifestTests` ×3 |
| R-M0-06 lenient dates | explicit `^\d{4}-\d{2}-\d{2}$` check before `date.fromisoformat` | `data.py` | `StrictDateTests` ×3 |
| R-M0-07 forged request object | `requests_by_id` index; `request_context` requires an exact match with the loaded record; `context_for(request_id)` added as the safe entry point | `data.py` | `ForgedRequestTests` ×4 |
| R-M0-08 suite did not test the boundary | `code/tests/test_input_boundary.py` added | — | the 26 above |

**One correction to the finding as filed (R-M0-06).** It is worse than
"`fromisoformat` is lenient". That function is **strict on Python 3.10 and
lenient on 3.11+**:

```
python 3.10.11 : 20240303 -> rejected      2024-W09-7 -> rejected
py -3.12 3.12.5: 20240303 -> 2024-03-03    2024-W09-7 -> 2024-03-03
```

So the loader's date strictness silently depended on the interpreter, and the
reviewer (on 3.12) and I (on 3.10) were running materially different validation
of the same code. That is a portability defect, not only a strictness one, which
is why the whole suite is now run on both interpreters and that is recorded as
the standing verification command.

**A defect in my own test fixture, surfaced by the new A13 rule.** The "clean"
synthetic dataset had `message_02` (user_01) referencing `sample_01`, which
belongs to user_02 — a cross-user reference sitting inside the fixture that was
supposed to represent a valid dataset. The scoping test it supported was
therefore passing for the wrong reason. Fixed by adding `request_02`, a second
request genuinely owned by user_01, so same-user/different-request scoping is
tested without crossing users. Worth noting because it is exactly the class of
error the review exists to catch: the fixture encoded my assumption rather than
the contract.

**Residual risk:** `A14` is a warning, not an error. If the shipped dataset ever
carries more than two decimals, values are preserved exactly but the output
rendering convention measured from the gold samples would need revisiting before
publication. It does not fire on the current data.

---

## M2 review response — `docs/reviews/M2_CODE_REVIEW.md` (fix-first, 3 findings)

**Status:** R-M2-01 … R-M2-03 all fixed, all covered by targeted regression
tests. Verdict accepted in full; no finding disputed.

**Verification:**

```
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 249 tests in 8.594s
OK
$ python code/main.py --mode deterministic --dataset dataset --out /tmp/det_output.csv
$ python code/main.py --mode assisted --dataset dataset --out /tmp/assisted_output.csv
assisted mode provider status: unavailable ...
$ diff <(sort /tmp/det_output.csv) <(sort /tmp/assisted_output.csv)
(no output — rows are byte-identical; assisted mode still fails closed
without credentials)
```

10 tests added (239 → 249): 3 strict-date fixtures, 1 hanging-provider
timeout test, 4 `citation_note` unit tests, 2 assisted-mode CLI integration
tests that read the published `output.csv`.

| Finding | Fix | File | Regression test |
|---|---|---|---|
| R-M2-01 evidence dates bypass strict input contract | `evidence.resolve_fact` no longer calls `date.fromisoformat` directly; it now calls a new `data.try_parse_iso_date`, which reuses M0's `^\d{4}-\d{2}-\d{2}$` shape check but returns `None` on failure instead of raising, so an untrusted evidence date can be rejected without crashing the row | `data.py`, `evidence.py` | `test_evidence.py::StrictDateTests` ×3 (compact, ISO-week, well-formed) |
| R-M2-02 per-row timeout is not a hard wall-clock bound | `BoundedCaller.call` no longer uses `ThreadPoolExecutor`: a hung worker could still block `__exit__`'s `shutdown(wait=True)`, and even `wait=False` would not stop `concurrent.futures.thread`'s `atexit` join hook at interpreter shutdown. Replaced with a daemon `threading.Thread` + `queue.Queue(maxsize=1)` handoff (`_run_with_hard_timeout`): a hung provider call is abandoned on its own daemon thread, which cannot block the caller past `remaining` seconds or block process/interpreter exit | `model.py` | `test_model.py::BoundedCallerTests::test_hanging_provider_never_returns_but_call_still_bounds_wall_clock_time` (real wall-clock, provider that never returns) |
| R-M2-03 citations never reach `decision_explanation` | Added `evidence.citation_note(trace)`, which re-derives the cited ids from `RowTrace.accepted` filtered against `RowTrace.retrieved` (never trusted from `resolve_fact` alone) and returns `None` — not an empty citation — when nothing was accepted. `main.run_predictions` appends the note to `row["decision_explanation"]` only in assisted mode and only when `accepted_facts` is non-empty | `evidence.py`, `main.py` | `test_evidence.py::CitationNoteTests` ×4; `test_assist.py::CitationReachesOutputTests` ×2 (end-to-end through `main.run_predictions` with a `FakeProvider`, reading the published CSV) |

**No correction to any finding as filed.** All three were reproduced exactly
as described before being fixed.

**Design note on R-M2-02.** The review's suggested fix ("non-waiting
shutdown") would not have been sufficient on its own: `ThreadPoolExecutor`
registers a global `atexit` hook (`concurrent.futures.thread._python_exit`)
that joins all pending worker threads regardless of how an individual
executor's `shutdown()` was called, so a hung provider could still hang the
whole process (or the test suite) at exit. Dropping `ThreadPoolExecutor`
entirely for this call site, in favor of a plain daemon thread, removes that
failure mode rather than papering over it.

**Residual scope note on R-M2-03.** The degraded-row explanation branch in
`output.render_explanation` (used when no evidence resolved an unfunded
obligation) already states insufficiency in general terms
("Some obligations could not be quantified from the available records...")
without naming any id; `citation_note` only ever appends, and only when
`accepted_facts` is non-empty, so it cannot conflict with or duplicate that
existing degraded-row language.

---

## Review response — `docs/AGENT_CONFIG_REVIEW.md` (fix-first, 10 findings)

All ten accepted. Full disposition with evidence:
**`docs/FINDING_TO_CHANGE.md`**.

Summary of what changed:
- One controlling plan (R08). `docs/IMPLEMENTATION_PLAN.md` is authoritative;
  `docs/PLAN.md` is a superseded stub holding only measurements and a
  rejected-rule register. All five agent prompts name the same plan; orchestration
  and shared files are owned by the main session; every agent may write `log.txt`.
- Unresolved **debits** stay in state and block unsupported approval (R01).
- Exact settlement-date FX only, no fallback (R02) — also corrected my own claim
  that rate dates are only the 15th; they are `{1, 15}`.
- Spending actions and claim provenance separated into two axes (R03).
- Effect vocabulary must express cessation and bounded intervals (R04), verified
  against `message_09`.
- C13/R1/R2 withdrawn; replaced by independent plan replay and
  render-from-facts (R05).
- Split moved to M0 and implemented here (R06).
- Content-hash cache keying required (R07).
- `Decimal` throughout (R09) — implemented in `money.py`.
- Baseline and submission-ready separated; `usage_report.md` required (R10).

One qualification returned in the other direction: the August evidence F1 of
0.480 was itself computed on matched held-out pairs, so the low score is a real
measurement of that run even though my proposed *cause* for it was not
established. Both statements travel together; neither is a September result.

---

## M4 (in progress) — credibility and package

**Status:** the no-cost parts of M4 are complete: real `--compare-baseline`
scoring, assisted-mode scoring in the evaluation harness, a code-level README,
and a packaging script. **Blocked** on the participant: no `ANTHROPIC_API_KEY`
is set in this environment, so the authorized paid-model run against the full
250-request dataset — the one thing `evaluation/usage_report.md` and a
submission-ready `output.csv` from assisted mode depend on — has not
happened. Per the standing instruction, no paid run is started without
explicit authorization.

**What changed:**

1. `code/evaluation/main.py` no longer has an unimplemented `--mode assisted`
   (previously exited 2) or a `--compare-baseline` flag that was accepted but
   never used. Both now work: `score()` takes a `mode` and calls
   `main.predict_one` (new, factored out of `main.run_predictions`'s per-row
   loop) so the evaluation harness scores the *identical* row-production path
   a real submission publishes from, never a second copy of it.
   `--compare-baseline` with `--mode assisted` additionally scores the
   deterministic-only baseline on the same request set immediately after, so
   the evidence layer's effect is visible request-for-request.
2. `main.predict_one(data, request_id, mode=..., assist_config=...)` is the
   one new production function: it returns the row, the decision, gate
   failures, the evidence trace (assisted only), and whether the row crashed.
   `run_predictions` now calls it per request instead of inlining the same
   logic, so the CLI and the evaluator cannot silently diverge.
3. `code/README.md` added: setup (optional `anthropic` install, `ANTHROPIC_API_KEY`
   from the environment only), run commands for all three modes, the test
   command, and the evaluation commands including `--compare-baseline`.
4. `code/package.py` added: builds `code.zip` from an explicit allowlist
   (`main.py`, `buy_or_wait/`, `prompts/`, `evaluation/`, `tests/`,
   `README.md`), rooted so the archive contains `evaluation/usage_report.md`
   directly rather than nested under `code/`, per plan §9. Excludes
   `__pycache__`, `code/evaluation/runs/`, and `extraction_cache.json`. Warns
   (does not fail) if `usage_report.md` is still empty, and fails if the
   archive doesn't contain it at the expected root path. Verified: 41 files
   packaged, correct root-relative paths, warning fires correctly against the
   still-empty placeholder.
5. `code.zip` added to `.gitignore` — it is a generated submission artifact.

**Tests:** `code/tests/test_eval_main.py` added (3 tests, 249 -> 252):
scoring a fixture's one gold sample via `score()` matches `predict_one`'s
published row exactly; assisted mode with no provider configured produces
byte-identical scoring output to deterministic mode; a CLI-level test against
the real dataset's frozen split confirms `--mode assisted --compare-baseline`
prints both an `ASSISTED` and a `BASELINE` section.

```
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 252 tests in ~11.7s          OK

$ python code/evaluation/main.py --split report --mode assisted --compare-baseline
assisted mode provider status: unavailable (no API key/package)
------------------ ASSISTED ------------------ ... (scores identical to baseline)
===== BASELINE (deterministic, no model calls) FOR COMPARISON =====
------------------ BASELINE ------------------ ... (identical numbers, confirming fail-closed parity)

$ python code/package.py
WARNING: evaluation/usage_report.md is empty. ...
wrote <repo>/code.zip
41 files: ...
```

**What is still blocked on the participant, not on code:**

1. **`evaluation/usage_report.md` is still empty**, correctly — per the plan,
   it must reflect the final full-dataset run and must never be pre-filled
   with invented numbers. Populating it requires an authorized paid run of
   `--mode assisted` against the full 250-request dataset with a real
   `ANTHROPIC_API_KEY` set, which has not been started.
2. **`output.csv` at the repo root is still the deterministic/M3 baseline.**
   Producing a submission-ready assisted-mode `output.csv` (to attempt
   resolving `request_03`/`request_16`, per the M2 write-up) requires the
   same authorized run.
3. **`code.zip` has not been produced as a submission artifact** — `package.py`
   works and was smoke-tested, but building the real archive should happen
   after the usage report is populated, not before, so it isn't rebuilt twice.

**Next step:** participant decision required — either (a) set
`ANTHROPIC_API_KEY` and authorize a bounded-cost run of
`python code/main.py --mode assisted --out output.csv` against the full
dataset, after which `usage_report.md` is generated from the real
`code/evaluation/runs/<timestamp>/usage.json` and `code.zip` is built, or
(b) submit on the deterministic/M3 baseline `output.csv` with
`usage_report.md` documenting zero model calls, which is honest but forgoes
the two known evidence-dependent rows.

**Review requested from Codex:** yes, on the diff described above
(`predict_one` factoring, `score()`/`--compare-baseline` semantics,
`package.py`'s allowlist and root-path check) — independent of the pending
paid-run decision.

## M4 review response — R-M4-01 (full-run budget wiring)

Source: `docs/reviews/M4_CODE_REVIEW.md`. Blocking finding: `_build_assist_config()`
constructed `UsageLedger()` with both full-run budgets `None`, so a 250-row
paid run had no cost ceiling; per-row limits existed but `UsageLedger.check_budget()`
was only ever called *after* `ledger.record(...)` inside `BoundedCaller.call`,
so it could never prevent the *next* row's call once budget was already
exceeded — it only raised retroactively, after that row had already paid for
a call.

**Fix (disposition: fixed, not disputed):**

1. `code/buy_or_wait/model.py` — `BoundedCaller.call()` now calls
   `ledger.check_budget()` once at the top, before any attempt is made. Once
   the ledger is already over budget, every subsequent row raises
   `BudgetExceeded` before touching the provider. The one call that first
   crosses a threshold still executes, because usage (tokens) and the
   post-call count are unknowable before that call returns — this is
   inherent to token budgets and applied uniformly to call-count budgets too,
   which is simpler than special-casing them separately.
2. `code/main.py` — added `DEFAULT_FULL_RUN_CALL_BUDGET = 60`,
   `DEFAULT_FULL_RUN_TOKEN_BUDGET = 300_000`, env vars
   `BUY_OR_WAIT_MAX_CALLS` / `BUY_OR_WAIT_MAX_TOKENS`, and CLI flags
   `--max-calls` / `--max-tokens`. `_resolve_budget()` resolves CLI > env >
   default, so assisted mode can never run with an unbounded ledger.
   `_build_assist_config()` now takes `max_calls`/`max_tokens` and builds
   `UsageLedger(full_run_call_budget=..., full_run_token_budget=...)`.
   `run_predictions()` prints `assisted mode full-run budget: N calls, M
   tokens` alongside the provider-status line, and `usage.json` now records
   `full_run_call_budget`/`full_run_token_budget`.
3. `code/evaluation/main.py` — mirrors the same budget line in its
   assisted-mode setup so `--compare-baseline` runs show the same ceiling.
4. `code/tests/test_model.py` — added
   `test_call_budget_exhaustion_prevents_any_further_provider_calls` and
   `test_token_budget_exhaustion_prevents_any_further_provider_calls`, both
   asserting `provider.calls` stops growing once the ledger is over budget
   (the crossing call still lands; every call after it is blocked pre-call).
5. `code/tests/test_assist.py` — the `_build_assist_config` monkeypatch
   lambda needed `**kwargs` to accept the new `max_calls`/`max_tokens`
   arguments.

**Model ID:** `claude-sonnet-5` is confirmed valid — this implementation is
itself running on that model per the harness's own system information, so no
separate account check against the Anthropic API is needed to answer that
question.

**Verification:**

```text
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 254 tests in 11.5s
OK
```

**Still blocked on participant decision, unchanged from above:** no
`ANTHROPIC_API_KEY` is set in this environment. Wiring and tests are
complete and offline-verified; a real (even small, budget-capped) smoke
batch against the Anthropic API requires the participant to supply a key and
explicitly authorize the spend before any paid call is made.

**Review requested from Codex:** yes, on the `check_budget()` placement,
the CLI/env/default precedence, and the two new regression tests.

## M4 review response — R-M4-02 (budget boundary: `>=` not `>`)

Source: `docs/reviews/M4_BUDGET_REVIEW.md`. Fix-first finding: `UsageLedger.check_budget()`
rejected only when `total > budget`, so usage landing exactly on the configured
ceiling let one further provider call through before the *next* call's
pre-check caught it — an off-by-one overshoot of a "hard" ceiling.

**Fix (disposition: fixed, not disputed):**

1. `code/buy_or_wait/model.py` — `check_budget()` now rejects at
   `total.calls >= full_run_call_budget` and
   `total_tokens >= full_run_token_budget`, applied uniformly to both the
   pre-call guard and the post-call guard in `BoundedCaller.call()` (both call
   the same `check_budget()`). Consequence: the call whose own usage lands
   exactly on the ceiling is still attempted (usage is unknowable
   beforehand) but its result is discarded via the post-call check, and every
   row after that is blocked pre-call. A budget of `N` therefore guarantees
   at most `N-1` calls' worth of usage is ever returned to a caller, never
   `N` or more.
2. `code/tests/test_model.py` — updated
   `test_full_run_call_budget_exceeded_raises_on_next_call` (budget=1: the
   pre-call check only sees usage *before* this call, so the first call still
   executes, but the post-call check then sees `1 >= 1` and discards its
   result) and rewrote both R-M4-01
   regression tests (`test_call_budget_exhaustion_prevents_any_further_provider_calls`,
   `test_token_budget_exhaustion_prevents_any_further_provider_calls`) to
   assert the corrected boundary: the call landing exactly on budget still
   reaches the provider but raises `BudgetExceeded` instead of returning a
   result, and every call after that is blocked before reaching the provider
   at all.

**Verification:**

```text
$ python -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 254 tests in ~12s
OK
```

**Separately found and fixed while verifying this response (not part of
either Codex review, self-detected):**

1. **Test isolation gap in `code/tests/test_eval_main.py::CompareBaselineCliTests`.**
   This test asserts the no-provider fallback path but never forced the
   no-key condition itself -- it only worked because the ambient environment
   happened to lack `ANTHROPIC_API_KEY`. After wiring optional `.env`
   auto-loading into `main.py`/`evaluation/main.py` (see below) and the
   participant adding a real key to their local `.env`, this test started
   constructing a real, configured `AnthropicProvider` and would have made
   real Anthropic calls against the dev split on every test run. Fixed by
   adding `setUp`/`addCleanup` to the test that explicitly pops
   `ANTHROPIC_API_KEY` from the environment before calling `eval_main.main()`
   and restores it afterward, so the assertion no longer depends on what the
   developer's `.env` happens to contain. Audited every other assisted-mode
   test in the suite (`test_assist.py`, remaining `test_eval_main.py` tests)
   and confirmed they either pass `assist_config` explicitly or monkeypatch
   `_build_assist_config`, so none of them are exposed to this gap.
2. **`.env` support added.** `code/main.py` and `code/evaluation/main.py` now
   call `load_dotenv(REPO_ROOT / ".env")` at import time if `python-dotenv`
   is installed (a no-op, silently skipped otherwise); `.env.example` and a
   local (gitignored) `.env` were added per the participant's request so
   `ANTHROPIC_API_KEY` can be set without exporting it in the shell.
   `code/README.md` documents this.
3. **Root `output.csv` was found truncated to a single row** (`request_26`
   only) from an earlier interrupted real-dataset run recorded at
   `code/evaluation/runs/20260913T033628Z/` -- that run's trace shows
   `"provider_status":"unavailable"`, confirming no model call was made and
   no cost was incurred; the file was simply left mid-write. Restored by
   rerunning `python code/main.py --mode deterministic --out output.csv`
   (no network access possible in this mode regardless of credentials),
   which reproduced the full, previously-committed 250-row baseline exactly
   (`git diff --stat output.csv` empty after regeneration). Stray
   `code/evaluation/runs/<timestamp>/` directories created by this session's
   test and debug runs were deleted (gitignored, never committed).

**Still blocked on participant decision, unchanged:** a real `ANTHROPIC_API_KEY`
is now present in the participant's local `.env`, but no assisted-mode run
against the real dataset has been made with it, and none will be made without
explicit authorization for the specific run (smoke batch or full dataset).

**Review requested from Codex:** yes, on the `>=` boundary fix and the
corrected regression tests; the test-isolation and `.env`/output.csv items
are disclosed for awareness rather than requested as a formal review target.

## Accuracy Phase A — evidence authorization holes (`docs/reviews/ACCURACY_IMPROVEMENT_PLAN.md`)

A real, authorized 250-row assisted run completed earlier
(`code/evaluation/usage_report.md`, 11 calls, ~40K tokens, ~$0.09). Codex's
follow-up investigation (`docs/reviews/ACCURACY_IMPROVEMENT_PLAN.md`)
reproduced eight offline regression probes
(`docs/reviews/accuracy_regression_probes.py`) exposing evidence-authorization
and recurrence gaps, and proposed a phased fix order: A (evidence safety) →
B (broaden evidence investigation) → C (recurrence correctness). This entry
covers Phase A only, per the plan's explicit sequencing
("Implement Phase A first and hand back the focused diff and tests for Codex
review; then proceed with authorized B/C work"). No paid calls were made.
No frozen submission artifact (root `output.csv`, `evaluation/usage_report.md`,
`evaluation/final/`) was touched.

**Scope:** `code/buy_or_wait/evidence.py` only (plus threading a new optional
parameter through its one caller in `assist.py`). Probes 1 (Phase B) and 6-8
(Phase C) are out of scope and still fail, as expected.

**Fixes, each mapped to its probe:**

1. **Probe 2 — an event can no longer cite itself as proof of its own
   cancellation/amendment.** `resolve_fact()`'s event-relevance check
   previously accepted `source_id == event.event_id` as sufficient support
   for *any* field, including `cancelled`/`amended_amount`. It now requires
   at least one cited source *other than* the event's own id for those two
   fields specifically -- a message or image that actually documents the
   change. Plain `amount` (filling a currently-unknown value) is unaffected,
   since existing tests (`StateRepairTests.test_plain_amount_never_overwrites_a_known_amount`)
   rely on citing the event itself for that case, and the plan's concern is
   specifically about a structured row "proving" its own cancellation, not
   about repairing a blank field.
2. **Probe 3 — a wrong-currency amount is rejected unless an exact, dated
   rate authorizes a real conversion.** `resolve_fact()` now compares
   `proposed.currency` against the target event's currency when both a
   currency and a target event are present. On a mismatch it calls the
   existing `fx.convert()` (never a new conversion path) using the event's
   `settlement_date` and a `rates_by_key` table now threaded in as an
   optional keyword argument (default `{}`, so every existing caller/test
   that doesn't pass it keeps its prior all-reject behavior). `assist.py`'s
   one call site now passes `dataset.rates_by_key`, the same table
   `fx.py`/`forecast.py` already use, so a genuinely supplied directed rate
   is honoured instead of the fact being dropped outright, while an
   unavailable rate (`fx.RateUnavailable`) still rejects the fact rather
   than guessing. Decision: chose the full FX-aware repair over an
   always-reject shortcut because the plan explicitly asked for "an
   explicit, valid conversion ... using the contract's exact directed
   settlement-date rate," and the machinery to do this correctly already
   existed and needed no new logic duplicated in `evidence.py`.
3. **Probe 4 — a `user_level` fact can no longer carry an event target.**
   `resolve_fact()` previously validated `target_scope` values but never
   checked that a `user_level` fact's `target_event_id` was `None`, so
   `apply_facts_to_events()` (keyed only on `target_event_id`, regardless of
   scope) could still patch an event from a fact nominally scoped
   `user_level`. Now rejected explicitly at the scope-check site.
4. **Probe 5 — ambiguous multi-number text is rejected, not concatenated.**
   `parse_fact_amount()` now scans the raw text for distinct contiguous
   numeric runs (`\d[\d.,]*`) before its existing comma/dot-convention
   normalization; more than one distinct run (e.g. `"2 invoices of INR
   500"` -> `"2"` and `"500"`) rejects the value instead of silently
   stripping the separating text and concatenating digits into `2500`. A
   single grouped/decimalled number (`"1,234.56"`, `"1.234,56"`) is still one
   run and parses exactly as before; all four existing `NumericParsingTests`
   pass unchanged.
5. **Trace completeness (plan: "Preserve source spans in traces"):**
   `RowTrace.to_json()`'s `fact_json()` helper now serializes `source_span`
   for both accepted and rejected facts; it was already stored on
   `ExtractedFact` but silently dropped at serialization.

**Tests:** added `EvidenceAuthorizationTests` (10 cases) to
`code/tests/test_evidence.py`, covering each fix's rejection path plus a
matching "still works" case (message-backed cancellation is still accepted;
matching-currency and rate-backed cross-currency amounts are still accepted;
a genuine user-level fact with no event target is still accepted) and one
end-to-end check that a rejected self-authorized cancellation never reaches
`apply_facts_to_events()`. This migrates the intent of probes 2-5 into the
production suite per the plan's instruction ("Move the behavioral
regressions into production tests while fixing them"), rather than leaving
`docs/reviews/accuracy_regression_probes.py` as the only coverage.

**Verification:**

```text
$ py -3.12 -B docs/reviews/accuracy_regression_probes.py
Ran 8 tests: probes 2-5 pass; probe 1 (Phase B) and 6-8 (Phase C) still fail as expected.

$ py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 264 tests in ~20s
OK

$ py -3.10 -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 264 tests in ~15s
OK
```

**Not done in this pass (explicitly deferred to Phase B/C per the plan):**
the blank-amount-only extraction gate in `assist.py` (probe 1), independent
salary-stream separation, calendar-monthly day-of-month drift, and
one-off-arrears-vs-recurring-income handling (probes 6-8). No live/paid
provider run was made or is needed for Phase A, since all four fixes are
pure validation-logic changes exercised by fixtures and a fake provider.

**Review requested from Codex:** yes -- this is the Phase A handback the
plan calls for. Please review before Phase B (`assist.py` extraction-gate
broadening) or Phase C (`recurrence.py`) work begins.

## Phase A corrective pass -- three findings from `docs/reviews/ADE_REVIEW_DISPOSITION.md`

Codex's independent review of the Phase A handback (above) confirmed the
scope was right but found three defects the original pass missed. All three
are fixed in `code/buy_or_wait/evidence.py`; no other module changed.

1. **Unsupported cancellations still passed (linked evidence is not
   proof).** The self-citation guard only checked that a cited source *other
   than the event itself* existed and was related by `related_event_id`; it
   never checked that source actually said anything about a cancellation or
   amendment. A message merely linked to the target event (e.g. "Your
   February payslip is attached") could authorize `cancelled=true` for that
   event. Fixed by `_has_supporting_language()`: for `cancelled`/
   `amended_amount`, at least one cited source must contain field-appropriate
   language (`_CANCELLATION_KEYWORDS` / `_AMENDMENT_KEYWORDS`). Ground truth
   wins over the model's own claim -- if any cited source is a message, its
   real `message_text` on file (never the model-supplied `source_span`)
   decides the outcome, closing the fabricated-quote variant of the same
   hole in the same fix. `source_span` is only consulted when no cited
   source has independently verifiable text (e.g. image-only citations).
   The existing `test_message_backed_cancellation_is_still_authorized`
   fixture was itself misleading (it asserted "accepted" using unrelated
   payslip text merely because of `related_event_id` linkage); corrected to
   use a mutated dataset whose message text actually states the
   cancellation, and two new regression tests
   (`test_linked_message_silent_on_cancellation_does_not_authorize_it`,
   `test_linked_message_silent_on_amendment_does_not_authorize_it`) pin the
   fixed behavior, plus `test_source_span_alone_cannot_forge_supporting_language`
   for the fabrication variant. `ConflictResolutionTests` also relied on the
   same unrelated payslip text to construct amendment/cancellation facts;
   both now build a small mutated dataset with genuinely supporting text.
2. **Ambiguous repeated amounts were concatenated into invented money.**
   `parse_fact_amount("500 plus 500")` returned `Decimal("500500")` because
   the ambiguity check only rejected *distinct* numeric runs
   (`{"500"} `-> length 1 -> allowed), not repeated occurrences. Fixed by
   rejecting whenever more than one numeric run is present at all,
   regardless of whether the values are equal
   (`if len(runs) > 1: return None`), which is what the original inline
   comment already described but the `distinct_runs` set implementation
   did not enforce. Added
   `test_repeated_equal_numbers_are_not_concatenated_into_money`; the
   existing distinct-number and single-number tests are unaffected since a
   single grouped/decimalled number is still exactly one run.
3. **Converted facts carried the wrong currency, with no conversion
   provenance.** After converting a cross-currency amount (e.g. 100 EUR ->
   2000 ZAR), `resolve_fact()` stored the converted (ZAR) value but still
   returned `proposed.currency` ("EUR") on the `ExtractedFact`, so the trace
   showed a ZAR-magnitude figure mislabeled as EUR with no record that a
   conversion happened. Fixed by tracking the fact's actual currency
   separately (`fact_currency`, defaulted to `proposed.currency` and
   reassigned to `converted.to_currency` only when a conversion actually
   ran) and adding a new `ExtractedFact.conversion_note` field (populated
   from `fx.Converted.cite()`, e.g. `"100 EUR -> EUR->ZAR @ 20 on
   2024-02-15"`), serialized in `RowTrace.to_json()`. Extended
   `test_wrong_currency_amount_converts_with_an_exact_dated_rate` to assert
   `result.currency == "ZAR"` and that `conversion_note` names both
   currencies.

**Tests:** `code/tests/test_evidence.py` grew from 45 to 49 cases (4 new:
2 authorization-language regressions, 1 fabrication-resistance case, 1
repeated-number regression); 2 existing `EvidenceAuthorizationTests` /
`ConflictResolutionTests` cases were corrected rather than added to, since
they encoded the misleading fixture Codex flagged.

**Verification:**

```text
$ py -3.12 -B -m unittest discover -s code/tests -t code -p "test_evidence.py"
Ran 49 tests
OK

$ py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"
Ran 268 tests
OK

$ py -3.12 -B code/main.py --mode audit --quiet
audit: 0 finding(s), 0 error(s)
```

**Not done in this pass (still Phase B/C or later per the review's
sequencing):** conflict-resolution order-dependence, independent replay,
spending-validation event-ownership gate, horizon gate, corrupt-cache
handling, run-ID collisions, retry/usage accounting, rounding, and the
broader material-evidence extraction gate. These are unchanged from the
prior handback's "not done" list plus the review's newer findings; none of
them are evidence-authorization defects the three items above needed to
also touch.

**Review requested from Codex:** yes -- this is the corrective handback for
the three findings in `docs/reviews/ADE_REVIEW_DISPOSITION.md`. The
remaining sequence (conflict resolution, independent replay, spending/
horizon validation, then Phase B/C, then rounding/cache/retry/run-ID) is
still open and not attempted here.

## Phase A second corrective pass (R-A-04, R-A-05) -- 2026-09-13

Codex's `docs/reviews/PHASE_A_CORRECTIVE_REVIEW.md` found the numeric and
currency fixes above sound, but the cancellation/amendment authorization
boundary itself was still a routing heuristic, not proof of an actual
financial change:

1. **R-A-04 -- negated, conditional, and pending language authorized
   cancellation.** `_has_supporting_language()` matched a keyword (e.g.
   "cancel", "refund") anywhere in the cited text with no check on
   polarity, certainty, or timing, so "This payment has **not** been
   cancelled", "**If** you cancel next month...", and "Your refund request
   is **pending**..." all authorized removing a real debit. Fixed by
   replacing the whole-text substring match with sentence-level
   affirmative-effect checking: `code/buy_or_wait/evidence.py`'s
   `_affirmative_sentence()` splits cited ground-truth text into sentences,
   requires a keyword-bearing sentence, and rejects that sentence if it
   also contains a negation marker (`not`, `n't`, `never`, `no longer`,
   `without`), a conditional marker (`if`, `unless`, `should`, `would`,
   `were to`, `provided that`), or an uncertainty/pending marker (`pending`,
   `will be`, `may`, `might`, `requested`, `next month`/`next week`,
   `upcoming`, `planned`, `expected to`, `about to`). `_find_supporting_sentence()`
   preserves the existing ground-truth-wins rule (a real message's text
   decides over the model's own `source_span`; `source_span` is only
   consulted when no cited source has retrievable ground truth, e.g.
   image-only evidence).
2. **R-A-05 -- amendment keyword did not bind the proposed amount.**
   `resolve_fact()` accepted any `amended_amount` value once an amendment
   keyword existed anywhere in the supporting text, so "The payment amount
   has been corrected to ZAR 900" authorized a proposed amendment to ZAR 1.
   Fixed by adding `_sentence_states_amount()`: once a qualifying amendment
   sentence is found, the proposed amount (parsed via the existing
   `parse_fact_amount()`) must equal the amount stated in that same
   sentence, and if the sentence names a currency code it must match the
   proposed currency. A mismatch is rejected with a distinct reason
   ("do not state the proposed amended amount ...") before any currency
   conversion or state repair can run.

**Tests:** migrated Codex's two reproduction probes
(`docs/reviews/phase_a_review_probes.py::test_negated_or_conditional_cancellation_is_not_authorized`,
`::test_amendment_keyword_does_not_authorize_wrong_amount`) into
`code/tests/test_evidence.py` as
`test_negated_or_conditional_cancellation_is_not_authorized` (3 subcases:
negation, conditional, pending-refund) and
`test_amendment_keyword_does_not_authorize_an_unstated_amount`. Two
existing `EvidenceAuthorizationTests` assertions were updated for the new
(more specific) rejection wording, not weakened. Test count: 268 -> 270.

**Verification:**

```text
$ py -3.12 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 270 tests
OK

$ py -3.10 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 270 tests
OK

$ py -3.12 -B docs/reviews/phase_a_review_probes.py
Ran 5 tests
OK
```
All five probes in `phase_a_review_probes.py` pass, including the two
R-A-04/R-A-05 reproductions and the three previously-fixed R-A-02/R-A-03
cases.

**Not done in this pass:** the image-fallback limitation Codex noted
(`evidence.py`'s `source_span` fallback for image-only evidence remains
model-derived, uncertain evidence; this pass did not add independent
OCR/pixel verification, nor was that requested) and the full remaining
Phase A/B/C sequence (conflict-resolution order-dependence, independent
replay, spending/horizon validation, rounding/cache/retry/run-ID) --
unchanged from the prior handback's open list.

**Review requested from Codex:** yes -- corrective handback for R-A-04 and
R-A-05 from `docs/reviews/PHASE_A_CORRECTIVE_REVIEW.md`. No paid calls or
frozen-artifact changes were made.

## Phase A -- third corrective pass (R-A-06, R-A-07)

Codex's `docs/reviews/PHASE_A_SENTENCE_REVIEW.md` found two more defects
in the same narrow authorization boundary, both in `code/buy_or_wait/evidence.py`:

- **R-A-06** (`evidence.py:269`): the sentence splitter treated a decimal
  point as sentence punctuation, so "corrected to ZAR 900.50." was
  truncated to "...900" before amount binding, silently accepting a
  proposed 900 instead of the stated 900.50.
- **R-A-07** (`evidence.py:284`): the affirmative-effect checker was still
  keyword-plus-blacklist matching -- it accepted a question ("Has this
  payment been cancelled?") and a bare instruction ("Please cancel this
  payment.") as proof the cancellation had occurred, because neither
  contains a negation/conditional/uncertainty marker.

**Fix (both are structural, not additional blacklist phrases):**

- `_SENTENCE_SPLIT` now only splits on `.`/`;`/`!`/`\n` when the character
  is not both preceded and followed by a digit, so a decimal point inside
  a number is never a sentence boundary. `_sentences()` was rewritten to
  slice on match spans (instead of `re.split`, which discards the
  delimiter) so a sentence keeps its own trailing `?` -- needed for
  question detection -- while trailing `.`/`;`/`!` terminators are
  stripped so they can never be mistaken for part of a preceding number.
- `_is_affirmative_effect_sentence` now rejects any sentence containing
  `?` (interrogative) and any sentence that is a subjectless directive:
  `_is_imperative_instruction` matches only an exact bare verb
  ("cancel", "refund", "correct", ...) as the sentence's very first word
  (after an optional "please"/"kindly"), using a dedicated
  `_IMPERATIVE_VERBS_BY_KEYWORDS` exact-word list kept separate from the
  existing topic stems, so a noun like "Correction:" is never
  misclassified as the command "correct".

**Tests:** migrated Codex's two new probes into
`code/tests/test_evidence.py` as
`test_cancellation_question_or_instruction_is_not_a_completed_effect` and
`test_decimal_amendment_is_not_truncated_at_sentence_boundary` (the latter
also asserts the correctly-supported 900.50 amendment *is* accepted, not
just that the wrong 900 is rejected). Added one further test,
`test_cancellation_statement_with_question_mark_elsewhere_still_authorized`,
so the new `?` check is confirmed to key off the sentence actually being a
question, not merely off `?` appearing anywhere in the source message.
Test count: 270 -> 273.

**Verification:**

```text
$ py -3.12 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 273 tests
OK

$ py -3.10 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 273 tests
OK

$ py -3.12 -B docs/reviews/phase_a_review_probes.py
Ran 7 tests
OK

$ py -3.10 -B docs/reviews/phase_a_review_probes.py
Ran 7 tests
OK
```
All seven probes pass on both interpreters, including the two new
R-A-06/R-A-07 reproductions and the five previously-fixed cases.

**Not done in this pass:** everything listed as open in the prior
handback (image-fallback evidentiary strength, conflict-resolution
order-dependence, independent replay, spending/horizon validation,
rounding/cache/retry/run-ID, and the full Phase B/C sequence) is
unchanged.

**Review requested from Codex:** yes -- corrective handback for R-A-06 and
R-A-07 from `docs/reviews/PHASE_A_SENTENCE_REVIEW.md`. No paid calls or
frozen-artifact changes were made.

## Phase A -- fourth corrective pass (default-accept authorization gap)

Codex's `docs/reviews/PHASE_A_THIRD_PASS_REVIEW.md` confirmed R-A-06 and
R-A-07 fixed, and identified one more hole in the same boundary
(`evidence.py:342`, used by `evidence.py:357`): the cancellation checker
rejected enumerated bad phrases and then *defaulted to acceptance* --
it never required positive proof the effect had occurred. Two real
messages still authorized `cancelled=true`:

- "The cancellation policy is attached." (mentions the topic, states nothing)
- "Cancellation failed." (explicitly reports the opposite of a completion)

**Why cancellation only, not also amendment:** the reviewer's fallback
recommendation was to disable cancellation *and* amendment mutations
outright unless a real positive-effect validator exists. A validator was
achievable for cancellation without regressing any passing case, so that
path was taken instead of disabling a working, already-reviewed feature.
Amendment was left as-is because it already carries a structurally
different, stronger positive requirement that cancellation lacks: an
amendment has no accepted effect unless the qualifying sentence also
states the *exact* proposed amount (`_sentence_states_amount`), which is
categorically not "keyword survived a denylist" -- it is deriving the
claimed value from source text. No failure of that amount-binding check
was demonstrated or is currently known.

**Fix:** added `_CANCELLATION_COMPLETION_PATTERN`, a completed-effect
grammar (auxiliary/copula -- `has been`/`have been`/`was`/`were`/`is`/`are`
-- directly followed by an explicit past-participle: `cancelled`,
`voided`, `reversed`, `refunded`, `terminated`, `stopped`, `withdrawn`)
required, for the cancellation keyword set only, as a positive
precondition inside `_is_affirmative_effect_sentence`. This is a grammar
requirement, not another excluded phrase: "is attached" and "failed" do
not match any participle in the pattern, so both new adversarial
messages are now rejected without naming either one. All prior
message-backed cancellation tests ("has been cancelled", "was
cancelled") already use this exact grammar and continue to pass.

**Disclosed residual limitation (not fixed in this pass):** the same
class of default-accept risk is structurally possible for amendment if a
policy sentence happens to state the exact number being proposed without
asserting a correction (e.g. "Correction requests must be under $50."
next to a proposed `amended_amount=50`). No such failure was demonstrated
by Codex and none was found in the fixture/test corpus, but it has not
been proven absent either. Tracked as open for Phase B; amendment
mutations remain enabled based on the existing amount-binding safeguard
being the best available positive check today.

**Tests:** migrated Codex's new probe
(`phase_a_review_probes.py::test_topic_mentions_and_failed_cancellation_do_not_establish_effect`)
into `code/tests/test_evidence.py` as
`test_topic_mentions_and_failed_cancellation_do_not_establish_effect`.
Test count: 273 -> 274.

**Verification:**

```text
$ py -3.12 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 274 tests
OK

$ py -3.10 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 274 tests
OK

$ py -3.12 -B docs/reviews/phase_a_review_probes.py
Ran 8 tests
OK
```
All eight probes pass, including the new R-A-08-class reproduction and
the seven previously-fixed cases.

**Not done in this pass:** the disclosed amendment-side residual above;
everything else listed as open in the prior handback (image-fallback
evidentiary strength, conflict-resolution order-dependence, independent
replay, spending/horizon validation, rounding/cache/retry/run-ID, and the
full Phase B/C sequence) is unchanged.

**Review requested from Codex:** yes -- corrective handback for the
default-accept finding in `docs/reviews/PHASE_A_THIRD_PASS_REVIEW.md`. No
paid calls or frozen-artifact changes were made.

## Phase A -- fifth pass: disable `cancelled`/`amended_amount` mutations by default

`docs/reviews/PHASE_A_FOURTH_PASS_REVIEW.md` reproduced two more concrete
effect-to-target binding failures on top of the disclosed amendment-side
residual above, both accepted despite passing every prior check:

- "The amendment processing fee is ZAR 1." authorized `amended_amount=1
  ZAR` -- the number matched, but named a fee, not the payment's
  replacement amount.
- "Your cancellation request has been cancelled. The payment remains
  due." authorized `cancelled=true` -- the completion grammar correctly
  fired, but on the *request*, not the payment; the very next sentence
  states the opposite of what was being authorized.

Codex's explicit recommendation, after four corrective passes closing
individual adversarial phrasings one at a time: stop enumerating more
example words and instead disable `cancelled`/`amended_amount`
acceptance by default until a validator exists that binds the claimed
effect (and, for amendment, the amount) to its correct referent -- not
just detects that *some* qualifying effect occurred somewhere in the
cited text.

**Decision:** implemented exactly that. This is a disclosed capability
restriction, not a claim of complete evidence support for these two
fields.

**Fix:** added `evidence.ALLOW_EVENT_MUTATIONS = False` and a final gate
in `resolve_fact` -- after citation, scope, relevance, self-citation,
negation/conditional/uncertainty, completed-effect grammar, and (for
amendment) amount/currency binding all already passed -- that rejects
any `cancelled`/`amended_amount` proposal with a reason naming the
policy and this review. The rest of the validation pipeline was
deliberately left in place rather than deleted: it is still exercised by
tests, still the strongest available defense-in-depth if a future,
stricter validator re-enables the flag, and its absence would make the
two reproduced defects look like the *only* gaps rather than instances
of a structural one (matching a value/keyword is not the same as
establishing what it refers to).

**Tests:** updated `code/tests/test_evidence.py` so the acceptance-path
tests for these two fields now assert the new disabled-by-default
rejection (the underlying evidence checks they exercised -- e.g. that a
genuinely message-backed cancellation clears the completed-effect
grammar, or that a decimal amendment binds the full, untruncated number
-- are preserved as intermediate assertions/renamed test names, not
deleted). The two conflict-resolution precedence tests
(`test_amendment_beats_plain_amount`, `test_cancellation_beats_plain_amount`)
now construct an already-`accepted` `ExtractedFact` directly for the
mutation side, since `resolve_conflicts` precedence logic is independent
of, and still meaningful without, `resolve_fact`'s new gate. Both of
Codex's new fourth-pass probes were already written as
`assertEqual(status, "rejected")` with no reason-string coupling, so they
require no changes and pass as-is.

Added an end-to-end, fake-provider integration test class,
`tests.test_assist.MutationFieldsDisabledByDefaultTests`, per Codex's ask:
a fully evidence-backed cancellation and a fully evidence-backed
amendment (real message text that would clear every check if the field
were enabled) are proposed through `assist.extract_facts`, and the test
asserts `facts == ()`, that `apply_facts_to_events` leaves the target
event's `status`/`amount` unchanged, that `main.decide_one`'s forecast
output is identical patched vs. unpatched, and that `citation_note`
(what `main.py` folds into `decision_explanation`) is `None` -- i.e. the
disabled mutation cannot reach events, the forecast, or the rendered
explanation through any of those three seams.

Test count: 274 -> 276 (2 new fake-provider integration tests; no test
was deleted).

**Verification:**

```text
$ py -3.12 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 276 tests
OK

$ py -3.10 -B -m unittest discover -s code/tests -p "test_*.py"
Ran 276 tests
OK

$ py -3.12 -B docs/reviews/phase_a_review_probes.py
Ran 10 tests
OK
```
All ten probes pass, including both of Codex's new fourth-pass
reproductions.

**Not done in this pass:** re-enabling these two fields with a stricter
effect-to-target/amount-role validator is deferred, not attempted, per
Codex's explicit deadline guidance -- doing so correctly is more than a
patch and the remaining time is better spent on the still-open items
below. Everything listed as open in the prior handback (image-fallback
evidentiary strength, conflict-resolution order-dependence, independent
replay, spending/horizon validation, rounding/cache/retry/run-ID, and
the full Phase B/C sequence) is unchanged.

**Review requested from Codex:** yes -- handback for
`docs/reviews/PHASE_A_FOURTH_PASS_REVIEW.md`. No paid calls or
frozen-artifact changes were made.

---

## Deadline-handoff Block 1 (2026-09-13) — independent replay, citation gate, publish safety, split portability

**Status:** all four Block 1 items from `docs/DEADLINE_HANDOFF.md` complete
and verified with actual test output on this machine (not inherited/historical
numbers). Phase A language-rule work stopped, as instructed; event mutations
remain disabled. Block 2 (monthly recurrence / income-stream separation) not
yet attempted — time-boxed decision pending against the 16:00 IST freeze.

**1. Independent production replay (`validation.py`).** Added
`independent_replay(forecast, extra)`, which re-derives debit→credit→payment
ordering directly from `forecast.movements` and checks certifiability,
opening/minimum balance, and each payment's request-date/horizon bounds —
without calling `Forecast.walk`/`Forecast.is_safe`/`Forecast.breach_date`.
Rule P1 now fails on `independent_replay`'s own breach date. Regression test
`test_p1_independent_replay_survives_a_faulty_planner_safety_method` monkeypatches
`Forecast.is_safe`/`Forecast.walk` to always claim safety and confirms P1 still
fires — proving the gate cannot be fooled by a bug shared with the planner.

**2. Spending-action citation gate (`validation.py`, `spending.py`).** A
`stop:<event_id>`/`reduce_to:<event_id>:<amount>` literal is only accepted when
`event_id` equals the actual citation id (`series.event_ids[-1]`) of a
detected, eligible, permitted recurring **debit** `FixedSeries` — never any
event row that merely matches by category/description.
`test_e5_same_description_unrelated_event_cannot_authorize_a_cut` proves an
impostor event with the same category/description but a different id is
rejected (`E5`). Non-finite/negative `reduce_to` amounts are rejected both by
the gate (`E7`, `test_e7_reduce_amount_must_be_finite_and_non_negative`) and
defensively in `spending.apply_literals`, which now skips any parsed action
whose amount is non-finite or negative before it can reach the replay
forecast.

**3. Failed-output publication safety (`main.py`).** An unhandled per-row
exception ("crashed", distinct from an expected degraded/fallback row) now
blocks `publish()` entirely and returns exit code 1, leaving any prior
`output.csv` byte-for-byte untouched. New file `code/tests/test_publish_safety.py`
proves both directions: a simulated `RuntimeError` on one row preserves a
sentinel prior file and returns 1; a clean run still publishes and returns 0.

**4. Split portability (`data.py`, `evaluation/splits.py`, `evaluation/main.py`).**
Added `canonical_content_sha256` (newline-normalized before hashing) as the
gating identity for `sample_requests.csv` in the frozen split manifest;
`file_sha256` (raw bytes) is retained separately, for provenance only, and is
expected to differ across a CRLF/LF checkout. `SPLIT_VERSION` bumped 1 → 2;
`load_manifest` raises a clear `SplitError` for a legacy version-1 manifest
rather than silently auto-migrating. `split_manifest.json` was migrated with a
verified before/after equality check on the `dev`/`report` id lists (both
`True`) prior to writing. New tests in `test_splits.py`: LF/CRLF-checkout
content equivalence (`canonical_content_sha256` equal, `file_sha256` differs,
both verify against the same manifest), a real value change still rejected
(`test_an_actual_content_change_is_still_rejected`), and legacy-manifest
rejection (`test_version_1_manifest_is_rejected_with_a_migration_message`).

**Verification (actual run, this session, this machine):**

```text
$ python -m unittest discover -s tests -t . -p "test_*.py"        # from code/
Ran 290 tests in 16.1s
OK
```

290 tests, up from 276 at the start of this pass (14 new: 5
`IndependentReplayTests`, 1 faulty-planner P1 regression, 1 same-description-
citation regression (E5), 1 finite/non-negative regression (E7), 2
`test_publish_safety.py`, 1 frozen-manifest-verifies-on-this-machine test, 3
`PortabilityTests`, plus test-file unpacking fixes for the new 6-tuple
`_spending_setup()` return value). No test was deleted or weakened to make
this pass; all 276 prior tests still pass unmodified in behavior.

**Known limitation surfaced during this pass, not fixed speculatively:** the
LF/CRLF test fixture initially wrote both encodings to the same filename,
silently overwriting the LF file with the CRLF one and producing a false
failure (`file_sha256` equal when it should differ). Fixed by giving the two
fixture files distinct names — a bug in the new test, not in
`canonical_content_sha256`/`file_sha256` themselves, which were correct
throughout.

**Review requested from Codex:** yes — handback per `docs/DEADLINE_HANDOFF.md`.
Worth attacking specifically: whether `independent_replay`'s re-derivation
still shares any code path with `Forecast` that could hide a common bug beyond
what the faulty-planner test exercises; whether the citation-gate change
(`series.event_ids[-1]` keying) has any gap for a series with zero or one
recorded event; and whether canonical-hash newline normalization is the right
boundary (vs. e.g. also trimming trailing whitespace) for cross-platform
manifest portability.
