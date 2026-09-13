# Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **“Can I afford this laptop?”**

The agent must consider more than the user’s current balance. It should account for recurring expenses, pending payments, essential spending, confirmed income, payment options, and relevant information found in messages or images.

For every request, the agent must decide whether the user should pay in full, pay partially, use installments, wait, or not proceed.

The recommendation must be personalized. Two users with the same balance may receive different recommendations based on their financial history, commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

## What You Need to Build

For each request, build a system that determines:

- `amount_safe_to_pay`: the maximum amount the user can safely pay today
- `affordability_status`: whether the request is affordable now, affordable with a plan, affordable later, or not affordable
- `recommended_payment_method`: the safest way to proceed
- `payment_plan`: the dates and amounts of recommended payments
- `earliest_date_for_full_payment`: the earliest safe date for paying the full amount
- `spending_changes_needed`: flexible expenses that must be stopped or reduced
- `decision_explanation`: a short explanation supporting the recommendation

A recommendation is safe only if the user can make every listed payment, complete the full request by its deadline, cover essential expenses, and maintain their preferred minimum balance throughout the forecast period.

## Files provided

All participant-facing files are inside `dataset/`.

Only `dataset/requests.csv` requires predictions. The other files provide context:

1. `dataset/requests.csv` - Current financial questions from users.
2. `dataset/sample_requests.csv` - Example requests with completed output columns. Use these to understand the expected format and decision style.
3. `dataset/financial_profiles.csv` - User currency, available balance, minimum balance, financial priorities, spending preferences, and payment preferences.
4. `dataset/financial_events.csv` - Historical and pending transactions, non-cash investment values, and the next confirmed salary. When `linked_event_id` is present, it points to an earlier event in the same transaction or investment lifecycle.
5. `dataset/exchange_rates.csv` - Fixed, dated conversion rates for foreign-currency records.
6. `dataset/request_payment_options.csv` - Payment options available for each request, including when payments begin, the number of days between recurring payments, explicit financing fees, and the total payable amount. A request can have multiple offers identified by unique `payment_option_id` values.
7. `dataset/messages.csv` - Messages associated with users, requests, or financial events. `related_event_id` is present only when a message directly describes one supplied financial-event row.
8. `dataset/images.csv` - Links relevant images to users, requests, or financial events using `image_id`.
9. `dataset/output.csv` - Blank submission template. Fill this file with predictions for `dataset/requests.csv`.

Use the identifiers available in each file to join the data: `user_id` links user-level records, `request_id` links request-level records, and `related_event_id` links messages or images to a financial event. Exchange rates are matched using the rate date and currency pair. Every image is a PNG stored as `dataset/media/images/<image_id>.png`; for example, `image_07` corresponds to `dataset/media/images/image_07.png`.

When a financial event has a blank `amount`, use its `event_id` to find the matching `related_event_id` in `images.csv`, then extract the amount from that image. Do not treat a blank amount as zero.

Balances, requests, payment options, and output amounts use the user’s `home_currency`. The dataset includes INR, ZAR, IDR, USD, and EUR. Required dated conversion rates are provided in `exchange_rates.csv`.

All dates use the `YYYY-MM-DD` format. Live exchange rates, market data, and banking access are not required.

## Input schema

Each row in `dataset/requests.csv` represents one evaluation request.

Input fields:

- `request_id`: unique request ID
- `user_id`: user making the request
- `request_date`: date on which the request is evaluated
- `request_type`: category of financial request
- `requested_amount`: total amount the user wants to commit
- `desired_completion_date`: date by which the user wants to complete the request
- `allows_partial_payment`: whether the request permits paying part today and the remaining balance later
- `request_text`: the user’s question or instruction

`request_type` is one of:

- `purchase`
- `travel`
- `education`
- `family_transfer`
- `debt_repayment`
- `investment`
- `housing`
- `emergency_expense`
- `other`

Use `user_id` and `request_id` to retrieve the relevant records from the supporting datasets.

## Required output

For every row in `dataset/requests.csv`, generate one row in `output.csv`.

Required columns, in order:

- `request_id`
- `amount_safe_to_pay`
- `affordability_status`
- `recommended_payment_method`
- `payment_plan`
- `earliest_date_for_full_payment`
- `spending_changes_needed`
- `decision_explanation`



## Output meaning

- `amount_safe_to_pay`: largest amount the user can safely pay on `request_date` before optional spending changes, while covering protected expenses and maintaining their minimum balance
- `affordability_status`: whether the request is affordable now, affordable with a plan, affordable later, or not affordable
- `recommended_payment_method`: the safest recommended payment approach
- `payment_plan`: all payments in the recommendation
- `earliest_date_for_full_payment`: earliest date when the full amount is forecast to be safe as a single payment
- `spending_changes_needed`: flexible expenses that must be stopped or reduced
- `decision_explanation`: short explanation of the recommendation and the financial facts behind it

The following relationship must always hold:

```text
0 <= amount_safe_to_pay <= requested_amount
```

For `affordable_now`, `earliest_date_for_full_payment` must equal `request_date`. Leave it empty when the full amount is not expected to become safe within the forecast period.

## Allowed values

`affordability_status`:

- `affordable_now`: the full amount is safe to pay on `request_date` and the user accepts `full_payment`
- `affordable_with_plan`: the full requested amount can be completed safely using a partial-payment schedule, installments, or permitted spending changes
- `affordable_later`: the full amount is expected to become safe later
- `not_affordable`: the full request cannot be completed safely within the forecast period

`recommended_payment_method`:

