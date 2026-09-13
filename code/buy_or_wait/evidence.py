"""Request-scoped evidence retrieval, extracted-fact validation, category
alignment, and conflict resolution.

Model output (`ProposedFact`, from `model.py`) is a **proposal only**. Every
fact here is either accepted after passing citation, scope, and category
checks, or explicitly marked rejected/unresolved with a reason. Nothing in
this module writes to `CashState`/`Recurrence`/`Decision` directly --
`assist.py` decides whether and how to fold accepted facts back into the
deterministic core, and `validation.py`'s existing gate is still the last
word on whether a resulting row may be published.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Optional

from . import fx
from .data import try_parse_iso_date
from .schema import EVENT_CATEGORIES, ExchangeRate, FinancialEvent, RequestContext

# --------------------------------------------------------------- retrieval ---


@dataclass(frozen=True)
class EvidenceRef:
    """One item in the deterministic candidate/source registry.

    `available` records the one retrieval boundary `data.DataSet.request_context`
    does not already enforce: same-user/same-request scoping is structural
    (R-M0-03/07), but a request has only a date while a message has a
    timestamp, so *time* availability is decided here.
    """

    kind: str  # "message" | "image" | "event"
    ref_id: str
    user_id: str
    request_id: Optional[str]
    available: bool
    unavailable_reason: Optional[str] = None


def _message_date(sent_at: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(sent_at.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def retrieve_candidates(
    context: RequestContext, events_by_id: Mapping[str, FinancialEvent]
) -> tuple[EvidenceRef, ...]:
    """Build the request/user-scoped, time-bounded candidate registry.

    `context` is already same-user/request scoped. This adds the availability
    cutoff the plan requires and the M0 status doc flagged as M2's decision:
    a request carries only a date, so no user timezone is assumed -- a
    message's `sent_at` **date** (as written, never shifted) must be on or
    before `request_date` to be usable for a historical decision. A future
    *scheduled* financial event is still forecastable (it is already
    confirmed data, handled by `recurrence.py`/`forecast.py`); what is
    excluded here is evidence -- a message or image -- that did not exist yet
    when the request was made.

    `images.csv` carries no timestamp of its own. An image tied to a specific
    future-dated event is unavailable for the same reason a future message
    would be; an image with no event link, or one linked to a past/settled
    event, is available.
    """
    request_date = context.request.request_date
    refs: list[EvidenceRef] = []

    for message in context.messages:
        sent_date = _message_date(message.sent_at)
        if sent_date is not None and sent_date > request_date:
            refs.append(EvidenceRef(
                "message", message.message_id, message.user_id, message.request_id,
                False, f"sent {sent_date} is after request_date {request_date}",
            ))
            continue
        refs.append(EvidenceRef(
            "message", message.message_id, message.user_id, message.request_id, True
        ))

    for image in context.images:
        linked = events_by_id.get(image.related_event_id) if image.related_event_id else None
        if linked is not None and linked.event_date > request_date:
            refs.append(EvidenceRef(
                "image", image.image_id, image.user_id, image.request_id, False,
                f"linked event {linked.event_id} is dated {linked.event_date}, "
                f"after request_date {request_date}",
            ))
            continue
        refs.append(EvidenceRef("image", image.image_id, image.user_id, image.request_id, True))

    for event in context.events:
        # Structured events are always citable evidence for their own fields;
        # they carry no separate "availability" question here.
        refs.append(EvidenceRef("event", event.event_id, event.user_id, None, True))

    return tuple(refs)


def available_candidates(refs: Iterable[EvidenceRef]) -> dict[str, EvidenceRef]:
    """The subset of the registry a model call may actually cite."""
    return {r.ref_id: r for r in refs if r.available}


# ------------------------------------------------------------ extracted facts

#: Fields a proposed fact may target. Anything else is rejected outright --
#: this is not an open vocabulary a prompt can extend at run time.
VALID_FACT_FIELDS = frozenset({"amount", "category", "cancelled", "amended_amount"})

#: `cancelled` and `amended_amount` change what an existing structured event
#: means (its status or its amount), not merely fill in a currently-unknown
#: value the way `amount` repair does. Codex's Phase A fourth-pass review
#: (docs/reviews/PHASE_A_FOURTH_PASS_REVIEW.md) reproduced two concrete
#: failures even after several corrective passes closed the negation/
#: conditional/self-citation/currency holes: a matching number can describe
#: something other than the replacement amount ("the amendment processing
#: fee is ZAR 1"), and a completed-effect sentence can name a different
#: object than the target event ("your cancellation request has been
#: cancelled; the payment remains due"). Both require binding the claimed
#: effect to its correct referent, not just detecting that the effect
#: occurred somewhere in the message -- a check this engine does not yet
#: have. Rather than keep patching individual adversarial phrasings, these
#: two fields are disabled by default: the rest of the validation pipeline
#: still runs (and is still exercised by tests, since it remains the
#: foundation a future stricter validator would build on), but no mutation
#: reaches "accepted" while this flag is `False`.
ALLOW_EVENT_MUTATIONS = False


@dataclass(frozen=True)
class ProposedFact:
    """Raw model output. Untyped and untrusted until `resolve_fact` runs."""

    field: str
    target_event_id: Optional[str]
    target_scope: str  # "event" | "user_level"
    value: str
    currency: Optional[str] = None
    value_date: Optional[str] = None
    source_ids: tuple[str, ...] = ()
    source_span: str = ""


@dataclass(frozen=True)
class ExtractedFact:
    """A `ProposedFact` after validation. `status` is the only thing a caller
    may trust: an `accepted` fact has a typed `value`; anything else must not
    influence the financial core."""

    field: str
    target_event_id: Optional[str]
    target_scope: str
    value: object
    currency: Optional[str]
    value_date: Optional[date]
    source_ids: tuple[str, ...]
    status: str  # "accepted" | "rejected"
    reason: Optional[str] = None
    source_span: str = ""
    conversion_note: Optional[str] = None


def _reject(proposed: ProposedFact, reason: str) -> ExtractedFact:
    return ExtractedFact(
        proposed.field, proposed.target_event_id, proposed.target_scope, None,
        proposed.currency, None, proposed.source_ids, "rejected", reason, proposed.source_span,
    )


def validate_citations(
    source_ids: Iterable[str], candidates: Mapping[str, EvidenceRef], context: RequestContext
) -> Optional[str]:
    """Return a rejection reason, or `None` if every citation is sound.

    A real id is not proof of relevance (`docs/IMPLEMENTATION_PLAN.md` §4): this
    only proves the id was actually retrieved for *this* request and belongs to
    this request's user. Field-level relevance (does the source actually
    support *this* claim) is checked by the caller in `resolve_fact`.
    """
    ids = tuple(source_ids)
    if not ids:
        return "no supporting source cited"
    for source_id in ids:
        ref = candidates.get(source_id)
        if ref is None:
            return f"{source_id!r} was not retrieved for this request"
        if ref.user_id != context.request.user_id:
            return f"{source_id!r} belongs to a different user"
    return None


def align_category(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Exact-match a proposed category against the real taxonomy.

    No alias table: M0 measured that every protect/reduce/stop token in the
    shipped data is already an exact `EVENT_CATEGORIES` member
    (`docs/IMPLEMENTATION_STATUS.md`, M0 decision 4), and there is no `other`
    event category to fall back to. A paraphrased or invented category is
    rejected outright rather than guessed or silently mapped.
    """
    value = (raw or "").strip()
    if value in EVENT_CATEGORIES:
        return value, None
    return None, f"{value!r} is not an exact event category"


