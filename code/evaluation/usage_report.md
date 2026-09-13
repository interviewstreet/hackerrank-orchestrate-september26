# Token Usage and Cost Analysis

This report covers the final full-dataset run that produced the submitted `output.csv`.

## Summary

| Field | Value |
|---|---|
| Total requests processed | 250 |
| Model provider(s) used | e.g. Anthropic |
| Model(s) used | e.g. claude-sonnet-4-6 |
| Total model calls | TODO |
| Total input tokens | TODO |
| Total output tokens | TODO |
| Average input tokens / request | TODO |
| Average output tokens / request | TODO |
| Estimated total cost (USD) | TODO |
| Estimated cost per request (USD) | TODO |

## Per-model breakdown

_If you used more than one model (e.g. a cheaper model for image reading and a
stronger one for ambiguous message interpretation), break totals down here._

| Model | Calls | Input tokens | Output tokens | Est. cost (USD) |
|---|---|---|---|---|
| e.g. claude-sonnet-4-6 | TODO | TODO | TODO | TODO |
| e.g. claude-haiku-4-5 | TODO | TODO | TODO | TODO |

## What model calls were used for

- e.g. Extracting amounts from receipt/payroll images (`extract_amount_from_image`)
- e.g. Interpreting ambiguous natural-language messages tied to financial events
- (State plainly if the core forecasting/ranking logic is fully deterministic
  Python with zero model calls — that's a legitimate and often stronger
  approach for this task.)

## Notes on cost calculation

- Pricing basis: TODO (link or note the per-token rate used, and its date)
- Any caching, batching, or retry logic that affected totals: TODO

## If no model calls were used

If your solution is fully deterministic Python (recommended for the
forecasting/ranking core), state that explicitly instead of the table above:

> This solution makes no calls to any LLM or external AI model. All
> financial-state reconstruction, forecasting, and plan ranking are performed
> with deterministic Python logic. [If applicable: image amounts were
> extracted using classical OCR (e.g. Tesseract) rather than a model.]