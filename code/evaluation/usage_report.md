# Token Usage Report

Final full-dataset run that produced `output.csv`.

## Run Summary

- Date (UTC): 2026-09-12 14:03:45
- Provider: Groq (OpenAI-compatible API)
- Requests processed: 1
- Duration: 1m 2s
- Total model calls: 4

## Per-Model Breakdown

| Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
| --- | --: | --: | --: | --: | --: |
| `openai/gpt-oss-20b` | 1 | 1,781 | 670 | 2,451 | $0.0003 |
| `qwen/qwen3.8-27b` | 3 | 8,282 | 291 | 8,573 | $0.0014 |

## Overall Totals

- Total model calls: 4
- Total tokens: 11,024
- Average tokens per request: 11,024
- Average calls per request: 4.00
- Estimated total cost: $0.0018
- Estimated cost per request: $0.001751

## Notes

- Pricing is per million tokens, from `code/config.py::MODEL_PRICING`.
- Receipt OCR results are cached by `image_id`, so each of the 16
  dataset images is read by the vision model at most once per run.
- Requests with no messages and no linked images need no evidence
  calls, which is why average calls per request is below the cap.
- No API keys or credentials are recorded here.
