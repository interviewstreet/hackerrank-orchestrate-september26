# Buy or Wait? — AI-Powered Financial Decision Agent

Winner-grade solution for the **HackerRank Orchestrate** hackathon challenge: **Buy or Wait?**

An intelligent financial agent that evaluates purchase requests against conservative 90-day cash flow forecasts, personalized user commitments, fixed dated exchange rates, and unstructured third-party evidence from document images and messages.

---

## 1. Problem Summary

Given purchase or payment requests in `dataset/requests.csv`, the agent decides whether the user should:
- **Pay in full today** (`affordable_now` / `full_payment`)
- **Pay using installments or partial payment or permitted spending changes** (`affordable_with_plan`)
- **Wait until a safe future date** (`affordable_later` / `wait`)
- **Do not proceed** (`not_affordable` / `not_recommended`)

A decision is safe **only if**:
1. The user's account balance never drops below `minimum_balance_to_keep` on any day over the next 90 days after all planned payments and projected essential expenses.
2. The full purchase is completed on or before `desired_completion_date`.
3. Intra-day transactions maintain safety (debits always clear before credits).

---

## 2. Architecture

The system enforces a strict boundary between deterministic financial mathematics and AI evidence extraction:

```text
┌─────────────────────────────────────────────────────────────┐
│                    UNTRUSTED EVIDENCE                       │
│  - Document Images (png)        - Financial Messages (csv)  │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
   ┌────────────────────────┐    ┌────────────────────────┐
   │  Gemini Vision (Image) │    │  Gemini Flash (Message)│
   │  Extracts amounts,     │    │  Extracts revisions,   │
   │  dates, doc type       │    │  confirmed salaries    │
   └────────────┬───────────┘    └────────────┬───────────┘
                │                             │
                └──────────────┬──────────────┘
                               │ Structured JSON Facts
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              DETERMINISTIC PYTHON ENGINE                    │
│                                                             │
│  1. Forecast Module (`code/forecast.py`)                   │
│     - 90-day daily cashflow projection                      │
│     - Intra-day debit-before-credit order                   │
│     - Historical salary recurrence suppressed               │
│     - Dated FX rate conversions                             │
│     - Binary-search exact `amount_safe_to_pay`              │
│                                                             │
│  2. Candidate Generator & Decision Engine (`code/plans.py`) │
│     - Candidate 1: Full payment today                       │
│     - Candidate 2: Partial payment (exact 2-part schedule)  │
│     - Candidate 3: Supplied provider installment options    │
│     - Candidate 4: Wait until earliest safe date            │
│     - Candidate 5: Flexible spending change combinations    │
│     - Candidate 6: Fallback (not recommended)               │
│     - Strict hierarchical ranking (contract rules 1 to 6)   │
│     - Grounded, audit-ready explanations                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  EVALUABLE OUTPUT CONTRACT                  │
│       `dataset/output.csv`  &  `output.csv` (250 rows)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Structure

```text
code/
├── main.py              # Main execution entry point (evaluates requests -> output.csv)
├── config.py            # Global paths, environment configuration, and usage tracker
├── data.py              # Dataset loading, validation, and O(1) index builders
├── models.py            # Dataclasses and Pydantic validation schemas
├── forecast.py          # Deterministic 90-day cash forecasting & binary search
├── plans.py             # Candidate generation, ranking rules, and decision engine
├── evidence.py          # Gemini evidence extraction for images and messages with cache
├── evaluation/
│   ├── __init__.py      # Evaluation package marker
│   └── main.py          # Output contract validator and ground-truth sample evaluator
└── usage_report.md      # Final API token and cost summary

tests/
├── test_data.py         # CSV loading, parsing, and indexing tests
├── test_forecast.py     # 90-day simulation, currency conversion, and safety tests
├── test_plans.py        # Candidate generation, ranking, and payment method tests
├── test_evidence.py     # Extraction schemas, prompt injection, and cache tests
└── test_output.py       # Contract schema, row count, and output integrity tests

dataset/                 # Competition dataset files
README.md                # This documentation
requirements.txt         # Minimal production dependencies
.env.example             # Template for API credentials
.gitignore               # Clean exclusions (no caches, logs, or secrets)
```

---

## 4. Setup Instructions

1. **Prerequisites**: Python 3.10+ (tested on Python 3.14).
2. **Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and provide your Gemini API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```

