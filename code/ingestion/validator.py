"""
validator.py — Dataset integrity checks for all ingested data.

Validates:
1. All request user_ids exist in financial_profiles.csv
2. All request user_ids have at least one event in financial_events.csv
3. All request_ids in request_payment_options.csv match a known request
4. All linked_event_ids in financial_events.csv point to a known event
5. Each request has 2–4 payment options (per problem spec)

Returns a list of ValidationIssue objects. Warnings do not abort the run;
Errors should be treated as fatal mismatches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from ..models import EvaluationRequest, FinancialEvent, FinancialProfile, SellerPaymentOption

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class ValidationIssue:
    severity: Severity
    check: str
    message: str


class DatasetValidator:
    """
    Run referential-integrity and schema-consistency checks against loaded data.

    Usage:
        validator = DatasetValidator(profiles, events, requests, payment_options)
        issues = validator.validate()
        errors = [i for i in issues if i.severity == Severity.ERROR]
    """

    def __init__(
        self,
        profiles: Dict[str, FinancialProfile],
        events: Dict[str, List[FinancialEvent]],
        requests: List[EvaluationRequest],
        payment_options: Dict[str, List[SellerPaymentOption]],
    ) -> None:
        self._profiles = profiles
        self._events = events
        self._requests = requests
        self._payment_options = payment_options

    def validate(self) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        issues.extend(self._check_request_profiles())
        issues.extend(self._check_request_events())
        issues.extend(self._check_payment_option_counts())
        issues.extend(self._check_option_request_refs())
        issues.extend(self._check_linked_event_ids())

        errors = sum(1 for i in issues if i.severity == Severity.ERROR)
        warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
        logger.info("Dataset validation: %d errors, %d warnings", errors, warnings)
        for issue in issues:
            log_fn = logger.error if issue.severity == Severity.ERROR else logger.warning
            log_fn("[%s] %s: %s", issue.severity.value, issue.check, issue.message)
        return issues

    # ── Individual checks ───────────────────────────────────────────────────

    def _check_request_profiles(self) -> List[ValidationIssue]:
        issues = []
        known_users = set(self._profiles.keys())
        for req in self._requests:
            if req.user_id not in known_users:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    check="request_profile_ref",
                    message=f"{req.request_id}: user_id '{req.user_id}' not found in financial_profiles.csv",
                ))
        return issues

    def _check_request_events(self) -> List[ValidationIssue]:
        issues = []
        for req in self._requests:
            if req.user_id not in self._events:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    check="request_events_ref",
                    message=f"{req.request_id}: user_id '{req.user_id}' has no events in financial_events.csv",
                ))
        return issues

    def _check_payment_option_counts(self) -> List[ValidationIssue]:
        issues = []
        for req in self._requests:
            opts = self._payment_options.get(req.request_id, [])
            count = len(opts)
            if count < 2:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    check="payment_option_count",
                    message=f"{req.request_id}: expected 2–4 payment options, found {count}",
                ))
            elif count > 4:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    check="payment_option_count",
                    message=f"{req.request_id}: expected 2–4 payment options, found {count}",
                ))
        return issues

    def _check_option_request_refs(self) -> List[ValidationIssue]:
        issues = []
        known_request_ids = {req.request_id for req in self._requests}
        for request_id in self._payment_options:
            if request_id not in known_request_ids:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    check="option_request_ref",
                    message=f"Payment options reference unknown request_id '{request_id}'",
                ))
        return issues

    def _check_linked_event_ids(self) -> List[ValidationIssue]:
        issues = []
        all_event_ids: set[str] = set()
        for user_events in self._events.values():
            for evt in user_events:
                all_event_ids.add(evt.event_id)
        for user_events in self._events.values():
            for evt in user_events:
                if evt.linked_event_id and evt.linked_event_id not in all_event_ids:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        check="linked_event_ref",
                        message=(
                            f"Event '{evt.event_id}' links to unknown event_id "
                            f"'{evt.linked_event_id}'"
                        ),
                    ))
        return issues
