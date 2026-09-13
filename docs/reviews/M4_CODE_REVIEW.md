# M4 no-cost implementation review

Date: 2026-09-13. Reviewer: Codex CLI.

## Verified

- `py -3.12 -B -m unittest discover -s code/tests -t code -p "test_*.py"` — 252 tests, OK.
- `predict_one()` is shared by CLI publication and evaluation scoring.
- `--compare-baseline` now executes a deterministic comparison for assisted mode.
- `code/package.py` uses an explicit allowlist and places
  `evaluation/usage_report.md` at the archive root.
- Assisted/no-provider smoke execution remains fail-closed.

## Blocking issue before paid run

`_build_assist_config()` still constructs `UsageLedger()` with both full-run
budgets set to `None`. Per-row timeout/retry limits exist, but the full 250-row
run has no explicit call or token ceiling. Do not start a real Anthropic run
until the CLI wires explicit budgets (preferably environment/CLI-configurable)
and prints them in the run header and usage ledger. Add a test proving the
configured full-run cap stops further provider calls and leaves a conservative
row.

The Anthropic model identifier (`claude-sonnet-5`) should also be confirmed
against the account/API before the paid run; a configuration error must fail
closed without spending retries.

## Disposition

M4 no-cost work is provisionally accepted. Real-run authorization remains
blocked by the missing full-run budget configuration and model-id confirmation.