#: One contiguous numeric run: digits optionally grouped/decimalled by `.`/`,`.
#: A gap (space, word, "of", ...) between two such runs means the source text
#: names more than one number -- e.g. "2 invoices of INR 500" -- and
#: concatenating their digits into one value would silently invent an amount
#: no one actually stated.
_NUMBER_RUN = re.compile(r"\d[\d.,]*")


def parse_fact_amount(raw: str) -> Optional[Decimal]:
    """Parse a free-text numeric value, tolerating two real-world conventions:
    `1,234.56` (comma group / dot decimal) and `1.234,56` (dot group / comma
    decimal), plus currency symbols and surrounding words. Anything that does
    not reduce to an unambiguous non-negative number is rejected -- this
    never guesses.
    """
    text = (raw or "").strip()
    if not text:
        return None
    runs = _NUMBER_RUN.findall(text)
    if len(runs) > 1:
        # More than one numeric run -- even equal ones, e.g. "500 plus 500" --
        # names more than one number. Concatenating occurrences (not just
        # distinct values) into a single figure would invent an amount no one
        # stated.
        return None
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".,-")
    if not cleaned or cleaned.count("-") > 0:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        if len(tail) in (1, 2) and "," not in head:
            cleaned = head + "." + tail
        else:
            cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


#: Relatedness (a message/image linked to the target event) proves the source
#: is *about* that event, not that it states a cancellation or amendment --
#: an unrelated payslip notice can be linked to the same salary event it is
#: silent on. These keyword sets are the minimum lexical evidence a cited
#: message must actually contain before such a claim is authorized.
_CANCELLATION_KEYWORDS = (
    "cancel", "void", "revers", "refund", "terminat", "stopp", "withdraw",
)
_AMENDMENT_KEYWORDS = (
    "amend", "correct", "revis", "instead of", "changed to", "updated to",
    "adjust", "settled for", "actual amount", "corrected to",
)

