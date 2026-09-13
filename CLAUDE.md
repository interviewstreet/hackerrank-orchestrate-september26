@AGENTS.md

## September implementation role

The participant's workflow is Codex planning/review, Claude implementation, then
Codex review of the actual code and tests. Read `docs/CLAUDE_HANDOFF.md`,
`docs/REPOSITORY_ANALYSIS.md`, `docs/IMPLEMENTATION_PLAN.md`, and
`docs/REVIEW_CHECKLIST.md` before the first implementation pass.

Review the plan against the current files before editing. Preserve working
behavior and concurrent changes. Implement one coherent authorized milestone
with targeted offline tests, record its results in `docs/IMPLEMENTATION_STATUS.md`,
and hand it back for Codex review. Resolve routine choices within that milestone
without asking for confirmation at each edit.

Keep money, forecasting, payment eligibility, evidence membership, and output
validation deterministic. Models propose sourced financial facts; code validates
them. Never silently strip citations while retaining unsupported claims. The
September CSV has exactly eight contract columns; August's notification schema
does not apply.

Use the existing machine-local settings and environment credentials. Do not
start paid model runs for planning or M0. Keep dataset files unchanged, generate
predictions at root `output.csv`, and keep mandatory logs beside root `AGENTS.md`.
