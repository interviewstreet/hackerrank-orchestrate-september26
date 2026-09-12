# Token Usage Report

Final full-dataset run that produced `output.csv`.

## Run Summary

- Date (UTC): 2026-09-12 16:27:08
- Provider: Groq (OpenAI-compatible API)
- Requests processed: 250
- Duration: 0m 0s
- Total model calls: 0

## Per-Model Breakdown

| Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
| --- | --: | --: | --: | --: | --: |

## Overall Totals

- Total model calls: 0
- Total tokens: 0
- Average tokens per request: 0
- Average calls per request: 0.00
- Estimated total cost: $0.0000
- Estimated cost per request: $0.000000

## Notes

- Pricing is per million tokens, from `code/config.py::MODEL_PRICING`.
- Receipt OCR results are cached by `image_id`, so each of the 16
  dataset images is read by the vision model at most once per run.
- Requests with no messages and no linked images need no evidence
  calls, which is why average calls per request is below the cap.
- No API keys or credentials are recorded here.
