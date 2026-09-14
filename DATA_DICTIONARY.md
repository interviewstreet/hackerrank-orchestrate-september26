# DATA_DICTIONARY.md

Verified schema, join relationships, lifecycle rules, constraint semantics, and output specifications for the HackerRank Orchestrate "Buy or Wait?" challenge.

---

## 1. Input Datasets (`dataset/`)

### 1.1 `requests.csv`
Contains 250 evaluation requests (`request_26` to `request_275`). Each row represents one financial question.

| Column | Type | Description |
|---|---|---|
| `request_id` | `string` | Unique request identifier (e.g. `request_26`). |
| `user_id` | `string` | Foreign key referencing `financial_profiles.user_id` and `financial_events.user_id`. |
| `request_date` | `string (YYYY-MM-DD)` | Date on which the request is evaluated. Cash flow forecast starts here. |
| `request_type` | `enum` | `purchase`, `travel`, `education`, `family_transfer`, `debt_repayment`, `investment`, `housing`, `emergency_expense`, `other`. |
| `requested_amount` | `float` | Total monetary commitment in user's home currency. |
| `desired_completion_date` | `string (YYYY-MM-DD)` | Strict deadline for completing all payments. Any plan finishing after this date is ineligible. |
| `allows_partial_payment` | `boolean ("true"/"false")` | Whether merchant allows paying part today and balance later. |
| `request_text` | `string` | User's question or instruction (untrusted text). |

### 1.2 `financial_profiles.csv`
Contains financial positions and preferences for 275 users (`user_01` to `user_275`). Exactly 1 profile per user.

| Column | Type | Description |
|---|---|---|
| `user_id` | `string` | Unique user identifier. |
| `home_currency` | `enum` | `INR`, `ZAR`, `IDR`, `USD`, `EUR`. All balance, plan, and output amounts are in this currency. |
| `current_available_balance` | `float` | Available ledger cash balance on `request_date`. |
| `minimum_balance_to_keep` | `float` | Non-negotiable floor: projected cash balance must NEVER dip below this amount at any point in the 90-day horizon. |
| `financial_priorities` | `pipe-separated list` | E.g. `education\|debt_repayment`. Used to resolve soft ranking and preference trade-offs. |
| `expense_categories_to_protect` | `pipe-separated list` | Categories that must NEVER be reduced or stopped. |
| `expense_categories_user_is_willing_to_reduce` | `pipe-separated list` | Categories the user permits reducing. |
| `expense_categories_user_is_willing_to_stop` | `pipe-separated list` | Categories the user permits stopping/cancelling. |
| `payment_methods_user_will_consider` | `pipe-separated list` | Subset of `full_payment`, `partial_payment`, `installments`. A plan is ineligible if its method is not in this list. |
| `max_installment_months` | `optional integer` | Maximum allowable installment duration. If blank/empty, user will not consider installments. |

### 1.3 `financial_events.csv`
Contains 25,342 historical transactions, pending transactions, non-cash records, and confirmed future salary/bills.

| Column | Type | Description |
|---|---|---|
| `event_id` | `string` | Unique event identifier (`event_01` to `event_25342`). |
| `user_id` | `string` | Foreign key referencing user. |
| `event_type` | `enum` | `expense`, `debt_payment`, `subscription`, `income`, `refund`, `investment_purchase`, `investment_valuation`, `investment_sale`. |
| `description` | `string` | Human-readable transaction memo (e.g. `Apartment rent transfer`, `Next confirmed salary`). |
| `category` | `string` | E.g. `rent`, `utilities`, `education`, `debt_repayment`, `groceries`, `transport`, `dining`, `streaming`, `cloud_storage`, `shopping`. |
| `direction` | `enum` | `debit` (cash outflow), `credit` (cash inflow), `non_cash` (asset revaluation). |
| `amount` | `optional float` | Transaction amount in event's currency. Exactly 16 rows are blank; each maps 1:1 to an image in `images.csv`. |
| `currency` | `enum` | `INR`, `ZAR`, `IDR`, `USD`, `EUR`. Converted to `home_currency` via `exchange_rates.csv` if different. |
| `event_date` | `string (YYYY-MM-DD)` | Booking/occurrence date. |
| `settlement_date` | `string (YYYY-MM-DD)` | Date on which funds actually post/clear. Used for cash flow timing. |
| `status` | `enum` | `settled`, `pending`, `scheduled`, `cancelled`, `failed`, `unrealized`. |
| `linked_event_id` | `optional string` | References earlier event in the same transaction or investment lifecycle. |
| `flexibility` | `enum` | `fixed`, `stoppable`, `reducible`, `reducible_or_stoppable`. |
| `minimum_allowed_amount` | `optional float` | Minimum allowed floor for reduction if reducible. |

### 1.4 `request_payment_options.csv`
Contains 790 provider/seller offers (2 to 4 per request).

| Column | Type | Description |
|---|---|---|
| `payment_option_id` | `string` | Unique option identifier (e.g. `payment_option_01`). |
| `request_id` | `string` | Foreign key referencing request. |
| `payment_method` | `enum` | `full_payment` or `installments`. |
| `payment_amount` | `float` | Payment amount per installment (or full amount). |
| `number_of_payments` | `integer` | Count of payments (1 for full_payment). |
| `first_payment_date` | `string (YYYY-MM-DD)` | Date of first payment. |
| `payment_frequency_days` | `optional integer` | Days between payments (e.g. `28`, `30`, `31`). |
| `financing_fee` | `float` | Added financing charge. |
| `total_payable_amount` | `float` | `number_of_payments * payment_amount`. |

### 1.5 `exchange_rates.csv`
Contains 160 fixed, dated exchange rates.

