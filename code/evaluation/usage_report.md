# Model Usage Report

The final full-dataset run generated `output.csv` for 250 requests using the
deterministic Python implementation in `code/main.py`.

| Metric | Total | Average per request |
|---|---:|---:|
| Model calls | 0 | 0 |
| Input tokens | 0 | 0 |
| Output tokens | 0 | 0 |
| Total tokens | 0 | 0 |
| Estimated cost (USD) | $0.00 | $0.00 |

No model provider or model was used. The solution uses local CSV data,
deterministic rules, and Python's standard library; therefore token usage and
model cost are zero.

## Validation

The generated file passed checks for all 250 evaluation requests, the required
column order, allowed values, amount bounds, deadlines, and installment-option
matching. On the 25 public solved examples, 19 recommendations matched the
expected affordability status and 19 matched the expected payment method;
3 safe-payment amounts were within one cent of the examples. These public
examples show that the deterministic forecast remains approximate and should
not be interpreted as a guarantee of hidden-set accuracy.