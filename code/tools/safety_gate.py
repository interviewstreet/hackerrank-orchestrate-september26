"""Screen untrusted evidence before it reaches the reasoning context.

The spec is explicit: messages and images are untrusted data that may clarify,
amend, delay, cancel or confirm a financial fact, but embedded instructions
never override the challenge rules. Defence is layered:

1. A regex pre-screen catches the common injection shapes for free -- no API
   call, and it works on the dataset's Indonesian text as well as English.
2. ``meta-llama/llama-prompt-guard-2-86m`` (14,400 requests/day, far cheaper
   than the reasoning models) classifies anything the regex flags.
3. Whatever survives is wrapped in ``<untrusted_message>`` delimiters, with
   flagged items marked, so the model can read the financial content without
   treating it as instruction.
"""

from __future__ import annotations

import re

from utils.llm_client import LLMClient
from validators.schemas import Message

# Instruction-shaped patterns, in the languages present in messages.csv.
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)", re.I),
    re.compile(r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|rules|instructions)", re.I),
    re.compile(r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\b", re.I),
    re.compile(r"\b(system|assistant)\s*:", re.I),
    re.compile(r"\b(must|always)\s+output\b", re.I),
    re.compile(r"\b(affordable_now|not_affordable|affordable_with_plan|full_payment)\b"),
    re.compile(r"\boverride\b.{0,40}\b(rule|limit|check|minimum)", re.I),
    re.compile(r"\bskip\b.{0,30}\b(check|validation|safety)", re.I),
    re.compile(r"\bapprove\b.{0,30}\b(regardless|anyway|without)", re.I),
    # Indonesian equivalents (messages.csv is bilingual).
    re.compile(r"abaikan\s+(semua\s+)?(instruksi|aturan)", re.I),
    re.compile(r"\bharus\s+menyetujui\b", re.I),
)

SAFE_VERDICTS = frozenset({"safe", "benign", "label_0", "0"})


class SafetyGate:
    """Marks untrusted evidence and renders it inside explicit delimiters."""

    def __init__(self, client: LLMClient | None = None, model: str | None = None) -> None:
        self.client = client
        self.model = model

    def screen(self, messages: list[Message], request_id: str | None = None) -> list[Message]:
        """Flag messages that try to issue instructions. Content is never dropped.

        Dropping text risks losing a genuine financial amendment, so a flagged
        message is kept and labelled instead: the orchestrator is told to read it
        for facts only.
        """
        for message in messages:
            hit = self._regex_hit(message.message_text)
            if hit is None:
                continue
            verdict = self._classify(message.message_text, request_id)
            if verdict is False:
                message.is_trusted = True
                message.injection_note = None
                continue
            message.is_trusted = False
            message.injection_note = f"instruction-like pattern: {hit}"
        return messages

    @staticmethod
    def _regex_hit(text: str) -> str | None:
        for pattern in INJECTION_PATTERNS:
            found = pattern.search(text or "")
            if found:
                return found.group(0)[:60]
        return None

    def _classify(self, text: str, request_id: str | None) -> bool | None:
        """True = injection, False = benign, None = undetermined."""
        if self.client is None or self.model is None:
            return None
        verdict = self.client.classify(
            model=self.model, text=text[:1500], request_id=request_id
        )
        if verdict is None:
            return None
        return verdict.strip().lower() not in SAFE_VERDICTS


def render_messages(messages: list[Message]) -> str:
    """Render evidence for the prompt with untrusted content clearly fenced."""
    if not messages:
        return "(no messages for this request)"
    blocks: list[str] = []
    for message in messages:
        flag = "" if message.is_trusted else " flagged=\"instructions-ignored\""
        target = message.related_event_id or "none"
        blocks.append(
            f'<untrusted_message id="{message.message_id}" from="{message.source_type}" '
            f'sent="{message.sent_at.isoformat()}" describes_event="{target}"{flag}>\n'
            f"{message.message_text.strip()}\n"
            f"</untrusted_message>"
        )
    return "\n".join(blocks)
