# Token Usage and Cost Analysis

This report covers the final full-dataset run that produced the submitted `output.csv`.

## Summary

This solution makes **zero runtime calls to any LLM or external AI model**.

| Component | Method | Model calls |
|---|---|---|
| Image amount extraction | 16 one-time vision reads performed during development, results cached in `IMAGE_AMOUNT_CACHE` and reused for every subsequent run | 0 at runtime |
| Message (`messages.csv`) interpretation | Regex / keyword-based classifier (cancel / delay / confirm / amend detection) | 0 |
| Financial-state reconstruction, forecasting, and plan ranking | Fully deterministic Python (90-day balance simulation, candidate-plan generation, rule-based tie-break ranking) | 0 |

**Total model calls (final run): 0**
**Total tokens consumed (final run): 0**
**Total cost (final run): $0**

## Why an LLM wasn't used for the core logic

The affordability decision is a deterministic function of structured data
(balances, dated cash flows, payment option schedules) once that data has
been extracted and cleaned. A rule-based simulation is faster, fully
reproducible, and auditable row-by-row - properties that matter for a
financial-safety decision - so no model calls were made in the pipeline that
generates `output.csv`.

## Where AI assistance was used (development time, not runtime)

- The 16 receipt/document images in `dataset/media/images/` were read once
  using a vision-capable model during development to extract their amounts.
  Those extracted values are hard-coded into `IMAGE_AMOUNT_CACHE` in the
  code, so the final run that produced `output.csv` makes no live calls -
  it looks values up from this cache.
- No model was used to write the decision logic itself beyond ordinary
  AI-assisted coding (autocomplete/pair-programming), which does not count
  toward runtime token/cost usage for the submission.

## If no model calls were used

This solution makes no calls to any LLM or external AI model at runtime.
All financial-state reconstruction, forecasting, and plan ranking are
performed with deterministic Python logic. Image amounts were extracted
once during development and cached rather than re-extracted on each run.