# M4 budget closure review

Date: 2026-09-13. Reviewer: Codex CLI.

The budget-boundary finding is resolved. `UsageLedger.check_budget()` now treats
call and token usage at `>=` the configured ceiling as exhausted, and
`BoundedCaller.call()` checks before starting a provider call. CLI flags and
environment variables provide explicit full-run defaults (60 calls / 300,000
tokens), while tests cover exact-boundary behavior.

Verification: 254 tests pass on Python 3.12; `output.csv` contains the header
plus 250 request rows after deterministic regeneration; `.env` is ignored and
`.env.example` contains no secret.

A real Anthropic run is now technically ready, but still requires explicit
participant authorization of the smoke/full-run ceilings and spend.
