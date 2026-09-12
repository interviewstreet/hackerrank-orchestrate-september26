"""Unit tests for evidence extraction models, validation rules, and caching."""

from __future__ import annotations

import sys
import pytest

sys.path.insert(0, "code")
from models import ImageEvidence, MessageEvidenceItem, MessageBatchExtraction
from evidence import build_evidence_lookups, load_image_cache, load_message_cache


def test_image_evidence_schema():
    ev = ImageEvidence(
        image_id="image_01",
        event_id="event_253",
        amount=4365000.0,
        currency="IDR",
        date="2019-09-02",
        document_type="payslip",
        confidence=0.99,
        notes="Net pay",
    )
    assert ev.image_id == "image_01"
    assert ev.amount == 4365000.0
    assert ev.currency == "IDR"


def test_message_evidence_external_reference_filtering():
    # If external ref is passed into amended_event_id, validator must nullify it
    item = MessageEvidenceItem(
        message_id="msg_01",
        user_id="u1",
        event_type="salary_revision",
        external_reference="EMP-0001",
        amended_event_id="EMP-0001",  # Invalid, not event_
        cancelled_event_id="SER-0012",  # Invalid, not event_
        confidence=0.9,
    )
    assert item.external_reference == "EMP-0001"
    assert item.amended_event_id is None
    assert item.cancelled_event_id is None

    # Valid event_id must be preserved
    item_valid = MessageEvidenceItem(
        message_id="msg_02",
        user_id="u1",
        amended_event_id="event_123",
        cancelled_event_id="event_456",
    )
    assert item_valid.amended_event_id == "event_123"
    assert item_valid.cancelled_event_id == "event_456"


def test_vague_salary_confirmation_disallowed():
    # Message says salary is confirmed, but amount and date are missing
    item = MessageEvidenceItem(
        message_id="msg_03",
        user_id="u1",
        event_type="salary_confirmation",
        is_confirmed_income=True,
        confirmed_income_amount=None,
        confirmed_income_date=None,
    )
    # Model validator must set is_confirmed_income to False
    assert item.is_confirmed_income is False

    # When both amount and date are provided, is_confirmed_income stays True
    item_confirmed = MessageEvidenceItem(
        message_id="msg_04",
        user_id="u1",
        event_type="salary_confirmation",
        is_confirmed_income=True,
        confirmed_income_amount=2500.0,
        confirmed_income_date="2026-01-15",
    )
    assert item_confirmed.is_confirmed_income is True
    assert item_confirmed.confirmed_income_amount == 2500.0


def test_evidence_lookups_from_cache():
    blank_amounts, confirmed_incomes, cancelled_events, amended_events = build_evidence_lookups()
    # Cache should contain resolved amounts from the extraction run
    assert isinstance(blank_amounts, dict)
    assert isinstance(confirmed_incomes, dict)
    assert isinstance(cancelled_events, set)
    assert isinstance(amended_events, dict)
