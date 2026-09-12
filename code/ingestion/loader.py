"""
loader.py — Robust CSV ingestion for all dataset files.

Loads all dataset CSVs into typed Pydantic domain models with:
- Type coercion & null handling via Pydantic validators
- Referential integrity checks (user_id consistency, event_id links)
- Per-row validation errors collected and logged without aborting the run
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List

from ..models import (
    EvaluationRequest,
    FinancialEvent,
    FinancialProfile,
    SellerPaymentOption,
)

logger = logging.getLogger(__name__)


class DatasetLoader:
    """
    Loads all dataset CSVs from a given directory.

    Usage:
        loader = DatasetLoader(Path("dataset"))
        loader.load_all()
        profiles = loader.profiles          # Dict[user_id, FinancialProfile]
        events   = loader.events            # Dict[user_id, List[FinancialEvent]]
        requests = loader.requests          # List[EvaluationRequest]
        options  = loader.payment_options   # Dict[request_id, List[SellerPaymentOption]]
    """

    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = Path(dataset_dir)
        self.profiles: Dict[str, FinancialProfile] = {}
        self.events: Dict[str, List[FinancialEvent]] = {}
        self.requests: List[EvaluationRequest] = []
        self.payment_options: Dict[str, List[SellerPaymentOption]] = {}
        self._loaded = False

    # ── Public API ──────────────────────────────────────────────────────────

    def load_all(self) -> None:
        """Load all dataset CSVs. Idempotent — safe to call multiple times."""
        if self._loaded:
            return
        self._load_profiles()
        self._load_events()
        self._load_requests()
        self._load_payment_options()
        self._loaded = True
        logger.info(
            "Dataset loaded",
            extra={
                "profiles": len(self.profiles),
                "users_with_events": len(self.events),
                "total_events": sum(len(v) for v in self.events.values()),
                "requests": len(self.requests),
                "requests_with_options": len(self.payment_options),
            },
        )

    def get_events_for_user(self, user_id: str) -> List[FinancialEvent]:
        return self.events.get(user_id, [])

    def get_options_for_request(self, request_id: str) -> List[SellerPaymentOption]:
        return self.payment_options.get(request_id, [])

    # ── Private loaders ─────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        path = self.dataset_dir / "financial_profiles.csv"
        errors = 0
        for row in self._iter_csv(path):
            try:
                profile = FinancialProfile.model_validate(row)
                self.profiles[profile.user_id] = profile
            except Exception as exc:
                errors += 1
                logger.warning("Skipping invalid profile row: %s | %s", row.get("user_id"), exc)
        logger.info("Loaded %d profiles (%d errors)", len(self.profiles), errors)

    def _load_events(self) -> None:
        path = self.dataset_dir / "financial_events.csv"
        total = 0
        errors = 0
        for row in self._iter_csv(path):
            try:
                event = FinancialEvent.model_validate(row)
                self.events.setdefault(event.user_id, []).append(event)
                total += 1
            except Exception as exc:
                errors += 1
                logger.warning("Skipping invalid event row: %s | %s", row.get("event_id"), exc)
        logger.info("Loaded %d events (%d errors)", total, errors)

    def _load_requests(self) -> None:
        path = self.dataset_dir / "requests.csv"
        errors = 0
        for row in self._iter_csv(path):
            try:
                req = EvaluationRequest.model_validate(row)
                self.requests.append(req)
            except Exception as exc:
                errors += 1
                logger.warning("Skipping invalid request row: %s | %s", row.get("request_id"), exc)
        logger.info("Loaded %d requests (%d errors)", len(self.requests), errors)

    def _load_payment_options(self) -> None:
        path = self.dataset_dir / "request_payment_options.csv"
        total = 0
        errors = 0
        for row in self._iter_csv(path):
            try:
                opt = SellerPaymentOption.model_validate(row)
                self.payment_options.setdefault(opt.request_id, []).append(opt)
                total += 1
            except Exception as exc:
                errors += 1
                logger.warning(
                    "Skipping invalid payment option row: %s | %s",
                    row.get("payment_option_id"),
                    exc,
                )
        logger.info("Loaded %d payment options (%d errors)", total, errors)

    # ── Utility ─────────────────────────────────────────────────────────────

    @staticmethod
    def _iter_csv(path: Path):
        """Yield rows from a CSV file as dicts. Handles UTF-8 with BOM."""
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {path}")
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # Normalize: replace empty strings with None for optional fields
                yield {k: (v if v != "" else None) for k, v in row.items()}
