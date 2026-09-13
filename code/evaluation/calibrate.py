"""Score the deterministic engine against the 25 labelled sample requests.

This runs with no API calls at all, so forecaster tuning costs zero of the
daily Groq request quota. Usage:

    python evaluation/calibrate.py                 # score current settings
    python evaluation/calibrate.py --sweep         # grid-search the knobs
    python evaluation/calibrate.py --show request_05
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import REPO_ROOT  # noqa: E402
from tools.balance_forecaster import ForecastConfig, build_forecast_model  # noqa: E402
from tools.dataset_loader import DatasetLoader  # noqa: E402
from tools.exchange_converter import ExchangeConverter  # noqa: E402


def _relative_error(predicted: float, truth: float) -> float:
    if truth == 0:
        return 0.0 if abs(predicted) < 0.01 else 1.0
    return abs(predicted - truth) / abs(truth)


def score(cfg: ForecastConfig, loader: DatasetLoader, verbose: bool = False) -> dict[str, float]:
    """Compare engine output to sample ground truth, field by field."""
    converter = ExchangeConverter(loader.exchange_rates)
    rows: list[dict[str, object]] = []

    for raw in loader.sample_requests:
        request = loader._request(raw)
        profile = loader.profiles.get(request.user_id)
        if profile is None:
            continue
        evidence = _evidence_tag(request, loader)
        model = build_forecast_model(
            profile,
            loader.events_by_user.get(request.user_id, []),
            request.request_date,
            converter,
            cfg,
        )
        forecast = model.summarise(request.requested_amount)
        truth_safe = float(raw["amount_safe_to_pay"] or 0.0)
        truth_date = (raw["earliest_date_for_full_payment"] or "").strip()
        predicted_date = (
            forecast.earliest_full_payment_date.isoformat()
            if forecast.earliest_full_payment_date
            else ""
        )
        rows.append(
            {
                "request_id": request.request_id,
                "currency": profile.home_currency,
                "pred_safe": forecast.amount_safe_to_pay,
                "truth_safe": truth_safe,
                "rel_err": _relative_error(forecast.amount_safe_to_pay, truth_safe),
                "pred_date": predicted_date,
                "truth_date": truth_date,
                "date_match": predicted_date == truth_date,
                "truth_status": raw["affordability_status"],
                "evidence": evidence,
            }
        )

    if not rows:
        return {"n": 0}

    if verbose:
        print(f"{'request':<12}{'ccy':<5}{'predicted':>17}{'truth':>17}{'err':>8} ev  dates")
        for r in rows:
            flag = "ok" if float(r["rel_err"]) <= 0.01 else "  "
            dm = "=" if r["date_match"] else f"{r['pred_date'] or '-'} vs {r['truth_date'] or '-'}"
            print(
                f"{r['request_id']:<12}{r['currency']:<5}"
                f"{float(r['pred_safe']):>17,.2f}{float(r['truth_safe']):>17,.2f}"
                f"{float(r['rel_err']):>7.1%} {flag} {r['evidence']:<3}{dm}"
            )

    stats = _aggregate(rows)
    clean = [r for r in rows if r["evidence"] == "-"]
    if clean:
        for key, value in _aggregate(clean).items():
            stats[f"clean_{key}"] = value
    return stats


def _aggregate(rows: list[dict[str, object]]) -> dict[str, float]:
    errors = sorted(float(r["rel_err"]) for r in rows)
    return {
        "n": len(rows),
        "median_rel_err": errors[len(errors) // 2],
        "mean_rel_err": sum(errors) / len(errors),
        "exact_1pct": sum(1 for e in errors if e <= 0.01) / len(errors),
        "within_10pct": sum(1 for e in errors if e <= 0.10) / len(errors),
        "date_accuracy": sum(1 for r in rows if r["date_match"]) / len(rows),
    }


def _evidence_tag(request, loader: DatasetLoader) -> str:
    """Mark requests whose ground truth depends on messages (m) or images (i).

    The deterministic engine cannot be expected to match these on its own, so
    they are reported separately from pure-forecast accuracy.
    """
    tag = ""
    messages = loader.messages_by_user.get(request.user_id, [])
    if any(m.request_id == request.request_id or not m.request_id for m in messages):
        tag += "m"
    images = loader.images_by_user.get(request.user_id, [])
    if any(i.request_id == request.request_id for i in images):
        tag += "i"
    return tag or "-"


def sweep(loader: DatasetLoader) -> None:
    """Grid-search the forecast knobs and report the best combinations."""
    base = ForecastConfig()
    results: list[tuple[float, float, str, dict[str, float]]] = []
    for conservatism in (0.0, 0.25, 0.5, 0.75, 1.0):
        for lookback in (60, 90, 120, 180, 3650):
            for max_cadence in (35, 45, 62):
                cfg = replace(
                    base,
                    variable_conservatism=conservatism,
                    lookback_days=lookback,
                    max_cadence_days=max_cadence,
                )
                stats = score(cfg, loader)
                label = f"cons={conservatism} lookback={lookback} cadence<={max_cadence}"
                results.append((stats["median_rel_err"], stats["mean_rel_err"], label, stats))

    results.sort(key=lambda r: (r[0], r[1]))
    print(f"{'median':>9}{'mean':>9}{'<=1%':>7}{'<=10%':>7}{'dates':>7}  config")
    for median, mean_err, label, stats in results[:15]:
        print(
            f"{median:>8.1%}{mean_err:>9.1%}{stats['exact_1pct']:>7.0%}"
            f"{stats['within_10pct']:>7.0%}{stats['date_accuracy']:>7.0%}  {label}"
        )


def show(request_id: str, loader: DatasetLoader, cfg: ForecastConfig) -> None:
    """Dump the projected flow ledger for one sample request."""
    raw = next((r for r in loader.sample_requests if r["request_id"] == request_id), None)
    if raw is None:
        print(f"{request_id} is not in sample_requests.csv")
        return
    request = loader._request(raw)
    profile = loader.profiles[request.user_id]
    converter = ExchangeConverter(loader.exchange_rates)
    model = build_forecast_model(
        profile, loader.events_by_user[request.user_id], request.request_date, converter, cfg
    )
    print(
        f"{request_id} {profile.home_currency} balance={profile.current_available_balance:,.2f} "
        f"floor={profile.minimum_balance_to_keep:,.2f} requested={request.requested_amount:,.2f}"
    )
    print(f"request_date={request.request_date} deadline={request.desired_completion_date}")
    print("\ndetected series:")
    for s in model.series:
        kind = "variable" if s.is_variable else "fixed   "
        print(
            f"  {kind} {s.key:<28} every {s.cadence_days:>3}d  {s.amount:>16,.2f}  "
            f"n={s.occurrences} last={s.last_seen} flex={s.flexibility.value}"
        )
    print("\nledger:")
    running = profile.current_available_balance
    for flow in model.flows():
        running += flow.amount
        mark = "  <-- below floor" if running < profile.minimum_balance_to_keep else ""
        tag = "proj" if flow.projected else "known"
        print(f"  {flow.on}  {flow.amount:>16,.2f}  -> {running:>16,.2f}  {tag:<6}{flow.label}{mark}")
    forecast = model.summarise(request.requested_amount)
    print(
        f"\npredicted safe={forecast.amount_safe_to_pay:,.2f}  "
        f"truth={float(raw['amount_safe_to_pay']):,.2f}"
    )
    print(
        f"predicted earliest={forecast.earliest_full_payment_date}  "
        f"truth={raw['earliest_date_for_full_payment'] or '(empty)'}"
    )
    print(f"truth status={raw['affordability_status']} method={raw['recommended_payment_method']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the forecast engine.")
    parser.add_argument("--sweep", action="store_true", help="grid-search the knobs")
    parser.add_argument("--show", metavar="REQUEST_ID", help="dump one request's ledger")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    loader = DatasetLoader(REPO_ROOT / "dataset")
    cfg = ForecastConfig()

    if args.sweep:
        sweep(loader)
        return
    if args.show:
        show(args.show, loader, cfg)
        return

    stats = score(cfg, loader, verbose=not args.quiet)
    print(
        f"\nall      n={stats['n']:<3} median={stats['median_rel_err']:>6.1%}  "
        f"<=1%={stats['exact_1pct']:>4.0%}  <=10%={stats['within_10pct']:>4.0%}  "
        f"dates={stats['date_accuracy']:>4.0%}"
    )
    if "clean_n" in stats:
        print(
            f"no-evid  n={int(stats['clean_n']):<3} median={stats['clean_median_rel_err']:>6.1%}  "
            f"<=1%={stats['clean_exact_1pct']:>4.0%}  <=10%={stats['clean_within_10pct']:>4.0%}  "
            f"dates={stats['clean_date_accuracy']:>4.0%}"
        )
    print("(ev column: m=messages, i=images -- those need the LLM evidence path)")


if __name__ == "__main__":
    main()
