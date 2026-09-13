"""Tunable constants for the deterministic financial core.

Every threshold the engine uses lives here with the reason it holds that value.
Nothing else in `buy_or_wait/` may contain a bare number that changes behaviour.

Values marked CALIBRATED were chosen by `code/evaluation/calibrate.py` against the
**development** subset only (`code/evaluation/splits.py`); the reporting subset is
never used to pick a constant.
"""
from __future__ import annotations

from decimal import Decimal

# --- Forecast window --------------------------------------------------------

#: `problem_statement.md` "90-Day Safety Check". The window is inclusive of the
#: request date and runs to request_date + 90 days.
FORECAST_DAYS = 90

# --- Recurrence detection ---------------------------------------------------

#: A series must repeat at least this many times in history before we project it
#: forward. Two occurrences cannot distinguish a recurring charge from a
#: coincidence, and inventing a recurring expense is as wrong as missing one.
RECURRENCE_MIN_OCCURRENCES = 3

#: Gaps outside this range are not treated as a regular cadence. The dataset's
#: recurring items are weekly (7), fortnightly (14) or monthly (28-31).
RECURRENCE_MIN_PERIOD_DAYS = 5
RECURRENCE_MAX_PERIOD_DAYS = 40

#: A series whose observed gaps vary by more than this fraction of the median is
#: treated as irregular: we still project it, but at its median gap, because an
#: irregular essential expense is still an expense.
RECURRENCE_IRREGULAR_TOLERANCE = Decimal("0.5")

#: Only history within this many days before the request informs recurrence.
#: Every user has ~177 days of history, so this keeps roughly the last two
#: thirds -- recent enough to reflect the current cost of living, long enough to
#: see three monthly occurrences.
RECURRENCE_LOOKBACK_DAYS = 120

# --- Conservatism -----------------------------------------------------------

#: Income needs fewer observations than spending to establish a cadence: income
#: records are few, large and regular, and requiring three would refuse to
#: forecast any salary for a recently-started job (`user_01` has exactly two
#: salary records, under two different descriptions).
INCOME_MIN_OCCURRENCES = 2

#: How a projected recurring CREDIT (income) amount is chosen.
#: "latest" = the current pay rate, which is what a raise, a cut or a prorated
#: first month should leave behind. "min" is available and is strictly more
#: cautious, but on a prorated first salary it forecasts a rate the user no
#: longer earns. CALIBRATED on the development split only.
PROJECTED_CREDIT_AMOUNT_POLICY = "latest"

#: Categories excluded from the *projected* recurring debit reservation.
#: `problem_statement.md` defines safety as covering **essential** expenses; a
#: recurring investment contribution is the user moving money into savings, not
#: an obligation that must be met. Confirmed future investment debits are still
#: reserved -- this only affects what we project forward from history.
#: CALIBRATED on the development split: see docs/IMPLEMENTATION_STATUS.md M1.
PROJECTED_DEBIT_EXCLUDED_CATEGORIES = frozenset({"investment"})

#: Income is only projected forward when history supports a regular cadence.
#: When False, only explicitly scheduled/confirmed income counts -- which the
#: 25 solved examples contradict (see IMPLEMENTATION_STATUS M1, hypothesis H1).
PROJECT_RECURRING_INCOME = True

# --- Intra-day ordering -----------------------------------------------------

#: Within one date: existing debits, then credits, then any proposed payment.
#: Existing obligations first is the conservative reading (the user does not
#: control when a direct debit clears). A proposed payment goes last because the
#: user does choose when to pay, and the solved examples confirm it -- their
#: `earliest_date_for_full_payment` is repeatedly the salary date itself, which
#: is only reachable if a payment may follow that day's credit.
#: See `forecast._order`.
DEBITS_BEFORE_CREDITS = True

# --- Output -----------------------------------------------------------------

#: Where predictions are written. The dataset directory is never a valid target.
OUTPUT_FILENAME = "output.csv"
