"""Tests for the financial rules that decide every answer.

Run with:  python tests/test_financial_rules.py

These use hand-built events rather than the dataset, so each rule is pinned in
isolation: a regression names the rule it broke.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.balance_forecaster import ForecastConfig, build_forecast_model  # noqa: E402
from tools.exchange_converter import ExchangeConverter  # noqa: E402
from tools.plan_generator import PlanGenerator  # noqa: E402
from tools.spending_optimizer import suggest_spending_changes  # noqa: E402
from validators.output_validator import validate_output  # noqa: E402
from validators.schemas import (  # noqa: E402
    AgentOutput,
    CashFlow,
    ExchangeRate,
    FinancialEvent,
    FinancialProfile,
    PaymentOption,
    RequestRow,
)

FX = ExchangeConverter(
    [
        ExchangeRate(
            rate_date=date(2026, 3, 15), from_currency="USD", to_currency="INR", rate=80.0
        )
    ]
)
CFG = ForecastConfig()
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  pass  {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        FAILURES.append(name)


def profile(**overrides) -> FinancialProfile:
    base = dict(
        user_id="u1",
        home_currency="INR",
        current_available_balance=100_000.0,
        minimum_balance_to_keep=20_000.0,
        payment_methods_user_will_consider=["full_payment", "partial_payment", "installments"],
        max_installment_months=6,
        expense_categories_to_protect=["rent"],
        expense_categories_user_is_willing_to_reduce=["dining"],
        expense_categories_user_is_willing_to_stop=["streaming"],
    )
    base.update(overrides)
    return FinancialProfile(**base)


def event(event_id: str, amount: float | None, day: int, **overrides) -> FinancialEvent:
    base = dict(
        event_id=event_id,
        user_id="u1",
        event_type="expense",
        description="Groceries",
        category="groceries",
        direction="debit",
        amount=amount,
        currency="INR",
        event_date=date(2026, 3, day),
        settlement_date=date(2026, 3, day),
        status="settled",
        flexibility="fixed",
    )
    base.update(overrides)
    return FinancialEvent(**base)


def request(**overrides) -> RequestRow:
    base = dict(
        request_id="r1",
        user_id="u1",
        request_date=date(2026, 3, 15),
        request_type="purchase",
        requested_amount=30_000.0,
        desired_completion_date=date(2026, 4, 30),
        allows_partial_payment=True,
        request_text="Can I afford this?",
    )
    base.update(overrides)
    return RequestRow(**base)


def model_for(events, prof=None, req=None):
    return build_forecast_model(
        prof or profile(), events, (req or request()).request_date, FX, CFG
    )


# ---- cash-state rules ------------------------------------------------------

def test_cash_states() -> None:
    print("\ncash-state rules")
    future = dict(event_date=date(2026, 4, 1), settlement_date=date(2026, 4, 1))

    cancelled = model_for([event("e1", 50_000, 1, status="cancelled", **future)])
    check("cancelled events never move money", cancelled.simulate()[0] == 100_000)

    failed = model_for([event("e2", 50_000, 1, status="failed", **future)])
    check("failed events never move money", failed.simulate()[0] == 100_000)

    unrealized = model_for(
        [
            event(
                "e3", 50_000, 1, status="unrealized", direction="non_cash",
                event_type="investment_valuation", category="investment", **future,
            )
        ]
    )
    check(
        "unrealized investment value is not cash",
        unrealized.simulate()[0] == 100_000,
    )

    pending_credit = model_for(
        [event("e4", 50_000, 1, status="pending", direction="credit", **future)]
    )
    check(
        "pending credits are not counted",
        pending_credit.simulate()[0] == 100_000,
        f"got {pending_credit.simulate()[0]}",
    )

    pending_debit = model_for([event("e5", 50_000, 1, status="pending", **future)])
    check(
        "pending debits are reserved",
        pending_debit.simulate()[0] == 50_000,
        f"got {pending_debit.simulate()[0]}",
    )

    scheduled = model_for([event("e6", 10_000, 1, status="scheduled", **future)])
    check("scheduled debits are counted", scheduled.simulate()[0] == 90_000)


def test_blank_amount_is_not_zero() -> None:
    print("\nblank amounts")
    model = model_for([event("e7", None, 1, status="scheduled",
                             event_date=date(2026, 4, 1),
                             settlement_date=date(2026, 4, 1))])
    check(
        "an event with no amount is skipped, not treated as zero cost",
        model.simulate()[0] == 100_000 and not model.known_flows,
    )


def test_currency_conversion() -> None:
    print("\ncurrency conversion")
    model = model_for(
        [
            event(
                "e8", 100, 1, currency="USD", status="scheduled",
                event_date=date(2026, 3, 20), settlement_date=date(2026, 3, 20),
            )
        ]
    )
    check(
        "a USD debit converts at the dated rate (100 USD -> 8000 INR)",
        abs(model.simulate()[0] - 92_000) < 1,
        f"got {model.simulate()[0]}",
    )


# ---- recurrence ------------------------------------------------------------

def test_recurrence_needs_evidence() -> None:
    print("\nrecurrence detection")
    once = model_for([event("e9", 5_000, 1)])
    check("a single occurrence is not a series", not once.series)

    monthly = model_for(
        [
            event("a1", 5_000, 10, event_date=date(2026, 1, 10),
                  settlement_date=date(2026, 1, 10)),
            event("a2", 5_000, 10, event_date=date(2026, 2, 10),
                  settlement_date=date(2026, 2, 10)),
            event("a3", 5_000, 10, event_date=date(2026, 3, 10),
                  settlement_date=date(2026, 3, 10)),
        ]
    )
    check("three monthly occurrences make a series", len(monthly.series) == 1)
    check(
        "a monthly series keeps its day-of-month",
        bool(monthly.series) and monthly.series[0].monthly
        and all(f.on.day == 10 for f in monthly.flows() if f.projected),
    )

    salary = [
        event(
            f"s{i}", 40_000, 15, direction="credit", event_type="income",
            category="salary", description="Payroll credit",
            event_date=date(2026, m, 15), settlement_date=date(2026, m, 15),
        )
        for i, m in enumerate((1, 2, 3))
    ]
    final = model_for(
        salary[:2]
        + [
            event(
                "s_final", 40_000, 15, direction="credit", event_type="income",
                category="salary", description="Final employer payroll",
                event_date=date(2026, 3, 15), settlement_date=date(2026, 3, 15),
            )
        ]
    )
    check(
        "a series described as final is not projected forward",
        not any(s.key == "credit:salary" for s in final.series),
    )

    bonus = model_for(
        [
            event(
                f"b{i}", 9_000, 15, direction="credit", event_type="income",
                category="salary", description="Quarterly performance bonus",
                event_date=date(2026, m, 15), settlement_date=date(2026, m, 15),
            )
            for i, m in enumerate((1, 2, 3))
        ]
    )
    check(
        "repeated bonuses never become dependable income",
        not bonus.series,
    )


def test_income_uses_latest_confirmed_amount() -> None:
    print("\nincome forward rate")
    model = model_for(
        [
            event("i1", 30_000, 15, direction="credit", event_type="income",
                  category="salary", description="Payroll credit",
                  event_date=date(2026, 1, 15), settlement_date=date(2026, 1, 15)),
            event("i2", 50_000, 15, direction="credit", event_type="income",
                  category="salary", description="Payroll credit",
                  event_date=date(2026, 2, 15), settlement_date=date(2026, 2, 15)),
        ]
    )
    series = next(s for s in model.series if s.key == "credit:salary")
    check(
        "income projects at its most recent figure, not an average",
        series.amount == 50_000,
        f"got {series.amount}",
    )


# ---- safety and plans ------------------------------------------------------

def test_minimum_balance_is_never_breached() -> None:
    print("\nsafety rule")
    model = model_for([])
    safe = model.amount_safe_today(200_000.0)
    check(
        "safe amount leaves exactly the minimum balance",
        safe == 80_000.0,
        f"got {safe}",
    )

    def paying(amount: float) -> bool:
        return model.is_safe_with(
            [CashFlow(on=date(2026, 3, 15), amount=-amount, label="t", sequence=1)]
        )

    check("paying exactly the safe amount is allowed", paying(80_000.0))
    check("paying one rupee more is rejected", not paying(80_001.0))


def test_installments_respect_the_month_cap() -> None:
    print("\ninstallment eligibility")
    req = request(requested_amount=30_000.0)
    prof = profile(max_installment_months=3)
    options = [
        PaymentOption(
            payment_option_id="p1", request_id="r1", payment_method="installments",
            payment_amount=10_000.0, number_of_payments=3,
            first_payment_date=date(2026, 3, 20), payment_frequency_days=30,
            financing_fee=0.0, total_payable_amount=30_000.0,
        ),
        PaymentOption(
            payment_option_id="p2", request_id="r1", payment_method="installments",
            payment_amount=2_500.0, number_of_payments=12,
            first_payment_date=date(2026, 3, 20), payment_frequency_days=30,
            financing_fee=0.0, total_payable_amount=30_000.0,
        ),
    ]
    generator = PlanGenerator(req, prof, options, model_for([], prof, req))
    plans = generator._installment_plans([])
    ids = {p.payment_option_id for p in plans}
    check("a 3-month plan is allowed under a 3-month cap", "p1" in ids)
    check("a 12-month plan is rejected under a 3-month cap", "p2" not in ids)

    no_cap = PlanGenerator(req, profile(max_installment_months=None), options,
                           model_for([], profile(max_installment_months=None), req))
    check(
        "a blank max_installment_months means no installments at all",
        not no_cap._installment_plans([]),
    )


def test_only_accepted_methods_are_offered() -> None:
    print("\npayment preferences")
    req = request()
    prof = profile(payment_methods_user_will_consider=["installments"])
    generator = PlanGenerator(req, prof, [], model_for([], prof, req))
    check("full payment is withheld when not accepted", generator._full_payment([]) is None)
    check(
        "partial payment is withheld when not accepted",
        generator._partial_payment(10_000.0, date(2026, 4, 1), []) is None,
    )


# ---- spending changes ------------------------------------------------------

def test_spending_changes_respect_permissions() -> None:
    print("\nspending-change permissions")
    events = [
        event(f"r{i}", 20_000, 5, category="rent", description="Rent",
              flexibility="stoppable", event_date=date(2026, m, 5),
              settlement_date=date(2026, m, 5))
        for i, m in enumerate((1, 2, 3))
    ] + [
        event(f"d{i}", 4_000, 8, category="dining", description="Dining",
              flexibility="reducible", minimum_allowed_amount=1_000,
              event_date=date(2026, m, 8), settlement_date=date(2026, m, 8))
        for i, m in enumerate((1, 2, 3))
    ] + [
        event(f"t{i}", 900, 9, category="streaming", description="Streaming",
              flexibility="stoppable", event_date=date(2026, m, 9),
              settlement_date=date(2026, m, 9))
        for i, m in enumerate((1, 2, 3))
    ]
    prof = profile()
    changes = suggest_spending_changes(model_for(events, prof), prof, 50_000.0)
    targets = {c.event_id for c in changes}
    kinds = {c.event_id: c.change_type for c in changes}

    check(
        "a protected category is never changed even when stoppable",
        not any(t.startswith("r") for t in targets),
        f"got {targets}",
    )
    check("a stoppable permitted category may be stopped", kinds.get("t2") == "stop")
    check("a reducible permitted category is reduced", kinds.get("d2") == "reduce_to")
    reduce_change = next((c for c in changes if c.change_type == "reduce_to"), None)
    check(
        "a reduction respects minimum_allowed_amount",
        reduce_change is not None and reduce_change.new_amount == 1_000,
    )
    check("at most three changes are proposed", len(changes) <= 3)
    check(
        "no event is both stopped and reduced",
        len(targets) == len(changes),
    )


# ---- output validation -----------------------------------------------------

def test_validator_catches_bad_rows() -> None:
    print("\noutput validation")
    req = request()
    prof = profile()
    model = model_for([], prof, req)

    def result_for(**overrides):
        fields = dict(
            request_id="r1",
            amount_safe_to_pay=30_000.0,
            affordability_status="affordable_now",
            recommended_payment_method="full_payment",
            payment_plan="2026-03-15:30000",
            earliest_date_for_full_payment="2026-03-15",
            spending_changes_needed="none",
            decision_explanation="ok",
            requested_amount=30_000.0,
        )
        fields.update(overrides)
        return validate_output(AgentOutput(**fields), req, prof, [], [], model)

    check("a correct row passes", result_for().ok, str(result_for().errors))
    check(
        "affordable_now with a later date is rejected",
        not result_for(earliest_date_for_full_payment="2026-04-01").ok,
    )
    check(
        "affordable_now with a non-full method is rejected",
        not result_for(recommended_payment_method="wait").ok,
    )
    check(
        "not_recommended with no plan passes",
        result_for(
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            amount_safe_to_pay=0.0,
            payment_plan="none",
            earliest_date_for_full_payment="",
        ).ok,
    )
    check(
        "not_recommended carrying a plan is rejected",
        not result_for(
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            earliest_date_for_full_payment="",
            payment_plan="2026-03-15:30000",
        ).ok,
    )
    check(
        "a plan breaching the minimum balance is rejected",
        not result_for(
            amount_safe_to_pay=95_000.0,
            requested_amount=95_000.0,
            payment_plan="2026-03-15:95000",
        ).ok,
    )
    check(
        "amount_safe_to_pay is capped at requested_amount",
        AgentOutput(
            request_id="r1", amount_safe_to_pay=99_999.0,
            affordability_status="affordable_now",
            recommended_payment_method="full_payment",
            payment_plan="2026-03-15:30000",
            earliest_date_for_full_payment="2026-03-15",
            spending_changes_needed="none", decision_explanation="",
            requested_amount=30_000.0,
        ).amount_safe_to_pay == 30_000.0,
    )
    check(
        "a spending change on an unknown event is rejected",
        not result_for(spending_changes_needed="stop:nope").ok,
    )
    check(
        "a plan out of chronological order is rejected",
        not result_for(
            affordability_status="affordable_with_plan",
            recommended_payment_method="partial_payment",
            amount_safe_to_pay=10_000.0,
            payment_plan="2026-04-15:20000|2026-03-15:10000",
            earliest_date_for_full_payment="2026-04-15",
        ).ok,
    )
    check(
        "a long explanation is truncated rather than raising",
        len(
            AgentOutput(
                request_id="r1", amount_safe_to_pay=0.0,
                affordability_status="not_affordable",
                recommended_payment_method="not_recommended",
                payment_plan="none", earliest_date_for_full_payment="",
                spending_changes_needed="none",
                decision_explanation="x" * 900, requested_amount=1.0,
            ).decision_explanation
        )
        == 500,
    )


def test_partial_payment_shape() -> None:
    print("\npartial payment shape")
    req = request(requested_amount=30_000.0)
    prof = profile()
    model = model_for([], prof, req)
    result = validate_output(
        AgentOutput(
            request_id="r1",
            amount_safe_to_pay=10_000.0,
            affordability_status="affordable_with_plan",
            recommended_payment_method="partial_payment",
            payment_plan="2026-03-15:10000|2026-04-15:20000",
            earliest_date_for_full_payment="2026-04-15",
            spending_changes_needed="none",
            decision_explanation="ok",
            requested_amount=30_000.0,
        ),
        req, prof, [], [], model,
    )
    check("a well-formed partial payment passes", result.ok, str(result.errors))

    wrong_total = validate_output(
        AgentOutput(
            request_id="r1",
            amount_safe_to_pay=10_000.0,
            affordability_status="affordable_with_plan",
            recommended_payment_method="partial_payment",
            payment_plan="2026-03-15:10000|2026-04-15:15000",
            earliest_date_for_full_payment="2026-04-15",
            spending_changes_needed="none",
            decision_explanation="ok",
            requested_amount=30_000.0,
        ),
        req, prof, [], [], model,
    )
    check("two payments that do not sum to the request are rejected", not wrong_total.ok)


def main() -> None:
    for test in (
        test_cash_states,
        test_blank_amount_is_not_zero,
        test_currency_conversion,
        test_recurrence_needs_evidence,
        test_income_uses_latest_confirmed_amount,
        test_minimum_balance_is_never_breached,
        test_installments_respect_the_month_cap,
        test_only_accepted_methods_are_offered,
        test_spending_changes_respect_permissions,
        test_validator_catches_bad_rows,
        test_partial_payment_shape,
    ):
        test()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): {FAILURES}")
        raise SystemExit(1)
    print("all financial-rule tests passed")


if __name__ == "__main__":
    main()
