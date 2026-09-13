# M0 closure review

Date: 2026-09-12. Reviewer: Codex CLI.

## Verdict

**M0 is accepted and ready for M1.** The eight boundary findings are now
covered by implementation and tests. The independent seven-probe regression
suite passes, and the normal suite reports 106 passing tests on the available
Python 3.12 interpreter.

## Verified commands

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"` — 106 tests, OK.
- `py -3.12 docs/reviews/m0_regression_tests.py` — 7 probes, OK.
- `py -3.12 code/main.py` — dataset audit: 0 findings, 0 errors.
- `py -3.12 code/evaluation/main.py --show-split` — frozen split `ecafb49177d9`, disjointness PASS.

The claimed Python 3.10 run could not be reproduced in this environment
because the registered 3.10 executable is inaccessible; keep the two-version
command in CI or the final verification transcript when available.

## Scope boundary

This review accepts only M0: strict loading, safe media resolution, ownership
scoping, exact decimal parsing, manifests, date validation, and frozen
evaluation metadata. It does **not** approve financial forecasting, evidence
selection, rationale coherence, model retries/budgets, or output generation;
those remain M1–M4 work.

## Next gate

Authorize M1 as a deterministic financial core. Require synthetic fixtures plus
an independent replay oracle for cash-state reconstruction, exact settlement-date
FX, recurrence/income handling, conservative forecast, plan feasibility, and an
atomic eight-column output writer. No paid model calls should be introduced in
M1.
