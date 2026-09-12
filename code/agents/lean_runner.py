"""A low-token path to a decision, for when the daily token allowance is short.

Groq caps tokens per day per model at 200,000, which is not visible in the
``x-ratelimit-*`` headers. The full orchestrator loop costs roughly 10,000 tokens
a request, so 250 requests need about 2.5M -- four times the whole account's
daily allowance across every model. This path exists to fit inside it.

It keeps the part of the pipeline that was *measured* to improve accuracy and
drops the part that was not. On the labelled samples, reading payroll messages
moved ``recommended_payment_method`` from 73% to 91%; the orchestrator's
multi-turn routing on top of that cost about four calls a request without
moving the score. So here the evidence tools still run -- receipts are read,
messages are resolved -- and the decision itself is taken by the deterministic
engine, which needs no tokens at all.

A request carrying no messages and no missing amounts costs nothing whatsoever:
there is no evidence to interpret, so there is nothing for a model to add.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from config import Settings
from tools.balance_forecaster import ForecastConfig, build_forecast_model
from tools.decision_engine import decide
from tools.evidence_cache import EvidenceCache
from tools.exchange_converter import ExchangeConverter
from tools.image_extractor import ImageExtractor
from tools.message_resolver import MessageResolver, apply_modifications
from tools.safety_gate import SafetyGate
from validators.output_validator import validate_output
from validators.schemas import AgentOutput


@dataclass
class LeanRunner:
    """Resolve the evidence, then let the deterministic engine decide."""

    settings: Settings
    converter: ExchangeConverter
    extractor: ImageExtractor
    resolver: MessageResolver
    gate: SafetyGate
    evidence: EvidenceCache | None = None
    forecast_config: ForecastConfig | None = None
    # Reuse the evidence already recorded rather than paying to resolve it
    # again. Lets a fix to the deterministic logic be re-run over affected rows
    # for no tokens at all.
    replay_only: bool = False
    logger: Any = None

    def run(self, bundle) -> AgentOutput:
        """Produce one validated row for `bundle`."""
        from agents.orchestrator import _template_explanation

        config = self.forecast_config or ForecastConfig()
        request, profile = bundle.request, bundle.profile

        # 1. Recover any amount that lives on a receipt rather than in the CSV.
        resolved = self._read_receipts(bundle)
        events = bundle.events
        if resolved:
            events = [
                e.model_copy(update={"amount": resolved[e.event_id]})
                if e.amount is None and e.event_id in resolved
                else e
                for e in events
            ]

        model = build_forecast_model(
            profile, events, request.request_date, self.converter, config
        )

        # 2. Let the messages amend, delay or cancel what history implied.
        if bundle.messages:
            if self.replay_only and self.evidence is not None:
                cached = self.evidence.modifications(request.request_id)
                self._note(
                    f"{request.request_id}: replaying {len(cached)} cached "
                    f"modification(s), no API call"
                )
                model = apply_modifications(model, cached)
                return self._finish(bundle, model, events)
            self.resolver.settings = self._resolver_for(request.request_id)
            analysis = self.resolver.resolve(bundle.messages, model, request.request_id)
            if analysis.modifications:
                self._note(
                    f"{request.request_id}: applied "
                    f"{len(analysis.modifications)} modification(s)"
                )
            if self.evidence is not None:
                self.evidence.record_modifications(
                    request.request_id, analysis.modifications
                )
            model = apply_modifications(model, analysis.modifications)

        return self._finish(bundle, model, events)

    def _finish(self, bundle, model, events) -> AgentOutput:
        """Decide deterministically, and hold the answer to the same checks."""
        from agents.orchestrator import _template_explanation

        request, profile = bundle.request, bundle.profile
        decision = decide(request, profile, bundle.options, model, events)
        output = decision.output
        if not output.decision_explanation:
            output = output.model_copy(
                update={"decision_explanation": _template_explanation(bundle, output)}
            )

        result = validate_output(
            output, request, profile, bundle.options, events, model
        )
        if not result.ok:
            self._note(f"{request.request_id}: validation failed -- {result.errors[0]}")
        return output

    # ---- helpers -----------------------------------------------------------

    def _read_receipts(self, bundle) -> dict[str, float]:
        """Recover missing amounts from their linked receipt images."""
        recovered: dict[str, float] = {}
        by_event = {
            ref.related_event_id: ref for ref in bundle.images if ref.related_event_id
        }
        for event in bundle.events:
            if event.amount is not None or event.event_id not in by_event:
                continue
            amount = self.extractor.resolve_amount(
                by_event[event.event_id],
                event,
                bundle.profile.home_currency,
                bundle.request.request_id,
            )
            if amount is None:
                # Unreadable stays unknown. Never zero.
                continue
            recovered[event.event_id] = amount
            if self.evidence is not None:
                self.evidence.record_amount(
                    bundle.request.request_id, event.event_id, amount
                )
        return recovered

    def _resolver_for(self, request_id: str) -> Settings:
        """Pick the resolver model, spreading load across the daily buckets."""
        pool = self.settings.resolver_pool or (self.settings.resolver_model,)
        chosen = pool[sha1(request_id.encode("utf-8")).digest()[0] % len(pool)]
        if chosen == self.settings.resolver_model:
            return self.settings
        return self.settings.model_copy(update={"resolver_model": chosen})

    def _note(self, text: str) -> None:
        if self.logger is not None:
            self.logger.info(text)