#: Exact bare-verb forms used only to detect an imperative/instruction
#: sentence ("Please cancel this payment.") -- a subjectless directive
#: telling someone to perform the effect is not a statement that the
#: effect already happened. Deliberately narrower and exact-word-matched
#: (unlike the stems above) so nouns such as "Correction:" are not
#: misclassified as a command to "correct".
_IMPERATIVE_VERBS_BY_KEYWORDS = {
    _CANCELLATION_KEYWORDS: (
        "cancel", "void", "refund", "terminate", "stop", "withdraw", "reverse",
    ),
    _AMENDMENT_KEYWORDS: (
        "amend", "correct", "revise", "adjust", "change", "update",
    ),
}

#: Cancellation has no accompanying number to cross-check (unlike an
#: amendment, which must separately state the exact proposed amount), so a
#: keyword mention that merely survives the negation/conditional/uncertainty
#: denylist is not enough: "The cancellation policy is attached." and
#: "Cancellation failed." both contain the keyword and trip none of those
#: markers, yet neither states that the payment was actually cancelled. For
#: this field only, require the completed-effect grammar itself --
#: auxiliary/copula directly followed by the participle -- as a positive
#: precondition rather than defaulting to acceptance whenever nothing bad
#: was found.
_CANCELLATION_COMPLETION_PATTERN = re.compile(
    r"\b(?:has been|have been|was|were|is|are)\s+"
    r"(?:successfully\s+|already\s+|now\s+)?"
    r"(?:cancell?ed|voided|reversed|refunded|terminated|stopped|withdrawn)\b",
    re.IGNORECASE,
)
_POSITIVE_PATTERN_BY_KEYWORDS = {
    _CANCELLATION_KEYWORDS: _CANCELLATION_COMPLETION_PATTERN,
}


def _message_text(context: RequestContext, source_id: str) -> Optional[str]:
    for message in context.messages:
        if message.message_id == source_id:
            return message.message_text
    return None


#: A cited source's keyword match only identifies which sentence to inspect.
#: A keyword-bearing sentence still does not authorize a cancellation or
#: amendment if it is negated ("has not been cancelled"), conditional
#: ("if you cancel"), or describes an uncertain/future/pending effect
#: ("refund is pending") rather than a stated, completed one.
#: Split on sentence punctuation, but never between two digits: a decimal
#: point in "900.50" must survive so amount binding sees the complete
#: number, not a truncated "900". A `.` (or `;!?`) counts as a splitter
#: whenever it is not both preceded and followed by a digit.
_SENTENCE_SPLIT = re.compile(r"(?<!\d)[.;!?\n]+|[.;!?\n]+(?!\d)")
_NEGATION_MARKERS = (" not ", "n't", " never ", "no longer", " without ")
_CONDITIONAL_MARKERS = (
    "if ", "in case", "unless ", "should ", "would ", "were to", "provided that",
)
_UNCERTAIN_MARKERS = (
    "pending", "will be", "may ", "might ", "considering", "requested",
    "next month", "next week", "upcoming", "planned", "expected to", "about to",
)