---

## 5. Execution & Entry Points

### Run the Main Pipeline
Evaluates all 250 requests in `dataset/requests.csv` and outputs predictions:
```bash
python code/main.py
```
Output is written to both `dataset/output.csv` and `output.csv`.

### Run the Contract Validator & Sample Evaluator
Validates schema compliance and evaluates predictions against labeled sample requests:
```bash
python code/evaluation/main.py
```

### Run Automated Tests
Runs all unit and regression tests:
```bash
python -m pytest
```

---

## 6. Deterministic Financial Engine

- **Cash Flow Projection**: Simulates exactly 91 daily balances (Day 0 through Day 90).
- **Intra-Day Ordering**: All daily debits clear before any credits on the same calendar date, preventing overdraft hazards.
- **Safety Boundary**: The daily closing balance and intra-day lowest balance must never violate `minimum_balance_to_keep`.
- **Amount Safe To Pay**: Evaluated via binary search in integer cents up to `requested_amount`.
- **Earliest Full Payment Date**: Identifies the first future calendar date where paying `requested_amount` in full preserves the minimum balance for the subsequent 90 days.
- **Spending Adjustments**: Supports up to three `stop:<event_id>` or `reduce_to:<event_id>:<new_amount>` modifications, strictly limited to non-protected categories permitted by the user's profile.

---

## 7. Gemini Evidence Extraction

- **Official SDK**: Utilizes modern `google-genai` (`from google import genai`).
- **Vision Extraction**: Resolves missing event amounts in `dataset/financial_events.csv` via receipts, payslips, and invoices in `dataset/media/images/`.
- **Message Batching**: Processes messages grouped by user context in efficient batches of 10 to minimize API latency and token consumption.
- **Deterministic Disk Caching**: Extracted facts are persisted in `code/extraction_cache/`, ensuring instantaneous, zero-cost, reproducible execution on subsequent runs.
- **Deterministic Calculation Guarantee**: The LLM is strictly confined to parsing text and document images into structured facts. Balance math, cashflow forecasts, candidate generation, and ranking are executed purely in Python.

---

## 8. Safety & Prompt-Injection Defenses

1. **Untrusted Data Boundary**: All message texts and images are treated as untrusted third-party records. System prompts enforce that embedded directives or overrides are completely ignored.
2. **Event ID Integrity**: Pydantic validators reject external reference strings (e.g. `EMP-0001`, `SER-0012`) and require real `event_*` dataset identifiers.
3. **Conservative Income Rule**: Vague salary notices without an explicit numerical amount and settlement date never generate spendable income.
4. **Secret Protection**: `.env`, API keys, session logs (`log.txt`), and temporary caches are strictly excluded via `.gitignore` and never printed to terminal or committed.

---

## 9. Output Format

The solution outputs `dataset/output.csv` (and root `output.csv`) with the exact eight required columns:

| Column | Description | Valid Values |
|---|---|---|
| `request_id` | Identifier matching requests.csv | `request_01` .. `request_250` |
| `amount_safe_to_pay` | Safe payment today before spending changes | Numeric float `[0.0, requested_amount]` |
| `affordability_status` | Classification of request affordability | `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable` |
| `recommended_payment_method` | Selected payment strategy | `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended` |
| `payment_plan` | Chronological schedule of payments | `YYYY-MM-DD:amount\|...` or `none` |
| `earliest_date_for_full_payment` | First safe date for full single payment | ISO `YYYY-MM-DD` or empty |
| `spending_changes_needed` | Required spending modifications | Up to 3 `stop:<event_id>` / `reduce_to:...` or `none` |
| `decision_explanation` | Grounded explanation for user | Concise, professional summary string |

---

## 10. Assumptions & Limitations

- **Fixed Dated FX Rates**: Currency conversions use fixed historical exchange rates from `exchange_rates.csv` on the transaction date.
- **Conservative Recurrence**: Historical salary credits are not assumed to repeat automatically unless confirmed by upcoming scheduled events or verified employer payroll notices.
- **Pending Debits**: Pending debits are reserved immediately; pending credits/bonuses are never credited until settled.
