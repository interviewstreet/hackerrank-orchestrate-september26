"""For every not_affordable/not_recommended row in output.csv, checks whether
the rescue-with-spending-changes mechanism even had a non-empty pool of real,
citable future events to work with (flexible, non-protected, inside the
horizon) -- i.e. whether there was any theoretical room for a deterministic
fix to rescue more cases, versus the pool being empty (in which case only
LLM-extracted facts or more income history could help).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from loaders import load_dataset  # noqa: E402
from fx import FxConverter  # noqa: E402
from event_normalizer import normalize_events  # noqa: E402
from forecast_engine import build_forecast  # noqa: E402
from plan_selector import _gather_spending_change_options  # noqa: E402
import csv  # noqa: E402

ds = load_dataset(REPO_ROOT / "dataset")
fx = FxConverter(ds.rates_by_pair)

output = {r["request_id"]: r for r in csv.DictReader(open(REPO_ROOT / "output.csv", encoding="utf-8"))}

not_affordable_ids = [rid for rid, r in output.items() if r["affordability_status"] == "not_affordable"]

had_pool = 0
empty_pool = 0
had_pool_ids = []

for rid in not_affordable_ids:
    req = ds.requests_by_id[rid]
    profile = ds.profiles_by_user.get(req.user_id)
    if profile is None:
        continue
    user_events = ds.events_by_user.get(req.user_id, [])
    clean = normalize_events(user_events, facts=[])
    forecast = build_forecast(req.user_id, req.request_date, clean, profile, fx)
    pool = _gather_spending_change_options(forecast, profile, req, fx)
    if pool:
        had_pool += 1
        had_pool_ids.append((rid, len(pool), sum(c.freed_home_amount for c in pool)))
    else:
        empty_pool += 1

print(f"not_affordable rows: {len(not_affordable_ids)}")
print(f"  had a non-empty real-event rescue pool: {had_pool}")
print(f"  had NO real-event rescue pool at all:    {empty_pool}")
print()
print("Rows with a non-empty pool (rescue was attempted but still failed/insufficient):")
for rid, n, total in sorted(had_pool_ids, key=lambda x: -x[2])[:15]:
    print(f"  {rid}: {n} option(s), total freeable {total:.2f}")
