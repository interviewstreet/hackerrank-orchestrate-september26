# M1 implementation review

Date: 2026-09-13. Reviewer: Codex CLI.

## Verdict

**M1 financial core accepted for continued development.** The deterministic
pipeline is model-free, uses exact directed FX, reserves future obligations,
blocks certification when debit amounts are unresolved, checks same-day order,
replays proposed plans, and publishes a contract-valid eight-column file.

## Verified

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"` — 150 tests, OK.
- `py -3.12 code/main.py --mode deterministic` — 250 rows, zero gate failures and zero unhandled errors.
- `py -3.12 code/evaluation/main.py --split dev` — status 5/10, method 5/10.
- Published output independently satisfies header, ordering, uniqueness, bounds,
  enums, chronology, totals, deadline, and status/method invariants.

## Finding before final evaluation

`code/evaluation/main.py --compare-baseline` only prints `baseline compare: yes`;
the flag is not consumed by `score()` and no second run or delta is reported.
This is not a financial-safety defect, but it fails the evaluation-credibility
requirement from the evaluator feedback. Implement an explicit baseline-vs-SUT
comparison once M2/M3 provide a distinct assisted system; until then, either
reject the flag as unavailable or state clearly that deterministic is itself the
baseline. Do not report the current output as a completed submission.

## Sequencing decision

Proceed with M3 before M2. M3 can remain deterministic and should add candidate
generation for partial payments, supplied installment options, and permitted
spending changes. Preserve the existing replay gate and add negative fixtures
for every new eligibility rule. Keep the baseline-comparison item tracked for
the final evaluation milestone.
