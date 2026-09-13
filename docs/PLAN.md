# SUPERSEDED — Claude planning draft (2026-09-12)

> **This document is not the controlling plan.**
> The controlling plan is [`docs/IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md)
> (milestones M0–M4), with [`docs/REPOSITORY_ANALYSIS.md`](./REPOSITORY_ANALYSIS.md)
> as the measured baseline and [`docs/REVIEW_CHECKLIST.md`](./REVIEW_CHECKLIST.md)
> as the review standard. Root `AGENTS.md` §9 and `CLAUDE.md` name the same chain.
>
> The original Wave 0–4 draft that lived here was reviewed by Codex
> ([`docs/AGENT_CONFIG_REVIEW.md`](./AGENT_CONFIG_REVIEW.md), verdict *fix-first*)
> and several of its rules were found to be financially wrong. Rather than leave a
> 700-line document whose rejected rules could be copied back into the
> implementation, it has been reduced to the two things still worth keeping: the
> measurements, and an explicit register of what was wrong.
>
> Disposition of every finding: [`docs/FINDING_TO_CHANGE.md`](./FINDING_TO_CHANGE.md).

---

## 1. Rejected rules — do not reintroduce

Each of these appeared in the original draft and in the first version of the
`.claude/agents/*.md` prompts. They are recorded here so that a future session
recognises them as already-rejected rather than re-deriving them.

| Rejected rule | Why it is wrong | Replacement |
|---|---|---|
| FX lookup falls back to the *nearest prior 15th* rate | `AGENTS.md` §6.1 requires the **settlement-date** rate in the stated direction. An older rate is not conservative in either direction. Measured: **140/140 foreign-currency events have an exact directed settlement-date rate row** | Exact `(settlement_date, from, to)` lookup. A missing rate is unresolved evidence, never a carried-forward or reciprocal guess |
| `exchange_rates.csv` only ever dates rows on the 15th | Measured: distinct days-of-month are **{1, 15}** | Never key logic on the day-of-month at all |
| A category **alias layer** (e.g. `food_delivery → delivery_membership`) | Invented, not measured. Measured: `expense_categories_to_protect` / `_reduce` / `_stop` contain **only** real event categories (10/5/5 distinct tokens, zero unknown). The only non-event tokens (`retirement_investment`, `emergency_savings`, `travel`) appear **solely** in `financial_priorities`, which is a separate goal vocabulary | Exact membership against two separate closed vocabularies. Unknown token ⇒ fail closed (event becomes immutable). No alias map |
| `spending_changes_needed` is "September's evidence-citation field" | It specifies **financial interventions**, not provenance. A fully affordable request can cite a payroll message while needing no spending change | Two independent axes: (a) legality of spending actions and their event targets; (b) claim-level provenance for every material fact. Never tune action counts toward a sample distribution |
| Unresolved amount ⇒ exclude the event and continue | **15 of the 16 blank amounts are debits.** Dropping an unknown obligation manufactures headroom that was never proved to exist | A material unresolved **debit** blocks a positive safe amount unless an independently justified conservative bound establishes safety. Unknown **credits** are excluded (they add no buying power) |
| Closed 9-archetype `MessageEffect` enum | Cannot represent income cessation. `message_09` (user_12): *"The current seasonal contract has ended. No off-season income or renewal has been confirmed."* Forcing this to `no_effect` leaves inferred salary funding purchases | Effect vocabulary derived from financial operations, including cessation and bounded/interval amendments, with an explicit `unsupported` state |
| C13: `not_recommended` ⇒ `earliest_date_for_full_payment` is empty | `problem_statement.md:163` states capacity is independent of method preference. A user can have capacity today yet accept only an unsafe offer | Empty **iff** no safe single full payment exists anywhere in the forecast. Capacity and eligibility are stored and validated separately |
| R1: regex every numeral in the explanation and require it to be a known amount | Dates, event/message IDs, installment counts and fees are all numerals. A truthful `message_198` reference would fail | Compare **structured claim values** carried through from accepted proof facts; never scrape digits from prose |
| R2: keyword membership per method | *"Do not pay today; wait"* contains `today` and would pass the full-payment check while contradicting it | Render prose **from** accepted facts via validated templates, so contradiction is not representable |
| E/C/R rule set is sufficient validation | Matching a seller schedule exactly still permits a plan that breaches the minimum balance or misses the deadline | Independently **replay** every selected plan against the forecast with a separate oracle |
| `float` for amounts, reductions, safe capacity, installments | Binary float cannot hold exact plan totals or threshold comparisons | `Decimal` parsed from source strings, explicit rounding policy (`code/buy_or_wait/money.py`) |
| "Wave 1 is submittable" | `AGENTS.md` §6.5 requires a populated `evaluation/usage_report.md` for the final run. An empty file fails even for a zero-model baseline | Runnable-baseline and submission-ready are separate milestones (M1 vs M4) |
| Target: "most rows should select zero tools" | An assumption, not a measurement. Codex measured **198 of 250 evaluation users have a message** | Measure and report the actual distribution; test selectivity on a genuinely evidence-free synthetic row only |

## 2. Measurements worth keeping

Independently verified in this repository on 2026-09-12 (stdlib CSV reads; each
number reproduced rather than taken from the analysis document).

### Dataset shape

| File | Rows | Verified |
|---|---|---|
| `requests.csv` | 250 | `user_26`…`user_275`, one request per user; deadline offsets span **6–86 days**; `allows_partial_payment` 170 false / 80 true |
| `sample_requests.csv` | 25 | 25 distinct request IDs, 25 distinct users, **zero user overlap** with `requests.csv` |
| `financial_profiles.csv` | 275 | `max_installment_months` blank for 119 users |
| `financial_events.csv` | 25,342 | settled 25,148 · pending 71 · scheduled 70 · cancelled 22 · failed 21 · unrealized 10; debit 23,609 · credit 1,723 · non_cash 10; fixed 21,138 · reducible 2,682 · stoppable 1,297 · reducible_or_stoppable 225 |
| `request_payment_options.csv` | 790 | 2–4 per request (2×65, 3×180, 4×30); methods **only** `full_payment` (275) and `installments` (515) |
| `messages.csv` | 215 | one per user; 128 carry `request_id`; 39 carry `related_event_id`; English + Bahasa Indonesia |
| `images.csv` | 16 | 1:1 with the 16 blank-amount events |
| `exchange_rates.csv` | 134 | `from_currency` ∈ {USD, EUR}; 5 distinct directed pairs |

### Facts that drive design decisions

- **Blank amounts: 15 debits + 1 credit.** Unreadable ≠ zero.
- **FX: 140/140 foreign-currency events resolve on an exact directed settlement-date rate.** 139 settle on the 15th, 1 on the 1st. No fallback rule is needed or permitted.
- **Payment options: all 790 satisfy `payment_amount × number_of_payments == total_payable_amount`** under `Decimal`. Validate at runtime; never silently repair.
- **434 of 515 installment offers end after `desired_completion_date`** (428 end more than 90 days after `request_date`). Most offers are ineligible — reject them, never truncate a schedule to fit.
- **Every one of the 5 gold installment picks ends on or before its deadline**, which supports deadline rejection as the primary eligibility filter.
- **Profile permission tokens are always actionable**: zero cases where a `willing_to_reduce` / `willing_to_stop` token matches none of that user's own event categories.
- **Rounding**: no gold amount exceeds 2 decimal places, and trailing zeros are stripped (EUR `603.3`, ZAR `25256`, IDR `17229139.2`). There is no per-currency precision table.
- `image_01.png` → `event_253` is an Indonesian payslip; the required value is the **Net Pay** line (IDR 4,365,000), not gross.
- Image files are `dataset/media/images/<image_id>.png` — PNG, despite August's dataset having mislabelled extensions.

### Environment (this machine, not a deployment requirement)

- `python` → **3.10.11**, with `pydantic` 2.13.4, `anthropic` 0.120.2, `pandas` 2.2.1, `dotenv`.
- `py -3.12` → **3.12.5 with none of those packages installed.**
- Consequence: the plan's proposed `py -3.12` commands would fail from M2 onward. Standardise on `python`, and keep the financial core stdlib-only so it runs under both.

## 3. The August diagnosis, correctly qualified

The original draft claimed the August evidence F1 of 0.480 was *caused* by
over-citation. Codex correctly flagged that comparing 30 sample labels against
110 different prediction rows cannot establish causation, and that another
August journal reports 0.526 from a different run.

What is actually supported:

- `code/router/validator.py:14-18` in the August tree already filtered cited IDs to the retrieved candidate set, so "the model invented IDs" was **not** the defect.
- On the 110-row full run the model emitted 2 IDs on 45% of rows and 0 on 16%; the 30 gold sample rows carry 1 ID on 83%. These are **different row populations**, so this is a suggestive distribution mismatch, not a measured cause.
- 0.480 and 0.526 are historical August run numbers. Neither is a September measurement, and neither may be quoted as one.

The design consequence survives the qualification: evidence selection should not
depend on a soft prompt instruction. That is implemented as deterministic
pre-filtering plus claim-level provenance validation, per
`docs/IMPLEMENTATION_PLAN.md` §4.
