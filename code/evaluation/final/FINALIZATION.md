# Finalization record

The submitted output is the original assisted run `20260913T041036Z`.
It has not been replaced by sample predictions or a later baseline run.
All 250 rows reproduce exactly from the recorded accepted facts. Its method
distribution is 53 full, 32 installments, 7 partial, 11 wait, 147 not recommended.
The unresolved/degraded requests are request_64 and request_73.

## Public reporting comparison

The frozen 15-example reporting subset was run with the real Anthropic provider
and compared with the deterministic baseline through the shared prediction path.
Both obtain status 6/15, method 8/15, plan exact match 6/15, and date exact match
3/15. There is no measured improvement on this subset. All samples had prior
development exposure; these are public regression results, not hidden-test results.
The printed metric note saying degraded rows are counted as wrong is inaccurate:
the current scorer compares their emitted labels normally and reports degradation
separately. No failure-penalized accuracy is claimed here.

The separate reporting run made 2 successful calls, 6,774 input and 148 output
tokens (6,922 total). Estimated additional cost: $0.015028 at $2/$10 per million
input/output tokens. These numbers are excluded from the submission-run report.
An initial sandbox attempt failed with connection errors on both investigated
rows, with no returned usage; that is not recorded as a proved zero bill.
The successful retry ran with SDK retries disabled, max 4 provider attempts,
20-second SDK timeout, and a 20,000 returned-token stop threshold. No final
prediction output was changed during reporting evaluation.

## Limits of the checks

- Citation membership and ownership are validated. The appended citation list
  is not a complete claim-by-claim semantic verification of the source content.
- The original run's ledger tracks successful responses. Failed-attempt billing,
  SDK internal retries, precise latency, and the returned model ID were not
  recorded. The configured requested model is corroborated by the saved cache.
- Input/code hashes were collected at finalization and exact output reproduction
  was checked; a historical code revision was not recorded at inference time.
- The evidence router skips requests without unknown amounts. Model failure can
  therefore preserve an incomplete deterministic forecast. Model facts currently
  support only a narrow set of event changes; user-level amendments are limited.
- Token thresholds are checked on returned usage, and are not hard dollar caps.
- A successful package check does not mean these accuracy limitations are solved.

The required conversation transcript must be exported from the actual assistant
sessions, with the exposed API key redacted. The repository log contains partial
summaries and is not a complete verbatim transcript. No synthetic transcript is
presented as an original conversation export.
