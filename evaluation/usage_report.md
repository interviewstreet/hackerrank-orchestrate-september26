# Usage Report: Buy or Wait? Financial Decision Agent

## 1. Model Configuration
- **Model Provider**: Google Gemini
- **Model Name**: gemini-2.5-flash
- **SDK**: `google-genai` (Official Google GenAI Python SDK)

## 2. Extraction Call Summary
- **Total Model Calls**: 37 (15 image extractions + 22 batched message extractions)
- **Input (Prompt) Tokens**: 66,483
- **Output (Candidates) Tokens**: 49,849
- **Total Tokens**: 116,332
- **Average Tokens per Request** (250 requests): 465.3

## 3. Cost Breakdown
- **Estimated Total Cost (USD)**: $0.0266
- **Estimated Cost per Request (USD)**: $0.000106

## 4. Division of Responsibility: AI vs Deterministic
| System Task | Implementation Engine | Rationale |
|---|---|---|
| Unstructured Document Image Reading | **Gemini Vision** | Reads amounts, dates, and types from scanned receipts, bills, and payslips. |
| Unstructured Message Parsing | **Gemini Flash** | Extracts confirmed payroll notices, invoice approvals, and cancellations. |
| Prompt-Injection Defense | **Pydantic Validation** | Discards embedded instructions and enforces valid `event_*` dataset IDs. |
| 90-Day Daily Cash Flow Simulation | **Deterministic Python** | Simulates exact balances, debit-before-credit ordering, and boundary preservation. |
| Binary-Search `amount_safe_to_pay` | **Deterministic Python** | Mathematical search in integer cents guaranteeing `minimum_balance_to_keep`. |
| Payment Plan Generation & Ranking | **Deterministic Python** | Evaluates all eligible candidate options against 6 strict priority rules. |
| Decision Explanations | **Deterministic Python** | Generates grounded, rule-based text without hallucination risk. |

## 5. Cache Behavior
- **Storage Location**: `code/extraction_cache/` (JSON files keyed by image/message ID).
- **Execution Policy**: Cached facts are reused on subsequent runs, making full pipeline execution deterministic, instantaneous, and zero-cost during repeated evaluation.
- **Cache Invalidation**: Cache files are omitted from source control via `.gitignore`.
