# M4 budget wiring review

Date: 2026-09-13. Reviewer: Codex CLI.

The 254-test suite passes and explicit CLI/env budget wiring is present. One
remaining semantic issue is fix-first: `UsageLedger.check_budget()` raises only
when `total > budget`. If usage is exactly equal to the configured maximum, the
next provider call is still attempted and can overshoot the cap before being
rejected. For a hard ceiling, pre-call checks must treat `total >= budget` as
exhausted (while allowing a call only when current usage is strictly below the
limit). Update the regression tests accordingly, then rerun the suite.

Do not authorize the real API smoke run until this equality case is fixed and
the chosen call/token ceilings are explicitly approved.