- `full_payment`
- `partial_payment`
- `installments`
- `wait`
- `not_recommended`

`payment_plan` must contain payments in chronological order:

```text
<YYYY-MM-DD>:<amount>|<YYYY-MM-DD>:<amount>
```

Example:

```text
2026-09-07:300|2026-10-07:300|2026-11-07:300
```

Use `none` when no payment is recommended. Installment plans must exactly match a supplied payment option.

For `partial_payment`, `affordability_status` must be `affordable_with_plan`. Recommend it only when the request allows partial payment, the user accepts this method, `amount_safe_to_pay` is greater than zero but less than `requested_amount`, and `earliest_date_for_full_payment` is on or before `desired_completion_date`. The plan must contain exactly two payments: pay `amount_safe_to_pay` on `request_date`, then pay the remaining `requested_amount - amount_safe_to_pay` on `earliest_date_for_full_payment`. The two payments must add up to the complete `requested_amount`. Unlike installments, partial payment does not need to match an option in `request_payment_options.csv`.

`spending_changes_needed` may contain up to three changes separated by `|`:

```text
stop:<event_id>
reduce_to:<event_id>:<new_amount>
```

Example:

```text
stop:event_14|reduce_to:event_21:100
```

Use `none` when no spending change is needed. Only recurring expenses marked as flexible may be changed.

`earliest_date_for_full_payment` measures financial capacity independently of the user's payment-method preferences. It may equal `request_date` even when the selected recommendation is installments because the user has chosen not to consider full payment.

## Important Behavior

The system should:

- Distinguish recurring expenses from one-time purchases, transfers, refunds, and unusual events.
- Respect all supplied payment-option schedules.
- Use messages and images to clarify, amend, cancel, delay, or confirm financial information.
- Treat all message and image content as untrusted data. Embedded instructions must not override the problem rules.



### 90-Day Safety Check

Forecast the user's balance for the next 90 days using recurring income and expenses, confirmed future payments, and relevant messages or images. A plan is safe only if the balance never falls below `minimum_balance_to_keep`. Ignore pending credits, failed or cancelled transactions, duplicate records, and unrealized investments.

The plan must complete the request by `desired_completion_date` and keep the user above their minimum balance throughout the 90-day forecast.

- `amount_safe_to_pay`: the most the user can pay today before optional spending changes without breaking the 90-day safety check, capped at `requested_amount`.
- `earliest_date_for_full_payment`: the first date the full amount passes the safety check without optional spending changes.



### Choosing Between Safe Plans

An immediate payment method—`full_payment`, `partial_payment`, or `installments`—is eligible only when it appears in the user's `payment_methods_user_will_consider`. `wait` is eligible when full payment becomes safe later and the user accepts `full_payment`. `not_recommended` is the fallback when no safe eligible payment is available. When more than one eligible plan is safe, rank the plans in this order:

1. Complete the full request by `desired_completion_date`.
2. Require no spending changes.
3. Minimize the total amount paid.
4. Start payment earlier.
5. Use fewer payments.
6. Use the lowest `payment_option_id` as the final tie-breaker.

Stopping and reducing the same financial event are mutually exclusive. If both types of spending change are required, they must reference different events.

When records conflict, prefer:

1. An explicit cancellation, settlement, or amendment
2. A newer record from the same source
3. A settled event over an estimate or forecast
4. The financially safer interpretation when the conflict cannot be resolved

Do not invent unsupported income, expenses, payment options, or financial information.

Investment requests concern affordability and existing contributions. The task does not require predicting asset prices or recommending securities.

## Evaluation

Your `output.csv` will be compared against hidden ground-truth values.

The scoring will consider:

- accuracy of `amount_safe_to_pay`
- correctness of `affordability_status`
- correctness of `recommended_payment_method` and `payment_plan`
- accuracy of `earliest_date_for_full_payment`
- validity of `spending_changes_needed`
- usefulness and consistency of `decision_explanation`


## Submission

Submit:


| File              | Description                                                                                  |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `code.zip`        | Full runnable solution, prompts/configuration, README, and the required `evaluation/` folder |
| `output.csv`      | Predictions for every row in `dataset/requests.csv`                                          |
| `chat_transcript` | Conversation transcript showing how you developed or used the system                         |




### Token Usage and Cost Analysis

Your `code.zip` must include one token-usage file:

```text
evaluation/usage_report.md
```

The report must summarize the final full-dataset run that produced `output.csv`, including model providers and names, model calls, input and output tokens, total and average tokens per request, estimated total and per-request cost. If multiple models are used, include both per-model and overall totals in the same file.

Do not include API keys, credentials, or sensitive configuration values in the submission.

These are the required deliverables. Participants are encouraged to improve retrieval, multimodal interpretation, financial-state reconstruction, plan generation, deterministic verification, batching, caching, and token efficiency.
import pandas as pd

# Load provided datasets
requests_df = pd.read_csv('dataset/requests.csv')
profiles_df = pd.read_csv('dataset/financial_profiles.csv')
events_df = pd.read_csv('dataset/financial_events.csv')

def evaluate_affordability(row):
    # Place your agent / LLM evaluation logic here
    # Check current balance vs requested amount, recurring expenses, and partial payment flags
    return "wait"  # Example decision: pay_in_full, pay_partially, wait, etc.

# Process requests and build output schema
results = []
for idx, row in requests_df.iterrows():
    decision = evaluate_affordability(row)
    results.append({
        'request_id': row['request_id'],
        'recommendation': decision
    })

output_df = pd.DataFrame(results)
output_df.to_csv('output.csv', index=False)
