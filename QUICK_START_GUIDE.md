# Quick Start Guide - Buy or Wait?

## 🚀 Get Started in 3 Steps

### Step 1: Setup (One-time)
```bash
./setup.sh
```
This creates a Python virtual environment and installs dependencies.

### Step 2: Set API Key
```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```
Get your API key from: https://console.anthropic.com/

### Step 3: Run
```bash
./run.sh
```
This processes all 250 requests and generates `output.csv`.

---

## 📋 What Happens When You Run?

1. **Loads Data** (5 seconds)
   - 250 requests from `dataset/requests.csv`
   - User profiles, financial events, messages, images
   - Payment options and exchange rates

2. **Processes Each Request** (~8-12 minutes total)
   - Builds financial context for user
   - Extracts amounts from images if needed
   - Analyzes with AI (2-3 seconds per request)
   - Generates recommendation

3. **Creates Output**
   - `output.csv` - All 250 predictions
   - `code/evaluation/usage_report.md` - Token usage stats

---

## 📊 Output Format

`output.csv` contains:
- `request_id` - Which request this answers
- `amount_safe_to_pay` - Max safe amount today (0 to requested_amount)
- `affordability_status` - affordable_now | affordable_with_plan | affordable_later | not_affordable
- `recommended_payment_method` - full_payment | partial_payment | installments | wait | not_recommended
- `payment_plan` - Date:amount pairs (e.g., "2024-03-03:25256" or "2024-03-03:15000|2024-03-15:10000")
- `earliest_date_for_full_payment` - First safe date for full payment (YYYY-MM-DD or empty)
- `spending_changes_needed` - Actions like "stop:event_14" or "reduce_to:event_21:100" (max 3, or "none")
- `decision_explanation` - Human-readable reasoning

---

## ✅ Validation

Check your output:
```bash
python3 validate_output.py
```

This verifies:
- Correct number of rows (250)
- Required columns in correct order
- amount_safe_to_pay ≤ requested_amount
- Valid status and method values
- Consistent affordability_status and earliest_date

---

## 📦 Create Submission Package

```bash
./create_submission.sh
```

This creates `code.zip` and verifies you have:
1. ✅ `code.zip` - Complete solution
2. ✅ `output.csv` - Predictions
3. ✅ `log.txt` - Chat transcript

---

## 🎯 Submit

Go to: https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

Upload:
1. `code.zip`
2. `output.csv`
3. `log.txt`

---

## 💡 How It Works

### The AI Decision Process

For each request, the system:

1. **Gathers Context**
   - User's current balance and minimum balance requirement
   - Last 6 months of transactions (to detect patterns)
   - Pending and future confirmed payments
   - User's payment preferences and priorities
   - Messages (salary updates, payment delays, etc.)
   - Images (for missing amounts)
   - Available payment options

2. **Forecasts 90 Days**
   - Identifies recurring income (salary patterns)
   - Identifies recurring expenses (rent, utilities, subscriptions)
   - Projects balance at each future date
   - Ensures balance stays above minimum

3. **Evaluates Options**
   - **Full payment**: Can pay entire amount today?
   - **Partial payment**: Pay some now, rest later? (only if allowed)
   - **Installments**: Which installment plan works? (must match offered options)
   - **Wait**: Will full payment be safe soon?
   - **Not recommended**: No safe option exists

4. **Considers Adjustments**
   - Can we stop a stoppable subscription?
   - Can we reduce flexible spending?
   - Only suggests changes user is willing to make

5. **Chooses Best Option**
   Priority:
   1. Completes by desired deadline
   2. Avoids spending changes
   3. Minimizes total cost
   4. Starts payment earlier
   5. Uses fewer payments

### Why Claude 3.5 Sonnet?

- **Smart reasoning**: Understands complex financial relationships
- **Vision capability**: Extracts amounts from images
- **Large context**: Fits full financial history in one call
- **Reliable output**: Consistent JSON formatting

---

## 📈 Expected Performance

### Token Usage
- Per request: ~2,000-4,000 input + 200-500 output tokens
- Total: ~500K-1M input + 50K-125K output tokens
- Cost: ~$10-25 for full run

### Processing Time
- ~2-3 seconds per request
- Total: ~8-12 minutes for 250 requests

### Accuracy
The AI analyzes:
- ✅ Balance trends
- ✅ Recurring patterns
- ✅ Payment deadlines
- ✅ User preferences
- ✅ Minimum balance safety
- ✅ Message updates
- ✅ Payment option costs

---

## 🔍 Troubleshooting

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY='sk-ant-...'
```

### "Virtual environment not found"
```bash
./setup.sh
```

### "Cannot extract amount from image"
- Check image file exists in `dataset/media/images/`
- Solution continues with available data

### "Invalid JSON from AI"
- Rare occurrence
- Solution falls back to safe default (not_recommended)
- Continues with remaining requests

### Validation errors
```bash
python3 validate_output.py
```
Shows specific issues to fix.

---

## 📚 Documentation

- `README.md` - Repository overview
- `problem_statement.md` - Full challenge specification
- `code/README.md` - Solution architecture details
- `SOLUTION_OVERVIEW.md` - Design decisions and rationale
- `AGENTS.md` - AI assistant instructions (for chat transcript)

---

## 🎓 Understanding the Decision Logic

### Example 1: Affordable Now
- Balance: 58,481 ZAR
- Request: 25,256 ZAR laptop
- Minimum: 18,000 ZAR
- Decision: **Full payment** (58,481 - 25,256 = 33,225 > 18,000 ✓)

### Example 2: Affordable With Plan
- Balance: 60,383,889 IDR
- Request: 46,018,000 IDR trip
- Option: 3 installments of 15,952,907 IDR
- Decision: **Installments** (spreads cost, stays above minimum)

### Example 3: Affordable Later
- Balance: 5,810,300 IDR
- Request: 5,491,000 IDR
- Minimum: 2,668,700 IDR
- Salary on 15th: +8,000,000 IDR
- Decision: **Wait until 15th** (then balance = 13,810,300 - 5,491,000 = 8,319,300 > minimum ✓)

### Example 4: Not Affordable
- Balance: 46,475 ZAR
- Request: 15,488 ZAR
- Minimum: 13,100 ZAR
- No future income soon enough
- Decision: **Not recommended** (would break minimum balance requirement)

---

## ⏰ Time Remaining

**Challenge Ends**: September 13, 2026 at 6:00 PM IST

Check time remaining:
```bash
python3 -c "from datetime import datetime; import pytz; end=datetime(2026,9,13,18,0,tzinfo=pytz.timezone('Asia/Kolkata')); now=datetime.now(pytz.timezone('Asia/Kolkata')); print(f'Time left: {end-now}')"
```

---

## 💪 Tips for Success

1. **Test on samples first**: Check against `dataset/sample_requests.csv` (25 solved examples)
2. **Validate output**: Run `validate_output.py` before submitting
3. **Check token usage**: Review `code/evaluation/usage_report.md` after running
4. **Review edge cases**: Zero balances, conflicting messages, no income users
5. **Read messages carefully**: They can cancel, delay, or confirm events

---

## 🏆 Submission Checklist

- [ ] Run `./run.sh` successfully
- [ ] `output.csv` has 250 rows (+ header)
- [ ] Run `python3 validate_output.py` - no errors
- [ ] Check `code/evaluation/usage_report.md` exists
- [ ] Run `./create_submission.sh`
- [ ] Have `code.zip`, `output.csv`, and `log.txt` ready
- [ ] Submit at: https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

Good luck! 🎉
