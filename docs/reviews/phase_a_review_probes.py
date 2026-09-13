"""Offline Phase A acceptance probes; failures document remaining review findings."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code"))

from buy_or_wait.evidence import ProposedFact, RowTrace, parse_fact_amount, resolve_fact
from tests.test_evidence import EvidenceTestCase


class PhaseAReviewProbes(EvidenceTestCase):
    def test_amendment_fee_is_not_the_amended_payment_amount(self):
        context, _, candidates = self.candidates("request_01")
        text = "The amendment processing fee is ZAR 1."
        context = replace(context, messages=tuple(
            replace(item, message_text=text) if item.message_id == "message_01" else item
            for item in context.messages))
        fact = resolve_fact(
            ProposedFact("amended_amount", "event_04", "event", "1", currency="ZAR",
                         source_ids=("message_01",), source_span=text),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
        )
        self.assertEqual(fact.status, "rejected")

    def test_cancellation_of_request_is_not_cancellation_of_payment(self):
        context, _, candidates = self.candidates("request_01")
        text = "Your cancellation request has been cancelled. The payment remains due."
        context = replace(context, messages=tuple(
            replace(item, message_text=text) if item.message_id == "message_01" else item
            for item in context.messages))
        fact = resolve_fact(
            ProposedFact("cancelled", "event_04", "event", "true",
                         source_ids=("message_01",), source_span=text),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
        )
        self.assertEqual(fact.status, "rejected")

    def test_topic_mentions_and_failed_cancellation_do_not_establish_effect(self):
        for text in ("The cancellation policy is attached.", "Cancellation failed."):
            with self.subTest(text=text):
                context, _, candidates = self.candidates("request_01")
                context = replace(context, messages=tuple(
                    replace(item, message_text=text) if item.message_id == "message_01" else item
                    for item in context.messages))
                fact = resolve_fact(
                    ProposedFact("cancelled", "event_04", "event", "true",
                                 source_ids=("message_01",), source_span=text),
                    candidates=candidates, context=context, events_by_id=self.events_by_id,
                )
                self.assertEqual(fact.status, "rejected")

    def test_cancellation_question_or_instruction_is_not_a_completed_effect(self):
        for text in ("Has this payment been cancelled?", "Please cancel this payment."):
            with self.subTest(text=text):
                context, _, candidates = self.candidates("request_01")
                context = replace(context, messages=tuple(
                    replace(item, message_text=text) if item.message_id == "message_01" else item
                    for item in context.messages))
                fact = resolve_fact(
                    ProposedFact("cancelled", "event_04", "event", "true",
                                 source_ids=("message_01",), source_span=text),
                    candidates=candidates, context=context, events_by_id=self.events_by_id,
                )
                self.assertEqual(fact.status, "rejected")

    def test_decimal_amendment_is_not_truncated_at_sentence_boundary(self):
        context, _, candidates = self.candidates("request_01")
        text = "The payment amount has been corrected to ZAR 900.50."
        context = replace(context, messages=tuple(
            replace(item, message_text=text) if item.message_id == "message_01" else item
            for item in context.messages))
        fact = resolve_fact(
            ProposedFact("amended_amount", "event_04", "event", "900", currency="ZAR",
                         source_ids=("message_01",), source_span=text),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
        )
        self.assertEqual(fact.status, "rejected")

    def test_negated_or_conditional_cancellation_is_not_authorized(self):
        for text in (
            "This payment has not been cancelled. It remains due.",
            "If you cancel next month, please notify payroll.",
            "Your refund request is pending; the payment remains due.",
        ):
            with self.subTest(text=text):
                context, _, candidates = self.candidates("request_01")
                context = replace(context, messages=tuple(
                    replace(item, message_text=text) if item.message_id == "message_01" else item
                    for item in context.messages))
                fact = resolve_fact(
                    ProposedFact("cancelled", "event_04", "event", "true",
                                 source_ids=("message_01",), source_span=text),
                    candidates=candidates, context=context, events_by_id=self.events_by_id,
                )
                self.assertEqual(fact.status, "rejected")

    def test_amendment_keyword_does_not_authorize_wrong_amount(self):
        context, _, candidates = self.candidates("request_01")
        text = "The payment amount has been corrected to ZAR 900."
        context = replace(context, messages=tuple(
            replace(item, message_text=text) if item.message_id == "message_01" else item
            for item in context.messages))
        fact = resolve_fact(
            ProposedFact("amended_amount", "event_04", "event", "1", currency="ZAR",
                         source_ids=("message_01",), source_span=text),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
        )
        self.assertEqual(fact.status, "rejected")

    def test_equal_repeated_numbers_are_ambiguous(self):
        self.assertIsNone(parse_fact_amount("500 plus 500"))

    def test_payslip_attachment_notice_is_not_cancellation_evidence(self):
        context, _, candidates = self.candidates("request_01")
        message = next(item for item in context.messages if item.message_id == "message_01")
        self.assertEqual(message.message_text, "Your February payslip is attached. Ref EMP-0001.")
        fact = resolve_fact(
            ProposedFact("cancelled", "event_04", "event", "true", source_ids=("message_01",),
                         source_span="This payment has been cancelled."),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
        )
        self.assertEqual(fact.status, "rejected")

    def test_converted_fact_is_labelled_in_target_currency(self):
        context, _, candidates = self.candidates("request_01")
        fact = resolve_fact(
            ProposedFact("amount", "event_04", "event", "100", currency="EUR",
                         source_ids=("message_01",)),
            candidates=candidates, context=context, events_by_id=self.events_by_id,
            rates_by_key=self.data.rates_by_key,
        )
        self.assertEqual(fact.status, "accepted")
        trace = RowTrace("request_01", tuple(candidates), accepted=(fact,)).to_json()
        self.assertEqual(trace["accepted"][0]["value"], "2000.00")
        self.assertEqual(trace["accepted"][0]["currency"], "ZAR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
