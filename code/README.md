# Buy or Wait? - Solution

AI-powered financial decision agent for HackerRank Orchestrate September 2026.

## Overview

This solution uses Claude 3.5 Sonnet to analyze user financial situations and make personalized recommendations for purchase requests. The agent considers:

- Current balance and minimum balance requirements
- Historical spending patterns and recurring expenses
- Pending and confirmed income
- Available payment options (full, partial, installments)
- User payment preferences and financial priorities
- Messages from employers, banks, and service providers
- Image-based financial documents (payslips, statements)

## Setup

### Prerequisites

- Python 3.8 or higher
- Anthropic API key

### Quick Start

From the repository root:

```bash
# One-time setup
./setup.sh

# Set your API key
export ANTHROPIC_API_KEY='your-api-key-here'

# Run the solution
./run.sh
```

### Manual Setup

If you prefer manual setup:

1. Create virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r code/requirements.txt
   ```

3. Set your Anthropic API key:
   ```bash
   export ANTHROPIC_API_KEY='your-api-key-here'
   ```

## Running the Solution

### Option 1: Using the run script (recommended)
```bash
./run.sh
```

### Option 2: Manual run
```bash
source venv/bin/activate
python3 code/main.py
```

This will:
1. Load all dataset files
2. Process each request with AI analysis
3. Generate `output.csv` in the repository root
4. Create `code/evaluation/usage_report.md` with token usage statistics

## How It Works

### 1. Data Loading
Loads all CSV files from `dataset/`:
- `requests.csv` - Requests to evaluate
- `financial_profiles.csv` - User profiles
- `financial_events.csv` - Transaction history
- `messages.csv` - Contextual messages
- `images.csv` - Links to financial documents
- `request_payment_options.csv` - Available payment options
- `exchange_rates.csv` - Currency conversion rates

### 2. Context Building
For each request, builds comprehensive financial context:
- User profile (balance, preferences, priorities)
- Recent financial events (6 months history + future)
- Relevant messages (from employers, banks, merchants)
- Related images (extracts amounts using Claude Vision)
- Available payment options

### 3. AI Analysis
Uses Claude 3.5 Sonnet to:
- Identify recurring income and expenses
- Forecast 90-day cash flow
- Evaluate payment safety
- Recommend optimal payment method
- Suggest spending adjustments if needed

### 4. Output Generation
Produces structured predictions with:
- `amount_safe_to_pay` - Maximum safe amount today
- `affordability_status` - Overall affordability
- `recommended_payment_method` - Best payment approach
- `payment_plan` - Detailed payment schedule
- `earliest_date_for_full_payment` - When full payment becomes safe
- `spending_changes_needed` - Required adjustments
- `decision_explanation` - Reasoning

## Architecture Decisions

### Why Claude 3.5 Sonnet?

1. **Multimodal Capabilities**: Can process both text and images for extracting amounts from financial documents
2. **Large Context Window**: Can analyze comprehensive financial history in a single call
3. **Reasoning Ability**: Excellent at understanding complex financial relationships and making nuanced decisions
4. **Structured Output**: Reliable JSON formatting for consistent predictions

### Approach

- **Single-pass Processing**: Each request analyzed independently with full context
- **Vision for OCR**: Extract amounts from images where needed
- **Deterministic Prompting**: Temperature=0 for consistent decisions
- **Comprehensive Context**: Include all relevant data in prompt rather than complex pre-processing

### Trade-offs

**Pros:**
- High accuracy through comprehensive analysis
- Handles edge cases and nuanced situations well
- Minimal pre-processing code
- Easy to iterate and improve prompts

**Cons:**
- Higher token usage per request
- Requires API key and internet connection
- Processing time proportional to dataset size

## Token Usage

The solution tracks:
- Total input/output tokens
- Average tokens per request
- Estimated cost

See `code/evaluation/usage_report.md` after running for detailed statistics.

## Output Format

`output.csv` contains exactly one row per request with columns:
1. `request_id`
2. `amount_safe_to_pay`
3. `affordability_status`
4. `recommended_payment_method`
5. `payment_plan`
6. `earliest_date_for_full_payment`
7. `spending_changes_needed`
8. `decision_explanation`

## Error Handling

- Falls back to safe defaults if context building fails
- Returns `not_recommended` if AI analysis fails
- Logs errors to stderr
- Continues processing remaining requests on individual failures

## Future Improvements

Potential enhancements:
1. Batch processing for better token efficiency
2. Caching common patterns
3. Hybrid approach: rules for simple cases, AI for complex ones
4. Multi-model comparison
5. Self-verification step
6. Fine-tuning on domain-specific patterns
