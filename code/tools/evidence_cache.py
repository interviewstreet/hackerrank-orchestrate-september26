"""Persist the evidence resolved for each request, so it can be replayed free.

Receipt amounts and message-derived modifications are what turn the raw CSV rows
into the position a recommendation was actually judged against. Without them any
later re-simulation is blind: it rebuilds the forecast from the original events,
misses a salary the payroll message raised, and reports a breach that never
existed.

Writing them down once during the run lets ``evaluation/main.py`` verify an
evidence-bearing recommendation with no API calls at all -- and lets a re-run
skip work it has already paid for.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from validators.schemas import EventModification


class EvidenceCache:
    """Per-request record of recovered amounts and applied modifications."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = self._read()

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass

    # ---- writes ------------------------------------------------------------

    def record_amount(self, request_id: str, event_id: str, amount: float) -> None:
        """Note an amount recovered from a receipt image."""
        with self._lock:
            entry = self._data.setdefault(request_id, {})
            entry.setdefault("amounts", {})[event_id] = amount
            self._flush()

    def record_modifications(
        self, request_id: str, modifications: list[EventModification]
    ) -> None:
        """Note the changes a request's messages established."""
        with self._lock:
            entry = self._data.setdefault(request_id, {})
            entry["modifications"] = [
                m.model_dump(mode="json") for m in modifications
            ]
            entry["messages_resolved"] = True
            self._flush()

    # ---- reads -------------------------------------------------------------

    def amounts(self, request_id: str) -> dict[str, float]:
        return dict(self._data.get(request_id, {}).get("amounts", {}))

    def modifications(self, request_id: str) -> list[EventModification]:
        out: list[EventModification] = []
        for raw in self._data.get(request_id, {}).get("modifications", []):
            try:
                out.append(EventModification.model_validate(raw))
            except Exception:  # noqa: BLE001 - a stale cache must never break a run
                continue
        return out

    def messages_resolved(self, request_id: str) -> bool:
        """Whether message resolution ran for this request."""
        return bool(self._data.get(request_id, {}).get("messages_resolved"))

    def has_entry(self, request_id: str) -> bool:
        return request_id in self._data
