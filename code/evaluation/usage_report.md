# Final full-dataset usage report

Run: `20260913T041036Z` (2026-09-13 04:10:36 UTC); 250 evaluation requests.
Provider: Anthropic Claude API. Requested model: `claude-sonnet-5`.
The original ledger does not record the response model ID; the requested ID
is corroborated by the extraction cache and provider configuration.

| Metric | Final run |
|---|---:|
| Recorded successful model calls | 11 |
| Input tokens | 39098 |
| Output tokens | 1129 |
| Total tokens | 40227 |
| Average input tokens / request | 156.392 |
| Average output tokens / request | 4.516 |
| Average total tokens / request | 160.908 |
| Cache read / write tokens | 0 / 0 |
| Estimated total cost (USD) | 0.089486 |
| Estimated cost / request (USD) | 0.000357944 |

Estimate: input tokens x $2/million + output tokens x $10/million, using
[Anthropic's published pricing](https://platform.claude.com/docs/en/about-claude/pricing)
verified 2026-09-13. The pricing page explicitly states the earlier planned
September increase did not occur. Taxes/account discounts are excluded;
this is a list-price estimate, not an invoice.

Configured run limits: 60 calls / 300000 tokens.
The legacy ledger counts returned usage, not every transport attempt; SDK retries
and usage of interrupted attempts are not independently accounted. The token
limit is checked after responses and is not a guaranteed dollar spending cap.
No extraction-cache hits appear in this run's traces.

6 accepted facts; 1 rejected facts;
2 degraded rows: request_64, request_73. All 250 rows reproduce from
their recorded accepted facts and pass the existing planner gate. This does not
prove all extracted facts or forecasts are semantically correct. Extraction is
currently triggered only for unknown amounts; message-only amendments on other
rows are not investigated by this version.

Output SHA-256: `e445b252d90e158bf51b21f33f6003b5d93014b45aba694cc0a3c35d513cf1fa`.
Run trace, original usage, and finalization-time input/code hashes are preserved
under `evaluation/final/`. Public-sample evaluation usage is reported separately
and excluded from the above final full-dataset totals. Public samples have prior
development exposure and are not an unseen holdout.