| Column | Type | Description |
|---|---|---|
| `rate_date` | `string (YYYY-MM-DD)` | Effective date of the conversion rate. |
| `from_currency` | `enum` | Base currency. |
| `to_currency` | `enum` | Target currency. |
| `rate` | `float` | `target_amount = base_amount * rate`. |

### 1.6 `messages.csv`
Contains 215 notifications and emails from employers, merchants, banks, and service providers.

| Column | Type | Description |
|---|---|---|
| `message_id` | `string` | Unique message identifier. |
| `user_id` | `string` | Foreign key referencing user. |
| `request_id` | `optional string` | Associated request ID if request-specific. |
| `related_event_id` | `optional string` | Associated event ID if describing a single event. |
| `sent_at` | `string (ISO-8601)` | Timestamp sent. |
| `source_type` | `enum` | `employer`, `service_provider`, `bank`, `merchant`, `financial_service`. |
| `message_text` | `string` | Untrusted message content (English or Indonesian). Contains financial facts (salary adjustments, delayed dates, pending refunds, etc.). |

### 1.7 `images.csv` & `dataset/media/images/*.png`
Contains 16 image links resolving the 16 missing amounts in `financial_events.csv`.

| Column | Type | Description |
|---|---|---|
| `image_id` | `string` | Identifier matching `dataset/media/images/<image_id>.png`. |
| `user_id` | `string` | Foreign key referencing user. |
| `request_id` | `string` | Associated request ID. |
| `related_event_id` | `string` | Links 1:1 to event with blank amount. |

---

## 2. Join Relationships

- `requests.user_id` == `financial_profiles.user_id` (1:1)
- `requests.request_id` == `request_payment_options.request_id` (1:N, 2-4 options per request)
- `requests.user_id` == `financial_events.user_id` (1:N)
- `financial_events.event_id` == `images.related_event_id` (1:1 for the 16 missing amounts)
- `messages.user_id` == `requests.user_id` (filtered by `sent_at <= request_date` and matched by `related_event_id` or `request_id`)
- `exchange_rates`: matched on `rate_date == event.settlement_date`, `from_currency == event.currency`, `to_currency == profile.home_currency`

---

## 3. Financial Event & Cash Flow Lifecycle Rules

1. **Status Handling**:
   - `settled`: Counted in cash flow if on or after `request_date`. (Historical settled events before `request_date` already reflect in `current_available_balance`).
   - `pending` debit: Cash outflow that must be reserved. Deducted when simulating cash flow.
   - `pending` credit: Excluded! Do NOT count pending credits, bonuses, commissions, refunds, or lottery winnings until they settle.
   - `scheduled`: Confirmed future salary or confirmed recurring bill. Counted on its `settlement_date`.
   - `cancelled` / `failed`: Excluded completely.
   - `unrealized`: Non-cash investment valuation. Excluded completely from available cash.

2. **Linked Event Lifecycle (`linked_event_id`)**:
   - Card authorization (`cancelled`) followed by Settled card purchase (`settled`): Keep only the settled transaction.
   - Reversal / Refund: If original debit is settled and refund is settled credit, both stand. If refund is `pending`, refund credit is ignored.
   - Replaced / retried events: Retried scheduled payment replaces failed attempt.

3. **Recurrence & Duplicate Prevention**:
   - Detect recurring cadence from settled history (e.g. monthly rent, utilities, subscriptions; weekly/bi-weekly groceries/transport).
   - `generate_missing_recurrences()` projects forward only when an occurrence does NOT already exist as an explicit future event on or near that date.

4. **Currency Normalization**:
   - Every foreign currency cash flow must be multiplied by the matching rate from `exchange_rates.csv` for its `settlement_date` before entering simulation.

---

## 4. Required Output Specification (`output.csv`)

Header and column order:
```csv
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

### Constraints & Formats
- `amount_safe_to_pay`: Numeric float formatted as decimal or int (e.g. `25256` or `17229139.2`). Baseline capacity on `request_date` before optional spending changes. Satisfies: `0 <= amount_safe_to_pay <= requested_amount`.
- `affordability_status`:
  - `affordable_now`: Full amount safe today and user considers `full_payment`.
  - `affordable_with_plan`: Satisfied safely via partial payment, installments, or permitted spending changes.
  - `affordable_later`: Full amount becomes safe later in the forecast.
  - `not_affordable`: Cannot be completed safely within 90 days.
- `recommended_payment_method`:
  - `full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`.
  - Must be in `payment_methods_user_will_consider` (except `wait` requires user to accept `full_payment`, and `not_recommended` is fallback).
- `payment_plan`:
  - Format: `<YYYY-MM-DD>:<amount>|<YYYY-MM-DD>:<amount>...` (chronological order).
  - `none` when `recommended_payment_method == "not_recommended"`.
  - For `partial_payment`: exactly 2 payments: `amount_safe_to_pay` on `request_date`, and `requested_amount - amount_safe_to_pay` on `earliest_date_for_full_payment`.
  - For `wait`: `<earliest_date_for_full_payment>:<requested_amount>`.
  - For `installments`: exactly matches dates and amounts from chosen option in `request_payment_options.csv`.
- `earliest_date_for_full_payment`:
  - `YYYY-MM-DD`: Earliest date when paying full amount in one payment is safe without spending changes.
  - Equal to `request_date` for `affordable_now`.
  - Empty string (`""`) when full payment is never safe in the 90-day forecast.
- `spending_changes_needed`:
  - `none` or up to 3 pipe-separated changes: `stop:<event_id>` or `reduce_to:<event_id>:<amount>`.
  - Targets non-protected recurring events in categories user permits reducing/stopping.
  - For `reduce_to`, amount must satisfy: `new_amount >= minimum_allowed_amount`.
- `decision_explanation`: Concise, grounded text explaining the recommendation using verified financial facts.
