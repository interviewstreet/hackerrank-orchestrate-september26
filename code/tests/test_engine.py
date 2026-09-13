"""M1 financial core: cash state, FX, recurrence, forecast, planning, gating.

Safety claims are proved two ways: against hand-computed expectations, and
against `tests/oracle.py`, an independent replay written from the contract
rather than from `forecast.py`.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from buy_or_wait import config, planner, recurrence, spending, state, validation  # noqa: E402
from buy_or_wait import forecast as F  # noqa: E402
from buy_or_wait.fx import RateUnavailable, convert  # noqa: E402
from buy_or_wait.money import ZERO  # noqa: E402
from buy_or_wait.schema import (  # noqa: E402
    ExchangeRate, FinancialEvent, PaymentOption, Profile, RequestInput,
)
from tests import oracle  # noqa: E402

D = Decimal
TODAY = date(2024, 3, 1)


# ------------------------------------------------------------- builders -----


def event(event_id, *, amount="100", direction="debit", status="settled", on=TODAY,
          category="groceries", description="shop", currency="ZAR", settle=None,
          flexibility="fixed", floor=None, event_type=None, link=None) -> FinancialEvent:
    return FinancialEvent(
        event_id=event_id, user_id="user_01",
        event_type=event_type or ("income" if direction == "credit" else "expense"),
        description=description, category=category, direction=direction,
        amount=None if amount is None else D(amount), currency=currency,
        event_date=on, settlement_date=settle if settle is not None else on,
        status=status, linked_event_id=link, flexibility=flexibility,
        minimum_allowed_amount=None if floor is None else D(floor),
    )


def profile(balance="10000", minimum="2000", methods=("full_payment",), currency="ZAR") -> Profile:
    return Profile(
        user_id="user_01", home_currency=currency,
        current_available_balance=D(balance), minimum_balance_to_keep=D(minimum),
        financial_priorities=(), expense_categories_to_protect=frozenset({"rent"}),
        expense_categories_user_is_willing_to_reduce=frozenset({"dining"}),
        expense_categories_user_is_willing_to_stop=frozenset({"streaming"}),
        payment_methods_user_will_consider=frozenset(methods), max_installment_months=6,
    )


def request(amount="1000", *, deadline_days=30, partial=False) -> RequestInput:
    return RequestInput(
        request_id="request_01", user_id="user_01", request_date=TODAY,
        request_type="purchase", requested_amount=D(amount),
        desired_completion_date=TODAY + timedelta(days=deadline_days),
        allows_partial_payment=partial, request_text="",
    )


def rate_table(*rows) -> dict:
    return {(r.rate_date, r.from_currency, r.to_currency): r for r in rows}


def build(events, prof=None, rates=None, when=TODAY):
    prof = prof or profile()
    rates = rates if rates is not None else {}
    cash = state.reconstruct(events, prof, when, rates)
    rec = recurrence.detect(events, prof, when, rates)
    return cash, rec, F.build(cash, rec, when)


def monthly_series(prefix, *, n=4, amount="500", direction="debit", category="rent",
                    description="rent", last_offset=5, status="settled",
                    flexibility="fixed", floor=None):
    return [
        event(f"{prefix}{i}", amount=amount, direction=direction, category=category,
              description=description, status=status, flexibility=flexibility, floor=floor,
              on=TODAY - timedelta(days=last_offset + 30 * i))
        for i in range(n)
    ]


def option(option_id, *, request_id="request_01", method="installments", amount="500",
           n=2, first=None, freq=30, fee="0", total=None) -> PaymentOption:
    first = first if first is not None else TODAY
    return PaymentOption(
        payment_option_id=option_id, request_id=request_id, payment_method=method,
        payment_amount=D(amount), number_of_payments=n, first_payment_date=first,
        payment_frequency_days=freq, financing_fee=D(fee),
        total_payable_amount=total if total is not None else D(amount) * n,
    )


# ----------------------------------------------------------------- FX -------


class FxTests(unittest.TestCase):
    RATES = rate_table(ExchangeRate(date(2024, 3, 15), "EUR", "ZAR", D("20.12345")))

    def test_identity_conversion_needs_no_rate(self):
        got = convert(D("100"), from_currency="ZAR", to_currency="ZAR",
                      on_date=TODAY, rates={})
        self.assertEqual(got.amount, D("100"))
        self.assertIsNone(got.rate)

    def test_exact_date_uses_full_rate_precision(self):
        got = convert(D("100"), from_currency="EUR", to_currency="ZAR",
                      on_date=date(2024, 3, 15), rates=self.RATES)
        self.assertEqual(got.rate, D("20.12345"))     # rate NOT rounded
        self.assertEqual(got.amount, D("2012.35"))    # result IS rounded

    def test_an_earlier_rate_does_not_satisfy_a_later_date(self):
        with self.assertRaises(RateUnavailable):
            convert(D("100"), from_currency="EUR", to_currency="ZAR",
                    on_date=date(2024, 4, 15), rates=self.RATES)

    def test_reverse_direction_is_not_inferred(self):
        with self.assertRaises(RateUnavailable):
            convert(D("100"), from_currency="ZAR", to_currency="EUR",
                    on_date=date(2024, 3, 15), rates=self.RATES)


# ------------------------------------------------------------ cash state ----


class CashStateTests(unittest.TestCase):
    def test_settled_history_is_not_replayed_onto_the_balance(self):
        events = [event(f"e{i}", amount="500", on=TODAY - timedelta(days=i)) for i in range(1, 6)]
        cash, _, forecast = build(events)
        self.assertEqual(forecast.opening_balance, D("10000"))
        self.assertEqual([m.event_id for m in cash.confirmed], [])
        self.assertTrue(all(r.reason == state.ALREADY_IN_BALANCE for r in cash.excluded))

    def test_pending_debit_is_reserved_exactly_once(self):
        events = [event("e1", amount="500", status="pending", on=TODAY + timedelta(days=3))]
        cash, _, forecast = build(events)
        self.assertEqual(len(cash.confirmed), 1)
        self.assertEqual(forecast.minimum_over_window(), D("9500"))

    def test_a_pending_debit_already_past_is_reserved_immediately(self):
        events = [event("e1", amount="500", status="pending", on=TODAY - timedelta(days=5))]
        cash, _, _ = build(events)
        self.assertEqual(cash.confirmed[0].on_date, TODAY)

    def test_pending_credit_does_not_fund_anything(self):
        events = [event("e1", amount="5000", direction="credit", status="pending",
                        on=TODAY + timedelta(days=2), category="shopping")]
        cash, _, forecast = build(events)
        self.assertEqual(cash.confirmed, ())
        self.assertEqual(forecast.minimum_over_window(), D("10000"))
        self.assertEqual(cash.excluded[0].reason, state.PENDING_CREDIT)

    def test_cancelled_failed_and_unrealized_are_excluded(self):
        events = [
            event("cancelled", status="cancelled", on=TODAY + timedelta(days=1)),
            event("failed", status="failed", on=TODAY + timedelta(days=1)),
            event("unrealized", status="unrealized", direction="non_cash",
                  category="investment", on=TODAY + timedelta(days=1)),
        ]
        cash, _, _ = build(events)
        self.assertEqual(cash.confirmed, ())
        self.assertEqual({r.reason for r in cash.excluded},
                         {state.CANCELLED, state.FAILED, state.UNREALIZED})

    def test_unknown_debit_is_an_unfunded_obligation(self):
        events = [event("e1", amount=None, status="pending", on=TODAY + timedelta(days=2))]
        cash, _, forecast = build(events)
        self.assertEqual(len(cash.unfunded_obligations), 1)
        self.assertFalse(forecast.certifiable)

    def test_unknown_credit_is_not_an_unfunded_obligation(self):
        # Missing income only makes us more cautious, so it does not block.
        events = [event("e1", amount=None, direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=2))]
        cash, _, forecast = build(events)
        self.assertEqual(cash.unfunded_obligations, ())
        self.assertTrue(forecast.certifiable)

    def test_foreign_event_without_a_rate_becomes_an_unfunded_obligation(self):
        events = [event("e1", amount="100", currency="EUR", status="pending",
                        on=TODAY + timedelta(days=2))]
        cash, _, forecast = build(events, rates={})
        self.assertEqual(cash.excluded[0].reason, state.RATE_UNAVAILABLE)
        self.assertFalse(forecast.certifiable)


# ------------------------------------------------------------ recurrence ----


class RecurrenceTests(unittest.TestCase):
    def _monthly(self, n, *, amount="500", direction="debit", category="rent",
                 description="rent", last_offset=5, status="settled"):
        return [
            event(f"{description}{i}", amount=amount, direction=direction, category=category,
                  description=description, status=status,
                  on=TODAY - timedelta(days=last_offset + 30 * i))
            for i in range(n)
        ]

    def test_constant_monthly_debit_becomes_a_fixed_series(self):
        rec = build(self._monthly(4))[1]
        self.assertEqual(len(rec.fixed), 1)
        self.assertEqual(rec.fixed[0].period_days, 30)
        self.assertEqual(rec.fixed[0].amount_home, D("500"))

    def test_two_occurrences_are_not_a_debit_cadence(self):
        rec = build(self._monthly(2))[1]
        self.assertEqual([s for s in rec.fixed if s.direction == "debit"], [])

    def test_varying_amounts_feed_the_category_rate_not_a_fixed_series(self):
        events = [event(f"g{i}", amount=str(100 + i * 7), category="groceries",
                        description="shop", on=TODAY - timedelta(days=5 + 30 * i))
                  for i in range(4)]
        rec = build(events)[1]
        self.assertEqual([s for s in rec.fixed if s.direction == "debit"], [])
        self.assertEqual([r.category for r in rec.rates], ["groceries"])

    def test_every_settled_debit_is_counted_exactly_once(self):
        fixed = self._monthly(4, amount="500", category="rent", description="rent")
        variable = [event(f"g{i}", amount=str(90 + i), category="groceries",
                          description=f"shop {i}", on=TODAY - timedelta(days=3 + 7 * i))
                    for i in range(6)]
        rec = build(fixed + variable)[1]
        in_series = {eid for s in rec.fixed for eid in s.event_ids}
        in_rates = {eid for r in rec.rates for eid in r.event_ids}
        self.assertEqual(in_series & in_rates, set(), "an event fed both a series and a rate")
        self.assertEqual(in_series | in_rates, {e.event_id for e in fixed + variable})

    def test_income_needs_only_two_occurrences(self):
        rec = build(self._monthly(2, direction="credit", category="salary",
                                  description="pay", amount="4000"))[1]
        self.assertEqual([s.direction for s in rec.fixed], ["credit"])

    def test_lapsed_income_is_not_projected(self):
        # Last salary 70 days ago on a 30-day cadence: it stopped.
        rec = build(self._monthly(3, direction="credit", category="salary",
                                  description="pay", amount="4000", last_offset=70))[1]
        self.assertEqual([s for s in rec.fixed if s.direction == "credit"], [])

    def test_income_under_two_different_descriptions_is_one_cadence(self):
        events = [
            event("s1", amount="4000", direction="credit", category="salary",
                  description="Prorated first salary", on=TODAY - timedelta(days=35)),
            event("s2", amount="5000", direction="credit", category="salary",
                  description="Next confirmed salary", status="scheduled",
                  on=TODAY - timedelta(days=5)),
        ]
        rec = build(events)[1]
        credits = [s for s in rec.fixed if s.direction == "credit"]
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0].amount_home, D("5000"))  # latest pay rate

    def test_investment_contributions_are_not_reserved_as_essential(self):
        events = [event(f"i{i}", amount="300", category="investment", description=f"buy {i}",
                        on=TODAY - timedelta(days=5 + 30 * i)) for i in range(4)]
        rec = build(events)[1]
        self.assertNotIn("investment", [r.category for r in rec.rates])


# -------------------------------------------------------------- forecast ----


class ForecastTests(unittest.TestCase):
    def test_agrees_with_the_independent_oracle(self):
        events = [
            event("d1", amount="900", status="scheduled", on=TODAY + timedelta(days=10)),
            event("d2", amount="400", status="pending", on=TODAY + timedelta(days=20)),
            event("c1", amount="2500", direction="credit", status="scheduled",
                  category="salary", on=TODAY + timedelta(days=15)),
        ]
        _, _, forecast = build(events)
        for payment in ([], [(TODAY, D("500"))], [(TODAY + timedelta(days=40), D("3000"))]):
            with self.subTest(payment=payment):
                self.assertEqual(
                    forecast.minimum_over_window(payment),
                    oracle.lowest_balance(D("10000"), forecast.movements, payment),
                )
                self.assertEqual(
                    forecast.is_safe(payment),
                    oracle.is_safe(D("10000"), D("2000"), forecast.movements, payment),
                )

    def test_hand_computed_balance(self):
        # 10000 - 900 (day 10) + 2500 (day 15) - 400 (day 20) = 11200, trough 9100.
        events = [
            event("d1", amount="900", status="scheduled", on=TODAY + timedelta(days=10)),
            event("c1", amount="2500", direction="credit", status="scheduled",
                  category="salary", on=TODAY + timedelta(days=15)),
            event("d2", amount="400", status="pending", on=TODAY + timedelta(days=20)),
        ]
        _, _, forecast = build(events)
        self.assertEqual(forecast.minimum_over_window(), D("9100"))
        self.assertEqual(forecast.headroom(), D("7100"))

    def test_landing_exactly_on_the_minimum_is_safe(self):
        _, _, forecast = build([])
        self.assertTrue(forecast.is_safe([(TODAY, D("8000"))]))      # 10000-8000 == minimum
        self.assertFalse(forecast.is_safe([(TODAY, D("8000.01"))]))

    def test_debits_are_applied_before_credits_on_the_same_date(self):
        when = TODAY + timedelta(days=5)
        events = [
            event("d1", amount="9000", status="scheduled", on=when),
            event("c1", amount="9000", direction="credit", status="scheduled",
                  category="salary", on=when),
        ]
        _, _, forecast = build(events)
        # Net zero by end of day, but the intraday low is 1000 -> below the minimum.
        self.assertEqual(forecast.minimum_over_window(), D("1000"))
        self.assertFalse(forecast.is_safe())

    def test_a_later_bill_blocks_a_payment_that_looks_affordable_today(self):
        events = [event("rent", amount="7000", status="scheduled", on=TODAY + timedelta(days=45))]
        _, _, forecast = build(events)
        self.assertFalse(forecast.is_safe([(TODAY, D("2000"))]))
        self.assertEqual(forecast.breach_date([(TODAY, D("2000"))]), TODAY + timedelta(days=45))

    def test_window_boundaries(self):
        _, _, forecast = build([])
        self.assertEqual(forecast.horizon, TODAY + timedelta(days=config.FORECAST_DAYS))
        inside = event("d", amount="9000", status="scheduled", on=forecast.horizon)
        outside = event("d", amount="9000", status="scheduled",
                        on=forecast.horizon + timedelta(days=1))
        self.assertFalse(build([inside])[2].is_safe())
        self.assertTrue(build([outside])[2].is_safe())

    def test_metamorphic_an_extra_debit_cannot_increase_capacity(self):
        base = build([])[2]
        extra = build([event("x", amount="750", status="scheduled",
                             on=TODAY + timedelta(days=30))])[2]
        self.assertLessEqual(extra.headroom(), base.headroom())
        self.assertLessEqual(extra.amount_safe_to_pay(D("99999")),
                             base.amount_safe_to_pay(D("99999")))

    def test_unquantified_debit_forces_zero_safe_amount(self):
        events = [event("u", amount=None, status="pending", on=TODAY + timedelta(days=2))]
        _, _, forecast = build(events)
        self.assertFalse(forecast.certifiable)
        self.assertEqual(forecast.amount_safe_to_pay(D("100")), ZERO)
        self.assertIsNone(forecast.earliest_full_payment_date(D("100")))

    def test_earliest_date_is_the_first_date_that_survives_the_whole_window(self):
        events = [event("c1", amount="5000", direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=20))]
        _, _, forecast = build(events)
        earliest = forecast.earliest_full_payment_date(D("12000"))
        self.assertEqual(earliest, TODAY + timedelta(days=20))
        self.assertTrue(forecast.is_safe([(earliest, D("12000"))]))
        self.assertFalse(forecast.is_safe([(earliest - timedelta(days=1), D("12000"))]))


# ------------------------------------------------------ planner and gate ----


class PlannerTests(unittest.TestCase):
    def test_affordable_now(self):
        _, _, forecast = build([])
        decision = planner.choose(request("1000"), profile(), forecast)
        self.assertEqual(decision.affordability_status, "affordable_now")
        self.assertEqual(decision.recommended_payment_method, "full_payment")
        self.assertEqual(decision.earliest_date_for_full_payment, TODAY)
        self.assertEqual(decision.amount_safe_to_pay, D("1000"))

    def test_wait_when_capacity_arrives_before_the_deadline(self):
        events = [event("c1", amount="6000", direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=10))]
        _, _, forecast = build(events)
        decision = planner.choose(request("12000", deadline_days=30), profile(), forecast)
        self.assertEqual(decision.recommended_payment_method, "wait")
        self.assertEqual(decision.affordability_status, "affordable_later")
        self.assertEqual(decision.payments[0].on_date, TODAY + timedelta(days=10))

    def test_capacity_after_the_deadline_is_reported_but_not_recommended(self):
        events = [event("c1", amount="6000", direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=40))]
        _, _, forecast = build(events)
        decision = planner.choose(request("12000", deadline_days=20), profile(), forecast)
        self.assertEqual(decision.recommended_payment_method, "not_recommended")
        # Capacity is independent of eligibility (problem_statement.md:163).
        self.assertEqual(decision.earliest_date_for_full_payment, TODAY + timedelta(days=40))

    def test_a_method_the_user_rejects_is_never_recommended(self):
        _, _, forecast = build([])
        decision = planner.choose(request("1000"), profile(methods=("installments",)), forecast)
        self.assertEqual(decision.recommended_payment_method, "not_recommended")
        self.assertTrue(any("not in payment_methods" in r for r in decision.rejected))

    def test_unquantified_obligation_blocks_every_recommendation(self):
        events = [event("u", amount=None, status="pending", on=TODAY + timedelta(days=2))]
        _, _, forecast = build(events)
        decision = planner.choose(request("100"), profile(), forecast)
        self.assertEqual(decision.recommended_payment_method, "not_recommended")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.amount_safe_to_pay, ZERO)

    def test_amount_safe_to_pay_is_capped_at_the_requested_amount(self):
        _, _, forecast = build([])
        decision = planner.choose(request("50"), profile(), forecast)
        self.assertEqual(decision.amount_safe_to_pay, D("50"))


class PartialPaymentTests(unittest.TestCase):
    def _forecast_with_later_capacity(self):
        # Safe today is between 0 and requested; full capacity arrives day 10.
        events = [event("c1", amount="6000", direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=10))]
        return build(events)[2]

    def test_partial_payment_candidate_when_allowed_and_accepted(self):
        forecast = self._forecast_with_later_capacity()
        prof = profile(methods=("full_payment", "partial_payment"))
        decision = planner.choose(request("12000", deadline_days=30, partial=True), prof, forecast)
        self.assertEqual(decision.recommended_payment_method, "partial_payment")
        self.assertEqual(decision.affordability_status, "affordable_with_plan")
        self.assertEqual(len(decision.payments), 2)
        first, second = decision.payments
        self.assertEqual(first.on_date, TODAY)
        self.assertEqual(second.on_date, TODAY + timedelta(days=10))
        self.assertEqual(first.amount + second.amount, D("12000"))

    def test_partial_payment_rejected_when_request_disallows_it(self):
        forecast = self._forecast_with_later_capacity()
        prof = profile(methods=("full_payment", "partial_payment"))
        _, rejected = planner.generate(request("12000", partial=False), prof, forecast)
        self.assertTrue(any("does not allow partial payment" in r for r in rejected))

    def test_partial_payment_rejected_when_user_does_not_accept_it(self):
        forecast = self._forecast_with_later_capacity()
        prof = profile(methods=("full_payment",))
        _, rejected = planner.generate(request("8000", partial=True), prof, forecast)
        self.assertTrue(any("partial_payment: not in payment_methods" in r for r in rejected))

    def test_partial_payment_rejected_when_remainder_lands_after_deadline(self):
        forecast = self._forecast_with_later_capacity()
        prof = profile(methods=("full_payment", "partial_payment"))
        _, rejected = planner.generate(request("12000", deadline_days=5, partial=True), prof, forecast)
        self.assertTrue(any("after the" in r and "deadline" in r for r in rejected))

    def test_partial_payment_rejected_when_safe_today_is_zero(self):
        _, _, forecast = build([])
        prof = profile(balance="100", minimum="100", methods=("full_payment", "partial_payment"))
        _, rejected = planner.generate(request("8000", partial=True), prof, forecast)
        self.assertTrue(any("partial_payment: amount_safe_to_pay" in r for r in rejected))


class InstallmentTests(unittest.TestCase):
    def test_installment_candidate_matches_supplied_option_exactly(self):
        _, _, forecast = build([])
        prof = profile(methods=("installments",))
        options = [option("payment_option_01", amount="500", n=2, first=TODAY + timedelta(days=3))]
        decision = planner.choose(request("1000", deadline_days=60), prof, forecast, payment_options=options)
        self.assertEqual(decision.recommended_payment_method, "installments")
        self.assertEqual(decision.chosen_payment_option_id, "payment_option_01")
        self.assertEqual([(p.on_date, p.amount) for p in decision.payments],
                         [(TODAY + timedelta(days=3), D("500")),
                          (TODAY + timedelta(days=33), D("500"))])

    def test_installment_rejected_when_term_exceeds_max_installment_months(self):
        _, _, forecast = build([])
        prof = profile(methods=("installments",))  # max_installment_months=6
        options = [option("payment_option_01", amount="200", n=12, freq=30)]  # ~11 months
        _, rejected = planner.generate(request("2400", deadline_days=400), prof, forecast,
                                       payment_options=options)
        self.assertTrue(any("exceeds max_installment_months" in r for r in rejected))

    def test_installment_rejected_when_max_installment_months_is_blank(self):
        _, _, forecast = build([])
        base = profile(methods=("installments",))
        prof = Profile(**{**base.__dict__, "max_installment_months": None})
        options = [option("payment_option_01", amount="500", n=2)]
        _, rejected = planner.generate(request("1000"), prof, forecast, payment_options=options)
        self.assertTrue(any("max_installment_months is blank" in r for r in rejected))

    def test_installment_rejected_when_it_completes_after_the_deadline(self):
        _, _, forecast = build([])
        prof = profile(methods=("installments",))
        options = [option("payment_option_01", amount="500", n=2, freq=30)]
        _, rejected = planner.generate(request("1000", deadline_days=10), prof, forecast,
                                       payment_options=options)
        self.assertTrue(any("completes" in r and "after" in r for r in rejected))

    def test_installment_not_offered_when_user_does_not_accept_it(self):
        _, _, forecast = build([])
        prof = profile(methods=("full_payment",))
        options = [option("payment_option_01", amount="500", n=2)]
        candidates, rejected = planner.generate(request("1000"), prof, forecast, payment_options=options)
        self.assertEqual([c for c in candidates if c.method == "installments"], [])
        self.assertTrue(any("installments: not in payment_methods" in r for r in rejected))


class SpendingChangeTests(unittest.TestCase):
    def _tight_forecast_with_stoppable_streaming(self):
        # A future projected streaming debit that only breaches the minimum
        # if it is not stopped.
        events = monthly_series("net", n=4, amount="500", category="streaming",
                                description="netflix", flexibility="stoppable")
        prof = profile(balance="10000", minimum="9000", methods=("full_payment",))
        _, rec, forecast = build(events, prof)
        return prof, rec, forecast

    def test_stopping_a_flexible_expense_makes_full_payment_safe(self):
        prof, rec, forecast = self._tight_forecast_with_stoppable_streaming()
        decision = planner.choose(request("900", deadline_days=60), prof, forecast, rec)
        self.assertEqual(decision.recommended_payment_method, "full_payment")
        self.assertEqual(decision.affordability_status, "affordable_with_plan")
        self.assertEqual(len(decision.spending_changes), 1)
        self.assertTrue(decision.spending_changes[0].startswith("stop:"))

    def test_protected_category_never_offers_a_spending_change(self):
        events = monthly_series("rent", n=4, amount="500", category="rent",
                                description="rent", flexibility="stoppable")
        prof = profile(methods=("full_payment",))  # "rent" is protected in profile()
        _, rec, _ = build(events, prof)
        actions = spending.eligible_actions(rec, prof)
        self.assertEqual(actions, [])

    def test_reduce_action_targets_the_series_minimum_allowed_amount(self):
        events = monthly_series("din", n=4, amount="300", category="dining",
                                description="eating out", flexibility="reducible", floor="100")
        prof = profile(methods=("full_payment",))  # "dining" is willing-to-reduce in profile()
        _, rec, _ = build(events, prof)
        actions = spending.eligible_actions(rec, prof)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "reduce")
        self.assertEqual(actions[0].new_amount, D("100"))


class GateTests(unittest.TestCase):
    def check(self, decision, req=None, prof=None, forecast=None):
        req = req or request("1000")
        prof = prof or profile()
        forecast = forecast or build([])[2]
        return [f.rule for f in validation.check(decision, req, prof, forecast)]

    def good(self):
        return planner.choose(request("1000"), profile(), build([])[2])

    def test_a_clean_decision_passes(self):
        self.assertEqual(self.check(self.good()), [])

    def test_c1_amount_outside_bounds(self):
        bad = self.good()._replace() if hasattr(self.good(), "_replace") else None
        decision = planner.Decision(**{**self.good().__dict__, "amount_safe_to_pay": D("9999")})
        self.assertIn("C1", self.check(decision))

    def test_c3_affordable_now_requires_earliest_equals_request_date(self):
        decision = planner.Decision(**{**self.good().__dict__,
                                       "earliest_date_for_full_payment": TODAY + timedelta(days=5)})
        self.assertIn("C3", self.check(decision))

    def test_c11_method_not_accepted(self):
        self.assertIn("C11", self.check(self.good(), prof=profile(methods=("installments",))))

    def test_c14_status_and_method_must_agree(self):
        decision = planner.Decision(**{**self.good().__dict__,
                                       "affordability_status": "not_affordable"})
        self.assertIn("C14", self.check(decision))

    def test_c16_plan_after_the_deadline(self):
        late = request("1000", deadline_days=0)
        decision = planner.Decision(**{**self.good().__dict__,
                                       "payments": (planner.Payment(TODAY + timedelta(days=5), D("1000")),)})
        self.assertIn("C16", self.check(decision, req=late))

    def test_p1_replay_catches_a_schedule_that_breaches(self):
        forecast = build([event("rent", amount="9500", status="scheduled",
                                on=TODAY + timedelta(days=10))])[2]
        decision = planner.Decision(**{**self.good().__dict__,
                                       "payments": (planner.Payment(TODAY, D("1000")),)})
        self.assertIn("P1", self.check(decision, forecast=forecast))

    def test_p1_independent_replay_survives_a_faulty_planner_safety_method(self):
        # A stubbed `Forecast.is_safe`/`walk` that always claims safety must
        # not be able to bypass P1: `validation.independent_replay` re-derives
        # the walk from `forecast.movements` on its own, never calling either.
        forecast = build([event("rent", amount="9500", status="scheduled",
                                on=TODAY + timedelta(days=10))])[2]
        decision = planner.Decision(**{**self.good().__dict__,
                                       "payments": (planner.Payment(TODAY, D("1000")),)})
        original_is_safe, original_walk = F.Forecast.is_safe, F.Forecast.walk
        F.Forecast.is_safe = lambda self, extra=(): True
        F.Forecast.walk = lambda self, extra=(): [F.Step(self.request_date, self.opening_balance, None)]
        try:
            self.assertIn("P1", self.check(decision, forecast=forecast))
        finally:
            F.Forecast.is_safe = original_is_safe
            F.Forecast.walk = original_walk

    def test_p2_degraded_row_cannot_recommend_a_payment(self):
        decision = planner.Decision(**{**self.good().__dict__, "degraded": True})
        failures = self.check(decision)
        self.assertIn("P2", failures)

    def test_conservative_fallback_is_itself_valid(self):
        fallback = validation.conservative_fallback(request("1000"), "test")
        self.assertEqual(self.check(fallback), [])
        self.assertEqual(fallback.amount_safe_to_pay, ZERO)
        self.assertEqual(fallback.recommended_payment_method, "not_recommended")


class IndependentReplayTests(unittest.TestCase):
    """Unit tests for `validation.independent_replay`, which deliberately does
    not call `Forecast.walk` / `Forecast.is_safe`."""

    def test_safe_schedule_returns_none(self):
        forecast = build([])[2]
        self.assertIsNone(validation.independent_replay(forecast, [(TODAY, D("500"))]))

    def test_breach_returns_the_first_offending_date(self):
        forecast = build([event("rent", amount="9500", status="scheduled",
                                on=TODAY + timedelta(days=10))])[2]
        breach = validation.independent_replay(forecast, [(TODAY, D("1000"))])
        self.assertEqual(breach, TODAY + timedelta(days=10))

    def test_payment_before_request_date_is_rejected(self):
        forecast = build([])[2]
        early = TODAY - timedelta(days=1)
        self.assertEqual(validation.independent_replay(forecast, [(early, D("10"))]), early)

    def test_payment_after_horizon_is_rejected(self):
        forecast = build([])[2]
        late = forecast.horizon + timedelta(days=1)
        self.assertEqual(validation.independent_replay(forecast, [(late, D("10"))]), late)

    def test_uncertain_forecast_cannot_be_certified_safe(self):
        events = [event("unk", amount=None, direction="debit", status="settled",
                        on=TODAY + timedelta(days=5))]
        forecast = build(events)[2]
        self.assertFalse(forecast.certifiable)
        self.assertEqual(validation.independent_replay(forecast, [(TODAY, D("10"))]), TODAY)


class M3GateTests(unittest.TestCase):
    """Negative tests for C5-C10 (partial_payment, installments) and E1-E7
    (spending_changes_needed), plus P1 replay of a spending-change claim."""

    def check(self, decision, req, prof, forecast, payment_options=(), events=(), rec=None):
        return [f.rule for f in validation.check(decision, req, prof, forecast,
                                                  payment_options, events, rec)]

    # ---- partial_payment (C5-C8) -------------------------------------------

    def _partial_setup(self):
        events = [event("c1", amount="6000", direction="credit", status="scheduled",
                        category="salary", on=TODAY + timedelta(days=10))]
        _, _, forecast = build(events)
        prof = profile(methods=("full_payment", "partial_payment"))
        req = request("12000", deadline_days=30, partial=True)
        decision = planner.choose(req, prof, forecast)
        return req, prof, forecast, decision

    def test_good_partial_payment_passes(self):
        req, prof, forecast, decision = self._partial_setup()
        self.assertEqual(self.check(decision, req, prof, forecast), [])

    def test_c6_partial_payment_when_request_disallows_it(self):
        req, prof, forecast, decision = self._partial_setup()
        bad_req = request("12000", deadline_days=30, partial=False)
        self.assertIn("C6", self.check(decision, bad_req, prof, forecast))

    def test_c7_partial_payment_amount_out_of_bounds(self):
        req, prof, forecast, decision = self._partial_setup()
        bad = planner.Decision(**{**decision.__dict__, "amount_safe_to_pay": D("0")})
        self.assertIn("C7", self.check(bad, req, prof, forecast))

    def test_c8_partial_payment_wrong_schedule_shape(self):
        req, prof, forecast, decision = self._partial_setup()
        bad = planner.Decision(**{**decision.__dict__,
                                   "payments": (planner.Payment(TODAY, D("12000")),)})
        self.assertIn("C8", self.check(bad, req, prof, forecast))

    def test_c8_partial_payment_wrong_second_amount(self):
        req, prof, forecast, decision = self._partial_setup()
        first, second = decision.payments
        bad = planner.Decision(**{**decision.__dict__,
                                   "payments": (first, planner.Payment(second.on_date, D("1")))})
        self.assertIn("C8", self.check(bad, req, prof, forecast))

    # ---- installments (C9-C10) ---------------------------------------------

    def _installment_setup(self):
        _, _, forecast = build([])
        prof = profile(methods=("installments",))
        opts = [option("payment_option_01", amount="500", n=2, first=TODAY + timedelta(days=3))]
        req = request("1000", deadline_days=60)
        decision = planner.choose(req, prof, forecast, payment_options=opts)
        return req, prof, forecast, opts, decision

    def test_good_installments_passes(self):
        req, prof, forecast, opts, decision = self._installment_setup()
        self.assertEqual(self.check(decision, req, prof, forecast, opts), [])

    def test_c9_installments_no_matching_option(self):
        req, prof, forecast, opts, decision = self._installment_setup()
        bad = planner.Decision(**{**decision.__dict__, "chosen_payment_option_id": "nonexistent"})
        self.assertIn("C9", self.check(bad, req, prof, forecast, opts))

    def test_c9_installments_wrong_schedule(self):
        req, prof, forecast, opts, decision = self._installment_setup()
        first, second = decision.payments
        bad = planner.Decision(**{**decision.__dict__,
                                   "payments": (first, planner.Payment(
                                       second.on_date + timedelta(days=1), second.amount))})
        self.assertIn("C9", self.check(bad, req, prof, forecast, opts))

    def test_c10_installments_term_exceeds_max_months(self):
        req, prof, forecast, _, decision = self._installment_setup()
        long_opt = option("payment_option_09", amount="200", n=12, freq=30, first=TODAY)
        long_req = request("2400", deadline_days=400)
        long_decision = planner.Decision(**{**decision.__dict__,
            "chosen_payment_option_id": "payment_option_09",
            "payments": tuple(planner.Payment(TODAY + timedelta(days=30 * i), D("200"))
                              for i in range(12))})
        self.assertIn("C10", self.check(long_decision, long_req, prof, forecast, [long_opt]))

    def test_c10_installments_max_months_blank(self):
        req, prof, forecast, opts, decision = self._installment_setup()
        blank_prof = Profile(**{**prof.__dict__, "max_installment_months": None})
        self.assertIn("C10", self.check(decision, req, blank_prof, forecast, opts))

    # ---- spending_changes_needed (E1-E7) -----------------------------------

    def _spending_setup(self):
        events = monthly_series("net", n=4, amount="500", category="streaming",
                                description="netflix", flexibility="stoppable")
        prof = profile(balance="10000", minimum="9000", methods=("full_payment",))
        _, rec, forecast = build(events, prof)
        req = request("900", deadline_days=60)
        decision = planner.choose(req, prof, forecast, rec)
        return req, prof, forecast, tuple(events), decision, rec

    def test_good_spending_change_passes(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        self.assertEqual(self.check(decision, req, prof, forecast, (), events, rec), [])

    def test_e1_spending_changes_require_affordable_with_plan(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        bad = planner.Decision(**{**decision.__dict__, "affordability_status": "affordable_now"})
        self.assertIn("E1", self.check(bad, req, prof, forecast, (), events, rec))

    def test_e2_too_many_spending_changes(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        literal = decision.spending_changes[0]
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": (literal,) * 4})
        self.assertIn("E2", self.check(bad, req, prof, forecast, (), events, rec))

    def test_e3_unparseable_spending_change(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("garbage",)})
        self.assertIn("E3", self.check(bad, req, prof, forecast, (), events, rec))

    def test_e4_duplicate_event_reference(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        event_id = decision.spending_changes[0].split(":")[1]
        bad = planner.Decision(**{**decision.__dict__,
                                   "spending_changes": (f"stop:{event_id}",
                                                        f"reduce_to:{event_id}:100")})
        self.assertIn("E4", self.check(bad, req, prof, forecast, (), events, rec))

    def test_e5_unknown_event_id(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("stop:no_such_event",)})
        self.assertIn("E5", self.check(bad, req, prof, forecast, (), events, rec))

    def test_e5_same_description_unrelated_event_cannot_authorize_a_cut(self):
        # A same-(category, description) event that is NOT the recurring
        # series' own citation id (`event_ids[-1]`) must not authorize a
        # spending change.
        req, prof, forecast, events, decision, rec = self._spending_setup()
        impostor = event("impostor_netflix", amount="500", category="streaming",
                         description="netflix", flexibility="stoppable",
                         on=TODAY - timedelta(days=1))
        bad = planner.Decision(**{**decision.__dict__,
                                   "spending_changes": ("stop:impostor_netflix",)})
        self.assertIn("E5", self.check(bad, req, prof, forecast, (), events + (impostor,), rec))

    def test_e6_protected_category(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        rent_events = tuple(monthly_series("rent", n=4, amount="500", category="rent",
                                           description="rent", flexibility="stoppable"))
        _, rec2, _ = build(events + rent_events, prof)
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("stop:rent0",)})
        self.assertIn("E6", self.check(bad, req, prof, forecast, (), events + rent_events, rec2))

    def test_e7_wrong_flexibility_for_stop(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        # "streaming" is in willing_to_stop, but this event is "fixed", not stoppable.
        fixed_events = tuple(monthly_series("fx", n=4, amount="200", category="streaming",
                                            description="fixed sub", flexibility="fixed"))
        _, rec2, _ = build(events + fixed_events, prof)
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("stop:fx0",)})
        self.assertIn("E7", self.check(bad, req, prof, forecast, (), events + fixed_events, rec2))

    def test_e7_category_not_permitted_for_reduce(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        # "gym" is reducible but not in profile()'s willing_to_reduce (only "dining" is).
        gym_events = tuple(monthly_series("gx", n=4, amount="300", category="gym",
                                          description="membership", flexibility="reducible",
                                          floor="100"))
        _, rec2, _ = build(events + gym_events, prof)
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("reduce_to:gx0:100",)})
        self.assertIn("E7", self.check(bad, req, prof, forecast, (), events + gym_events, rec2))

    def test_e7_reduce_below_floor(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        dining_events = tuple(monthly_series("din", n=4, amount="300", category="dining",
                                             description="eating out", flexibility="reducible",
                                             floor="100"))
        _, rec2, _ = build(events + dining_events, prof)
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("reduce_to:din0:50",)})
        self.assertIn("E7", self.check(bad, req, prof, forecast, (), events + dining_events, rec2))

    def test_e7_reduce_is_not_actually_a_reduction(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        dining_events = tuple(monthly_series("din", n=4, amount="300", category="dining",
                                             description="eating out", flexibility="reducible",
                                             floor="100"))
        _, rec2, _ = build(events + dining_events, prof)
        bad = planner.Decision(**{**decision.__dict__, "spending_changes": ("reduce_to:din0:300",)})
        self.assertIn("E7", self.check(bad, req, prof, forecast, (), events + dining_events, rec2))

    def test_e7_reduce_amount_must_be_finite_and_non_negative(self):
        req, prof, forecast, events, decision, rec = self._spending_setup()
        for bad_amount in ("-100", "NaN", "Infinity"):
            with self.subTest(bad_amount=bad_amount):
                bad = planner.Decision(**{**decision.__dict__,
                                           "spending_changes": (f"reduce_to:net0:{bad_amount}",)})
                self.assertIn("E7", self.check(bad, req, prof, forecast, (), events, rec))

    # ---- P1 replay of a spending-change claim ------------------------------

    def test_p1_replay_catches_a_spending_change_that_frees_nothing(self):
        req, prof, forecast, events, decision, _ = self._spending_setup()
        # A real, stoppable, willing-to-stop event -- but a stale settled one that
        # is not the series' cited event and matches no projected movement, so
        # stopping it frees no headroom and the payment still breaches.
        unrelated = event("unrelated1", amount="50", category="streaming",
                          description="a different subscription", flexibility="stoppable",
                          on=TODAY - timedelta(days=200))
        bad = planner.Decision(**{**decision.__dict__,
                                   "spending_changes": (f"stop:{unrelated.event_id}",)})
        self.assertIn("P1", self.check(bad, req, prof, forecast, (), events + (unrelated,)))

    # ---- E5a-E5d: cited-event ownership / existence / direction checks ------
    # R-B1-01 regression tests. The loader currently prevents these upstream;
    # these are independent safeguards.

    def test_e5_foreign_user_event_rejected(self):
        """A spending change citing an event that belongs to another user must fail."""
        from dataclasses import replace as dc_replace
        req, prof, forecast, events, decision, rec = self._spending_setup()
        foreign = tuple(dc_replace(item, user_id="another_user") for item in events)
        self.assertIn("E5", self.check(decision, req, prof, forecast, (), foreign, rec))

    def test_e5_mismatched_profile_user_rejected(self):
        """Events match request.user_id but profile has a different user -- E5b must catch it."""
        from dataclasses import replace as dc_replace
        req, prof, forecast, events, decision, rec = self._spending_setup()
        bad_prof = dc_replace(prof, user_id="mismatched_user")
        self.assertIn("E5", self.check(decision, req, bad_prof, forecast, (), events, rec))

    def test_e5_missing_event_in_registry_rejected(self):
        """A spending change citing an event_id absent from the supplied events must fail."""
        req, prof, forecast, _events, decision, rec = self._spending_setup()
        # Pass empty events tuple: the cited event_id won't be found.
        self.assertIn("E5", self.check(decision, req, prof, forecast, (), (), rec))

    def test_e5_credit_event_rejected(self):
        """A spending change citing a credit event must fail."""
        from dataclasses import replace as dc_replace
        req, prof, forecast, events, decision, rec = self._spending_setup()
        # Find the cited event_id from the decision's spending change
        parsed = spending.from_literal(decision.spending_changes[0])
        self.assertIsNotNone(parsed)
        _, cited_id, _ = parsed
        # Replace that event's direction with credit
        patched = tuple(
            dc_replace(e, direction="credit") if e.event_id == cited_id else e
            for e in events
        )
        self.assertIn("E5", self.check(decision, req, prof, forecast, (), patched, rec))

    def test_e5_category_mismatch_between_event_and_series_rejected(self):
        """A spending change where the cited event's category differs from the series must fail."""
        from dataclasses import replace as dc_replace
        req, prof, forecast, events, decision, rec = self._spending_setup()
        parsed = spending.from_literal(decision.spending_changes[0])
        self.assertIsNotNone(parsed)
        _, cited_id, _ = parsed
        # Replace that event's category with something different from the series
        patched = tuple(
            dc_replace(e, category="dining") if e.event_id == cited_id else e
            for e in events
        )
        self.assertIn("E5", self.check(decision, req, prof, forecast, (), patched, rec))


if __name__ == "__main__":
    unittest.main()
