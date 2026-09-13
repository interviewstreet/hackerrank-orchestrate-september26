# Final handoff — 2026-09-13

## Artifacts

- `code.zip`: 49 files; extracted package passes its audit and all 295 tests.
- `output.csv`: original 250-row assisted output retained, with exact trace-based reproduction.
- `code/evaluation/usage_report.md`: populated from the original recorded inference run.
- `code/evaluation/final/`: source trace, usage, manifest, finalization notes, reporting comparison.
- `docs/reviews/FINAL_ARCHIVE_VERIFICATION.json`: independent serialized checks, archive/output hashes, clean-extraction test output.

No source financial data or prediction logic changed during finalization. The
dataset has no git changes. No `.env` or repository log is tracked, and no
credential pattern was detected in the archive. Key revocation itself cannot be
verified locally.

## Results and limits

Original inference: 11 recorded successful calls, 39098 input tokens, 1129 output
tokens, estimated $0.089486 total ($0.000357944 per request). Separate successful
reporting evaluation: 2 calls, 6774 input/148 output tokens, estimated $0.015028.
Pricing source is linked in the usage report. The failed sandbox connection
attempts had unknown/unreported usage and are explicitly disclosed.

The real public reporting comparison returns status 6/15 and method 8/15 for
both modes. The assisted model does not improve these metrics. Final-output
requests request_64 and request_73 remain degraded. These findings supersede
earlier broad assurances that all behavior is production-safe or that model
integration alone demonstrates decision accuracy.

The archive is built and verified; final submission still requires the actual
chat transcript export. The local log is incomplete and should not be presented
as a verbatim transcript. Redact the exposed API key in all exported transcripts.
The participant retains the choice to submit this documented version or ask
Claude to improve the remaining forecast/evidence coverage before another review.