def _sentences(text: str) -> list[str]:
    """Split `text` into sentences on `_SENTENCE_SPLIT` boundaries.

    A trailing `?` is kept (unlike plain `re.split`, which would discard
    it) so question detection downstream can see it. Trailing `.`/`;`/`!`
    terminators are dropped instead of kept flush against the sentence's
    last word/digit, so a sentence-ending period right after a number
    (e.g. "...ZAR 900.50.") is never mistaken for part of that number.
    """
    sentences = []
    start = 0
    for match in _SENTENCE_SPLIT.finditer(text):
        piece = text[start:match.end()].strip()
        if piece:
            sentences.append(piece.rstrip(".;!\n") or piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_question(sentence: str) -> bool:
    return "?" in sentence


def _is_imperative_instruction(sentence: str, keywords: tuple[str, ...]) -> bool:
    """`True` if `sentence` is a subjectless directive to perform the effect
    ("Please cancel this payment.") rather than a statement that the effect
    already occurred. Matched on the exact bare verb at the very start of
    the sentence (after an optional "please"/"kindly"), never on the topic
    stems in `keywords`, so nouns like "Correction:" are not mistaken for
    the command "correct"."""
    imperative_verbs = _IMPERATIVE_VERBS_BY_KEYWORDS.get(keywords, ())
    if not imperative_verbs:
        return False
    stripped = re.sub(r"^(please|kindly)\s+", "", sentence.strip(), flags=re.IGNORECASE)
    first_word_match = re.match(r"[A-Za-z]+", stripped)
    if not first_word_match:
        return False
    return first_word_match.group(0).lower() in imperative_verbs


def _is_affirmative_effect_sentence(sentence: str, keywords: tuple[str, ...]) -> bool:
    if _is_question(sentence):
        return False
    if _is_imperative_instruction(sentence, keywords):
        return False
    positive_pattern = _POSITIVE_PATTERN_BY_KEYWORDS.get(keywords)
    if positive_pattern is not None and not positive_pattern.search(sentence):
        return False
    lowered = f" {sentence.lower()} "
    if any(marker in lowered for marker in _NEGATION_MARKERS):
        return False
    if any(marker in lowered for marker in _CONDITIONAL_MARKERS):
        return False
    if any(marker in lowered for marker in _UNCERTAIN_MARKERS):
        return False
    return True


def _affirmative_sentence(text: str, keywords: tuple[str, ...]) -> Optional[str]:
    """The first sentence in `text` that both names the effect (a keyword)
    and actually states it happened -- not merely mentions it in passing,
    negated, conditional, interrogative, instructional, or still-pending
    form."""
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        if _is_affirmative_effect_sentence(sentence, keywords):
            return sentence
    return None


def _find_supporting_sentence(
    context: RequestContext, source_ids: Iterable[str], keywords: tuple[str, ...],
    source_span: str,
) -> Optional[str]:
    """The qualifying sentence backing the claimed effect, or `None`.

    Ground truth wins: if any cited source is a message (real `message_text`
    on file), that text -- not the model's own `source_span` -- decides the
    outcome, so a fabricated or over-eager quote can never override what the
    real message actually says. Only when no cited source has retrievable
    ground-truth text (for example, an image-only citation, where this
    engine has no independently verifiable text) does the model's own quoted
    `source_span` get considered at all.
    """
    ground_truth_checked = False
    for source_id in source_ids:
        text = _message_text(context, source_id)
        if text is None:
            continue
        ground_truth_checked = True
        sentence = _affirmative_sentence(text, keywords)
        if sentence is not None:
            return sentence
    if ground_truth_checked:
        return None
    return _affirmative_sentence(source_span, keywords)


#: A three-letter currency code inside the supporting sentence, used to bind
#: a proposed amendment to the currency actually stated (not just any
#: currency the model happens to propose).
_CURRENCY_CODE = re.compile(r"\b[A-Z]{3}\b")


def _sentence_states_amount(
    sentence: str, proposed_amount: Decimal, proposed_currency: Optional[str],
) -> bool:
    """`True` only if the supporting sentence itself states the exact amount
    (and currency, when the sentence names one) being proposed. A keyword
    like "corrected to" proves an amendment happened, not what number it
    changed the amount to -- that number must come from the same sentence."""
    stated_amount = parse_fact_amount(sentence)
    if stated_amount is None or stated_amount != proposed_amount:
        return False
    stated_currencies = set(_CURRENCY_CODE.findall(sentence))
    if proposed_currency and stated_currencies and proposed_currency.upper() not in stated_currencies:
        return False
    return True


def _related_event_id(context: RequestContext, source_id: str) -> Optional[str]:
    for message in context.messages:
        if message.message_id == source_id:
            return message.related_event_id
    for image in context.images:
        if image.image_id == source_id:
            return image.related_event_id
    return None


def resolve_fact(
    proposed: ProposedFact,
    *,
    candidates: Mapping[str, EvidenceRef],
    context: RequestContext,
    events_by_id: Mapping[str, FinancialEvent],
    rates_by_key: Mapping[tuple[date, str, str], ExchangeRate] = {},
) -> ExtractedFact:
    """Validate one proposed fact end to end: citation, scope, relevance,
    category/amount typing. Returns `accepted` only if every check passes."""
    if proposed.field not in VALID_FACT_FIELDS:
        return _reject(proposed, f"unsupported field {proposed.field!r}")

    citation_error = validate_citations(proposed.source_ids, candidates, context)
    if citation_error:
        return _reject(proposed, citation_error)

    target_event: Optional[FinancialEvent] = None
    if proposed.target_scope == "event":
        target_event = events_by_id.get(proposed.target_event_id or "")
        if target_event is None or target_event.user_id != context.request.user_id:
            return _reject(proposed, "target event is not in this request's scope")
        relevant_sources = [
            source_id for source_id in proposed.source_ids
            if source_id == target_event.event_id
            or _related_event_id(context, source_id) == target_event.event_id
        ]
        if not relevant_sources:
            return _reject(proposed, f"cited source(s) do not support event {target_event.event_id}")
        if proposed.field in ("cancelled", "amended_amount"):
            # The event row itself is the thing being changed, not proof of the
            # change -- a cancellation/amendment needs a message or image that
            # actually says so, not merely a citation of the row it targets.
            supporting = [s for s in relevant_sources if s != target_event.event_id]
            if not supporting:
                return _reject(
                    proposed,
                    f"event {target_event.event_id} cannot cite itself as proof of its own "
                    f"{proposed.field}",
                )
            keywords = _CANCELLATION_KEYWORDS if proposed.field == "cancelled" else _AMENDMENT_KEYWORDS
            sentence = _find_supporting_sentence(context, supporting, keywords, proposed.source_span)
            if sentence is None:
                return _reject(
                    proposed,
                    f"cited source(s) are linked to event {target_event.event_id} but do not "
                    f"affirmatively state a {proposed.field.replace('_', ' ')} (negated, "
                    f"conditional, or pending language does not authorize it)",
                )
            if proposed.field == "amended_amount":
                # The keyword only proves an amendment happened; it does not
                # prove the model's proposed number is the one the sentence
                # actually states. Bind them before accepting the change.
                proposed_amount = parse_fact_amount(proposed.value)
                if proposed_amount is None or not _sentence_states_amount(
                    sentence, proposed_amount, proposed.currency
                ):
                    return _reject(
                        proposed,
                        f"cited source(s) do not state the proposed amended amount "
                        f"{proposed.value!r}",
                    )
    elif proposed.target_scope == "user_level":
        if proposed.target_event_id is not None:
            return _reject(proposed, "user_level facts must not carry an event target")
    else:
        return _reject(proposed, f"unsupported target_scope {proposed.target_scope!r}")

    fact_currency = proposed.currency
    conversion_note: Optional[str] = None
    if proposed.field == "category":
        aligned, reason = align_category(proposed.value)
        if aligned is None:
            return _reject(proposed, reason or "category rejected")
        value: object = aligned
    elif proposed.field in ("amount", "amended_amount"):
        amount = parse_fact_amount(proposed.value)
        if amount is None:
            return _reject(proposed, f"{proposed.value!r} is not a parseable amount")
        if proposed.currency and target_event is not None and proposed.currency != target_event.currency:
            try:
                converted = fx.convert(
                    amount, from_currency=proposed.currency, to_currency=target_event.currency,
                    on_date=target_event.settlement_date, rates=rates_by_key,
                )
            except fx.RateUnavailable:
                return _reject(
                    proposed,
                    f"{proposed.currency!r} does not match event currency "
                    f"{target_event.currency!r} and no exact dated rate is available",
                )
            # The stored value is now in the event's currency, not the
            # currency the model proposed -- the fact's `currency` and any
            # provenance note must say so, never keep silently reporting the
            # pre-conversion denomination alongside a converted figure.
            conversion_note = f"{amount} {proposed.currency} -> {converted.cite()}"
            amount = converted.amount
            fact_currency = converted.to_currency
        value = amount
    else:  # "cancelled"
        text = proposed.value.strip().lower()
        if text not in ("true", "false", "yes", "no", "cancelled"):
            return _reject(proposed, f"{proposed.value!r} is not a recognised cancellation flag")
        value = text in ("true", "yes", "cancelled")

    value_date: Optional[date] = None
    if proposed.value_date:
        # `date.fromisoformat` alone is not sufficient: on Python 3.11+ it also
        # accepts compact (`20240303`) and ISO-week (`2024-W09-7`) forms, which
        # would make this parser's strictness depend on the interpreter (the
        # same defect M0 fixed for CSV dates -- reuse that exact contract
        # rather than re-introduce it here).
        value_date = try_parse_iso_date(proposed.value_date.strip())
        if value_date is None:
            return _reject(proposed, f"{proposed.value_date!r} is not a YYYY-MM-DD date")

    if proposed.field in ("cancelled", "amended_amount") and not ALLOW_EVENT_MUTATIONS:
        # Every check above already passed (citation, scope, relevance,
        # affirmative supporting sentence, amount/currency binding for an
        # amendment) -- this is a deliberate policy gate on top, not a
        # substitute for them. It is the last line before acceptance so
        # that "field in VALID_FACT_FIELDS and reaches this point" alone
        # can never smuggle a mutation through some other code path.
        return _reject(
            proposed,
            f"{proposed.field} mutations are disabled pending a validator that binds the "
            "claimed effect to its correct referent (amount role, cancellation target); "
            "see docs/reviews/PHASE_A_FOURTH_PASS_REVIEW.md",
        )

    return ExtractedFact(
        proposed.field, proposed.target_event_id, proposed.target_scope, value,
        fact_currency, value_date, proposed.source_ids, "accepted", None,
        proposed.source_span, conversion_note,
    )


# --------------------------------------------------------- conflict resolution


def resolve_conflicts(
    facts: Iterable[ExtractedFact], context: RequestContext
) -> tuple[ExtractedFact, ...]:
    """Reduce accepted facts to at most one winner per `(target, field)`.

    Order, per `docs/IMPLEMENTATION_PLAN.md` §4: an explicit
    cancellation/amendment wins outright; otherwise the newest same-source
    (message) evidence; otherwise the financially safer interpretation (for a
    debit target, the larger amount; for a credit, the smaller). Rejected
    facts pass through untouched, and a superseded fact is re-labelled
    `rejected` with its own reason so provenance for both sides survives in
    the trace -- never removed outright.

    `amount`, `amended_amount`, and `cancelled` are grouped together per
    target event (not kept in separate per-field groups): they are competing
    claims about the same underlying financial outcome for that event, and an
    amendment/cancellation must be recorded as *superseding* a plain `amount`
    fact rather than merely coexisting with one that `apply_facts_to_events`
    happens to override silently.
    """
    accepted = [f for f in facts if f.status == "accepted"]
    other = [f for f in facts if f.status != "accepted"]

    events_by_id = {e.event_id: e for e in context.events}
    messages_by_id = {m.message_id: m for m in context.messages}

    _AMOUNT_GROUP_FIELDS = {"amount", "amended_amount", "cancelled"}

    def group_key(fact: ExtractedFact) -> tuple[Optional[str], str]:
        field_key = "amount_or_status" if fact.field in _AMOUNT_GROUP_FIELDS else fact.field
        return (fact.target_event_id, field_key)

    groups: dict[tuple[Optional[str], str], list[ExtractedFact]] = {}
    for fact in accepted:
        groups.setdefault(group_key(fact), []).append(fact)

    winners: list[ExtractedFact] = []
    superseded: list[ExtractedFact] = []
    for group in groups.values():
        if len(group) == 1:
            winners.append(group[0])
            continue
        winner = _pick_winner(group, events_by_id, messages_by_id)
        winners.append(winner)
        for fact in group:
            if fact is not winner:
                superseded.append(replace(
                    fact, status="rejected",
                    reason="superseded by a higher-precedence fact for the same target/field",
                ))

    return tuple(winners) + tuple(superseded) + tuple(other)


def _pick_winner(group, events_by_id, messages_by_id) -> ExtractedFact:
    def is_explicit(fact: ExtractedFact) -> bool:
        return fact.field == "amended_amount" or (fact.field == "cancelled" and fact.value is True)

    explicit = [f for f in group if is_explicit(f)]
    if explicit:
        group = explicit
        if len(group) == 1:
            return group[0]

    def recency(fact: ExtractedFact) -> str:
        dates = [messages_by_id[s].sent_at for s in fact.source_ids if s in messages_by_id]
        return max(dates) if dates else ""

    newest = max((recency(f) for f in group), default="")
    newer = [f for f in group if recency(f) == newest]
    if len(newer) == 1:
        return newer[0]
    group = newer if newer else group

    if len(group) > 1 and isinstance(group[0].value, Decimal):
        target = events_by_id.get(group[0].target_event_id)
        direction = target.direction if target else "debit"
        key = (lambda f: f.value) if direction == "debit" else (lambda f: -f.value)
        return max(group, key=key)

    return group[0]


# ------------------------------------------------------------- state repair


def apply_facts_to_events(
    events: tuple[FinancialEvent, ...], facts: Iterable[ExtractedFact]
) -> tuple[FinancialEvent, ...]:
    """Patch events with validated, accepted facts. Deliberately narrow:

    * `amount` only repairs an event whose amount is currently **unknown** --
      it never overwrites a known structured value with an unstructured guess.
    * `amended_amount` and `cancelled` may override a known event, because the
      conflict resolver has already ranked them as an explicit amendment.

    Returns a new tuple; the input is never mutated, so a caller that keeps
    the original context around (e.g. to compare deterministic vs. assisted
    results) is unaffected.
    """
    by_event: dict[str, list[ExtractedFact]] = {}
    for fact in facts:
        if fact.status == "accepted" and fact.target_event_id:
            by_event.setdefault(fact.target_event_id, []).append(fact)
    if not by_event:
        return events

    patched: list[FinancialEvent] = []
    for event in events:
        changes = by_event.get(event.event_id)
        if not changes:
            patched.append(event)
            continue
        amount = event.amount
        status = event.status
        for fact in changes:
            if fact.field == "amount" and event.amount is None:
                amount = fact.value
            elif fact.field == "amended_amount":
                amount = fact.value
            elif fact.field == "cancelled" and fact.value is True:
                status = "cancelled"
        patched.append(event if (amount == event.amount and status == event.status)
                       else replace(event, amount=amount, status=status))
    return tuple(patched)


# ------------------------------------------------------------------ tracing


@dataclass(frozen=True)
class RowTrace:
    """The audit sidecar for one request's assisted-mode attempt: retrieved
    ids, accepted/rejected facts, provider status, cache provenance, and usage.
    """

    request_id: str
    retrieved: tuple[str, ...]
    accepted: tuple[ExtractedFact, ...] = ()
    rejected: tuple[ExtractedFact, ...] = ()
    provider_status: str = "unavailable"
    usage: Optional[dict] = None
    cache_hit: bool = False
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict:
        def fact_json(f: ExtractedFact) -> dict:
            return {
                "field": f.field,
                "target_event_id": f.target_event_id,
                "target_scope": f.target_scope,
                "value": str(f.value) if f.value is not None else None,
                "currency": f.currency,
                "value_date": f.value_date.isoformat() if f.value_date else None,
                "source_ids": list(f.source_ids),
                "status": f.status,
                "reason": f.reason,
                "source_span": f.source_span,
                "conversion_note": f.conversion_note,
            }

        return {
            "request_id": self.request_id,
            "retrieved": list(self.retrieved),
            "accepted": [fact_json(f) for f in self.accepted],
            "rejected": [fact_json(f) for f in self.rejected],
            "provider_status": self.provider_status,
            "usage": self.usage,
            "cache_hit": self.cache_hit,
            "notes": list(self.notes),
        }


def citation_note(trace: RowTrace) -> Optional[str]:
    """A short, auditable note listing the evidence ids behind an
    assisted-mode decision, or `None` if there is nothing to cite.

    Only ids that are both on an *accepted* fact and present in
    `trace.retrieved` are ever emitted -- re-checked here rather than trusted
    from `resolve_fact` alone, so a caller can never surface a rejected or
    unretrieved id even if a future change to fact resolution regresses that
    guarantee. Returns `None` (never an empty citation) when no evidence
    changed the row, so a caller must not invent one.
    """
    retrieved = set(trace.retrieved)
    ids: list[str] = []
    for fact in trace.accepted:
        for source_id in fact.source_ids:
            if source_id in retrieved and source_id not in ids:
                ids.append(source_id)
    if not ids:
        return None
    return f"Evidence used: {', '.join(sorted(ids))}."
