# Semantic Analysis of Challenge Specification & Reference Outputs

HackerRank Orchestrate (September 2026) — Buy or Wait?

## 1. Core Financial Semantics & Output Fields

### 1. `amount_safe_to_pay`
- **Definition from Spec**: The largest amount the user can safely pay on `request_date` before optional spending changes, maintaining their minimum balance and covering essential living expenses.
- **Bounds**: Must satisfy $0 \le \text{amount\_safe\_to\_pay} \le \text{requested\_amount}$.
- **Timing & Horizon**: Computed strictly from the **baseline** scenario (before optional spending changes). It represents the immediate cash capacity today that does not breach `minimum_balance_to_keep` throughout the simulation period before the next income replenishment or over the 90-day window.
- **Reference Evidence**:
  - In `request_01`: `start=58,481.10`, `min=18,000`, `headroom=40,481.10`, `req_amt=25,256`. Since $25,256 \le 40,481.10$ and future salary covers all expenses, `amount_safe_to_pay = 25,256`.
  - In `request_04`: `start=52,206,950`, `min=30,686,600`, `gross_headroom=21,520,350`. Between `request_date` (June 4) and next payday (June 15), essential expenses total `13,118,550`. $21,520,350 - 13,118,550 = 8,401,800$. Exactly matching `exp_safe = 8,401,800`.
  - In `request_05`: `start=46,475.10`, `min=13,100`. The user had a terminal payroll ("Final employer payroll"), so no future salary arrives. Over the forecast period to completion deadline, essential expenses leave exactly `737` safe today.

### 2. `affordability_status`
Must be exactly one of:
1. `affordable_now`: The user can safely pay the full `requested_amount` today without any spending changes. (`amount_safe_to_pay == requested_amount`).
2. `affordable_with_plan`: The full request cannot be safely paid today as a lump sum without plan/changes, but CAN be satisfied safely by `desired_completion_date` via:
   - an installment plan from `request_payment_options.csv`, OR
   - a two-part partial payment schedule, OR
   - permitted spending changes (`stop` or `reduce_to`).
3. `affordable_later`: The user cannot safely pay today or with available plans, but WILL safely be able to pay the full amount in a single lump sum on a future date `earliest_date_for_full_payment <= desired_completion_date` (typically after confirmed salary arrives). Recommended method is `wait`.
4. `not_affordable`: No viable option (full, partial, installments, wait, or up to 3 legal spending changes) can complete the request safely by `desired_completion_date` while protecting `minimum_balance_to_keep`.

### 3. `recommended_payment_method`
Must be exactly one of:
- `full_payment`: Recommended when `affordability_status == 'affordable_now'` or when full payment today is enabled after permitted spending changes.
- `partial_payment`: Exactly 2 payments: `amount_safe_to_pay` today, and remainder on `earliest_date_for_full_payment`.
- `installments`: Uses an eligible installment option from `request_payment_options.csv`.
- `wait`: Wait until `earliest_date_for_full_payment` to pay in full.
- `not_recommended`: When `affordability_status == 'not_affordable'`.

### 4. `payment_plan`
- Format: `YYYY-MM-DD:amount|YYYY-MM-DD:amount|...` or `none`.
- For `full_payment`: `<request_date>:<requested_amount>`
- For `partial_payment`: `<request_date>:<amount_safe_to_pay>|<earliest_date_for_full_payment>:<requested_amount - amount_safe_to_pay>`
- For `installments`: Chronological payment dates and installment amounts matching the provider option.
- For `wait`: `<earliest_date_for_full_payment>:<requested_amount>`
- For `not_recommended`: `none`

### 5. `earliest_date_for_full_payment`
- The first date where paying `requested_amount` in full in a single transaction maintains `balance >= minimum_balance_to_keep` throughout the simulation.
- Equals `request_date` for `affordable_now`.
- Equals the wait date for `wait`.
- Empty (`""`) when no full payment is safe within the forecast horizon.
- Computed from baseline capacity before optional spending changes.

### 6. `spending_changes_needed`
- `none` or up to three `stop:<event_id>` and `reduce_to:<event_id>:<new_amount>` actions separated by `|`.
- Must only target recurring, flexible events in categories the user permits and not in protected categories.

---

## 2. Multi-Horizon Financial Safety Model

To prevent conflating different forecasting scopes, the financial engine must explicitly distinguish:
1. **Immediate Headroom Horizon** ($t_0$ to next income event or 30 days): Determines `amount_safe_to_pay` today.
2. **Request Lifecycle Horizon** ($t_0$ to `desired_completion_date`): Determines whether candidate payment plans and wait schedules complete before the user's hard deadline.
3. **Planning Simulation Horizon** ($t_0$ to $t_0 + 90\text{ days}$): Verifies long-term safety so a payment does not trigger an inevitable insolvency later in the quarter.
