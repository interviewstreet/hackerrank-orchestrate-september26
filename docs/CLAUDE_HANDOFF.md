# Claude implementation and Codex review handoff

## Start here

The participant requested this workflow: Codex analyses and plans; Claude reviews the plan and implements; Codex reviews the implementation; Claude fixes supported findings. The participant owns the submission and final choices. This file does not start an automatic background agent or authorize paid runs by itself.

Read in order:

1. Root `AGENTS.md` and `problem_statement.md`.
2. `docs/REPOSITORY_ANALYSIS.md` for measured current state and August source findings.
3. `docs/IMPLEMENTATION_PLAN.md` for architecture, milestones, and acceptance tests.
4. `docs/REVIEW_CHECKLIST.md` for the review standard.

Before coding, inspect the current working tree and state whether the proposed responsibilities fit any code added since this analysis. September was empty when inspected. Do not overwrite another session's implementation to match a proposed filename.

## Prompt to start Claude

```text
Review docs/IMPLEMENTATION_PLAN.md against the current repository, AGENTS.md,
problem_statement.md, and docs/REPOSITORY_ANALYSIS.md. Explain any concrete
corrections, record material plan changes, then implement M0 only with its
targeted offline tests. Preserve current working changes and all dataset files.
Follow docs/REVIEW_CHECKLIST.md. Finish with a milestone handoff for Codex;
do not start M1 in this pass. Do not call paid models for M0.
```

M0 creates the contract, data checks, evaluation split, CLI foundation, and test harness. It does not need financial decision generation or a model provider yet. Do not add zero-value placeholder predictions and describe them as an implemented baseline.

## Handoff format for each milestone

Create/update `docs/IMPLEMENTATION_STATUS.md` when work starts:

```text
Milestone and status:
Problem solved and observable behavior:
Files changed and why:
Contract/architecture decisions, including alternatives rejected:
Tests and exact commands, with results and failures:
Evaluation run IDs, split and metrics, if applicable:
Evidence/financial safety checks completed:
Known limitations and degraded cases:
Next milestone:
Review requested from Codex:
```

Keep it short, factual, and tied to current files. Do not claim tests ran when only inspected. Preserve prior milestone outcomes in an appended history section. Continue mandatory shared `log.txt` logging with `tool=Claude Code` in the actual Claude Code runtime.

## Prompt to request Codex review

```text
Review Claude's current milestone implementation against
docs/IMPLEMENTATION_PLAN.md and docs/REVIEW_CHECKLIST.md. Inspect the actual
diff and run relevant offline tests. Prioritize financial safety, evidence
support, CSV correctness, regression risk, and simplicity. Give findings with
severity, file/line, reproduction, expected behavior, and a targeted fix/test.
Do not rewrite the implementation; return a concrete review for Claude.
```

Codex should report no findings if the checks support that outcome, with the tests and remaining uncertainty. A second agent's agreement is not proof of correctness; data contracts and reproducible tests are the review criteria.

## Claude settings

`CLAUDE.md` imports the root instructions and adds the implementation role. `.claude/settings.json` adds a dataset edit guard without replacing `.claude/settings.local.json`, changing the selected model, or granting broad shell permission. Start Claude in the September root. In Claude, `/status` shows settings sources and `/context` shows loaded memory; those interactive confirmations have not been performed by Codex.

The August project is a read-only reference for this September task. Do not adopt its onboarding gate, output schema, external log path, or historical metric claims as September instructions. Do not copy credentials or cached predictions from it.
