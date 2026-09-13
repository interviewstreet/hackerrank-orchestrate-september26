# Buy or Wait? - Financial Decision Agent

AI-powered financial decision agent for HackerRank Orchestrate September 2026.

## Overview

This solution analyzes user financial situations and provides personalized recommendations for purchase requests. It considers:

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
- Anthropic API key (optional - for AI-powered mode)

### Installation

1. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set API key (optional for AI mode):**
   ```bash
   export ANTHROPIC_API_KEY='your-api-key-here'
   ```

## Running the Solution

### From repository root:
```bash
python3 main.py
```

### Expected behavior:
- Loads all dataset files from `../dataset/`
- Processes 250 financial requests
- Generates `../output.csv` with predictions
- Creates `evaluation/usage_report.md` with statistics

### Processing modes:

**AI-Powered Mode** (with API key):
- Uses Claude 3.5 Sonnet for comprehensive analysis
- Processing time: ~8-12 minutes
- Cost: ~$10-25
- Higher accuracy

**Rule-Based Mode** (without API key):
- Uses fallback decision engine
- Processing time: ~3 seconds
- Cost: $0
- Good baseline accuracy

## Solution Architecture

### Core Components

1. **Data Loader**
   - Reads CSV files (profiles, events, messages, images, rates, options, requests)
   - Handles date parsing and decimal conversion
   - Links related records via IDs

2. **Context Builder**
   - Assembles comprehensive financial picture per request
   - Extracts amounts from images using Claude Vision (AI mode)
   - Includes 6 months history + future events
   - Filters relevant messages and payment options

3. **Decision Engine**
   - AI Mode: Uses Claude 3.5 Sonnet for analysis
   - Rule-Based Mode: Simple balance-based decisions
   - Forecasts 90-day cash flow
   - Ensures minimum balance protection

4. **Output Formatter**
   - Validates AI/rule responses
   - Formats into required CSV schema
   - Handles fallbacks for errors
   - Tracks token usage

### Decision Logic

The system evaluates each request through:

1. **Cash Flow Analysis**
   - Identify recurring income from patterns
   - Detect recurring expenses (rent, utilities, subscriptions)
   - Account for pending transactions
   - Project 90-day balance trajectory

2. **Safety Checks**
   - Balance must never drop below `minimum_balance_to_keep`
   - Protected categories cannot be reduced/stopped
   - Only flexible expenses can be adjusted
   - Only confirmed income counts

3. **Payment Method Selection**
   
   Priority order:
   1. Complete by desired deadline
   2. Avoid spending changes
   3. Minimize total payment cost
   4. Start payment earlier
   5. Use fewer payments

   **Options:**
   - `full_payment`: Pay entire amount today
   - `partial_payment`: Pay partial now, rest later (if allowed)
   - `installments`: Use offered payment plan
   - `wait`: Full payment safe later
   - `not_recommended`: No safe option

### Output Format

Generates CSV with columns:
1. `request_id`
2. `amount_safe_to_pay` (0 to requested_amount)
3. `affordability_status` (affordable_now | affordable_with_plan | affordable_later | not_affordable)
4. `recommended_payment_method`
5. `payment_plan` (YYYY-MM-DD:amount|YYYY-MM-DD:amount)
6. `earliest_date_for_full_payment`
7. `spending_changes_needed` (stop:event_id | reduce_to:event_id:amount)
8. `decision_explanation`

## File Structure

```
solution/
├── main.py                      # Main solution entry point
├── requirements.txt             # Python dependencies
├── README.md                    # This file
└── evaluation/
    └── usage_report.md          # Token usage and cost report
```

## Key Features

- ✅ Dual-mode support (AI + Rule-based)
- ✅ Comprehensive data processing
- ✅ Multimodal analysis (text + images)
- ✅ 90-day cash flow forecasting
- ✅ Minimum balance protection
- ✅ Payment preference respect
- ✅ Spending adjustment suggestions
- ✅ Graceful error handling
- ✅ Complete validation

## Example Decisions

### Request 1: Affordable Now
```
Request: 25,256 ZAR laptop
Balance: 58,481 ZAR
Minimum: 18,000 ZAR
Available: 40,481 ZAR
→ Full payment recommended
```

### Request 2: Use Installments
```
Request: 46,018,000 IDR trip
Option: 3 × 15,952,907 IDR
→ Installments recommended (spreads cost)
```

### Request 3: Wait
```
Request: 5,491,000 IDR course
Available now: 873,000 IDR
Salary on 15th: +8,000,000 IDR
→ Wait until 15th, then full payment
```

### Request 4: Not Affordable
```
Request: 15,488 ZAR
Available: 737 ZAR
No future income soon
→ Not recommended (would breach minimum)
```

## Technical Details

### Dependencies
- `anthropic==0.39.0` - Claude API client

### Error Handling
- Image extraction fails: Skip, rely on other context
- AI call fails: Fall back to rule-based decision
- Invalid JSON: Log warning, use safe default
- Missing context: Process with available data

### Validation
Post-processing checks:
- amount_safe_to_pay ≤ requested_amount
- Payment plan matches chosen method
- Installments match supplied options
- Spending changes reference flexible events
- All required fields populated

## Token Usage

**With AI Mode:**
- Per request: ~2,000-4,000 input + 200-500 output tokens
- Total (250 requests): ~500K-1M input + 50K-125K output
- Estimated cost: $10-25

**Rule-Based Mode:**
- No API calls
- Cost: $0

Details written to `evaluation/usage_report.md` after each run.

## Improvements

Potential enhancements:
1. Batch processing for efficiency
2. Caching common patterns
3. Hybrid approach (rules for simple, AI for complex)
4. Multi-model comparison
5. Self-verification step
6. Confidence scores
7. Fine-tuning on domain data

## License

HackerRank Orchestrate September 2026 Submission

## Author

Built for HackerRank Orchestrate hackathon challenge.
