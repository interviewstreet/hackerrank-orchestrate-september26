"""Strict dataset loading, typed parsing, indexing, and input hashing.

Design rules, in priority order:

1. **Fail loudly at load time.** A malformed decimal, an unknown enum value, a
   duplicate ID or an unexpected header is a dataset-level error and stops the
   run before anything is published. It is never coerced into a default.
2. **Unknown is not zero.** Only the columns explicitly allowed to be blank may
   be blank, and they parse to `None`.
3. **Labels never cross the prediction boundary.** `load_dataset()` reads
   `sample_requests.csv` for its *input* columns only. The label columns are
   read by `code/evaluation/labels.py` and by nothing else.
4. **Order is deterministic.** Every index preserves file order; nothing in a
   read path iterates a set.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from .money import MoneyError, parse_decimal
from .schema import (
    CURRENCIES,
    DIRECTIONS,
    EVENT_CATEGORIES,
    EVENT_STATUSES,
    EVENT_TYPES,
    FLEXIBILITIES,
    OUTPUT_COLUMNS,
    PAYMENT_OPTION_METHODS,
    REQUEST_INPUT_COLUMNS,
    REQUEST_TYPES,
    SAMPLE_COLUMNS,
    SOURCE_TYPES,
    ExchangeRate,
    FinancialEvent,
    ImageRef,
    Message,
    PaymentOption,
    Profile,
    RequestContext,
    RequestInput,
)

#: Payment methods a profile may declare (a subset of the output methods --
#: `wait` and `not_recommended` are outcomes, not user preferences).
CONSIDERABLE_METHODS: frozenset[str] = frozenset({
    "full_payment", "partial_payment", "installments",
})

EXPECTED_HEADERS: dict[str, tuple[str, ...]] = {
    "requests.csv": REQUEST_INPUT_COLUMNS,
    "sample_requests.csv": SAMPLE_COLUMNS,
    "output.csv": OUTPUT_COLUMNS,
    "financial_profiles.csv": (
        "user_id", "home_currency", "current_available_balance",
        "minimum_balance_to_keep", "financial_priorities",
        "expense_categories_to_protect",
        "expense_categories_user_is_willing_to_reduce",
        "expense_categories_user_is_willing_to_stop",
        "payment_methods_user_will_consider", "max_installment_months",
    ),
    "financial_events.csv": (
        "event_id", "user_id", "event_type", "description", "category",
        "direction", "amount", "currency", "event_date", "settlement_date",
        "status", "linked_event_id", "flexibility", "minimum_allowed_amount",
    ),
    "request_payment_options.csv": (
        "payment_option_id", "request_id", "payment_method", "payment_amount",
        "number_of_payments", "first_payment_date", "payment_frequency_days",
        "financing_fee", "total_payable_amount",
    ),
    "messages.csv": (
        "message_id", "user_id", "request_id", "related_event_id", "sent_at",
        "source_type", "message_text",
    ),
    "images.csv": ("image_id", "user_id", "request_id", "related_event_id"),
    "exchange_rates.csv": ("rate_date", "from_currency", "to_currency", "rate"),
}

#: Files the engine cannot run without.
REQUIRED_FILES: tuple[str, ...] = (
    "requests.csv", "financial_profiles.csv", "financial_events.csv",
    "request_payment_options.csv", "messages.csv", "images.csv",
    "exchange_rates.csv",
)

#: The contract says `YYYY-MM-DD`. `date.fromisoformat` alone is NOT sufficient:
#: it is strict on Python 3.10 but accepts `20240303` and ISO week dates such as
#: `2024-W09-7` on 3.11+. Validating the shape first makes the loader behave
#: identically on every interpreter (review finding R-M0-06).
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: An image id must be a single safe path component. Without this, an id such as
#: `../../../etc/passwd` would resolve outside the dataset (R-M0-02).
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

#: Sentinel key under which csv.DictReader collects surplus cells.
_SURPLUS = "__surplus__"


class DataError(ValueError):
    """A dataset-level problem that must stop the run before publication."""


# ----------------------------------------------------------- primitives ------


def _where(source: str, row_no: int, column: str) -> str:
    return f"{source}:{row_no} [{column}]"


def parse_text(raw: Optional[str]) -> str:
    return (raw or "").strip()


def parse_optional_text(raw: Optional[str]) -> Optional[str]:
    value = parse_text(raw)
    return value or None


def parse_date_value(raw: Optional[str], *, where: str, allow_blank: bool = False) -> Optional[date]:
    """Parse a `YYYY-MM-DD` cell, rejecting every other shape.

    The explicit shape check is load-bearing, not belt-and-braces: on Python
    3.11+ `date.fromisoformat` also accepts `20240303` and ISO week dates like
    `2024-W09-7`, so relying on it alone would make the loader's strictness
    depend on the interpreter. Settlement dates, deadlines and forecast
    boundaries all flow from this parse.
    """
    text = parse_text(raw)
    if not text:
        if allow_blank:
            return None
        raise DataError(f"{where}: blank date where a value is required")
    if not _ISO_DATE.match(text):
        raise DataError(f"{where}: {text!r} is not a YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise DataError(f"{where}: {text!r} is not a valid calendar date") from exc
    return parsed


def try_parse_iso_date(text: str) -> Optional[date]:
    """The same strict `YYYY-MM-DD` shape check as `parse_date_value`, but
    returns `None` on any failure instead of raising `DataError`.

    For a caller validating an untrusted, non-CSV value (e.g. `evidence.py`
    typing a model-proposed date) where the correct response to an invalid
    shape is "reject this one fact", not "stop the whole run".
    """
    if not _ISO_DATE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_safe_id(raw: Optional[str], *, where: str) -> str:
    """Parse an identifier that will be used to build a filesystem path.

    Rejects path separators, `..`, absolute paths, drive letters and anything
    outside `[A-Za-z0-9_-]`, so a malformed dataset cannot steer a later read
    outside `dataset/media/` (R-M0-02).
    """
    text = parse_text(raw)
    if not text:
        raise DataError(f"{where}: blank identifier")
    if not _SAFE_ID.match(text):
        raise DataError(
            f"{where}: {text!r} is not a safe identifier "
            f"(letters, digits, underscore and hyphen only; no path separators)"
        )
    return text


def safe_media_path(media_dir: Path, image_id: str) -> Path:
    """Resolve `<media_dir>/<image_id>.png`, proving the result stays inside.

    Two independent guards, because containment alone is not enough: an id of
    `..` yields the perfectly contained filename `..png`, and an id of `image_01`
    on a caller-supplied directory could still point anywhere. So the id shape is
    re-validated here as well as at load time, and then the resolved path is
    proven to sit directly inside `media_dir`. The model layer must use this
    function rather than joining paths itself.
    """
    image_id = parse_safe_id(image_id, where="image_id")
    media_dir = Path(media_dir).resolve()
    candidate = (media_dir / f"{image_id}.png").resolve()
    if candidate.parent != media_dir:
        raise DataError(f"image_id {image_id!r} resolves outside {media_dir}")
    return candidate


def parse_bool_value(raw: Optional[str], *, where: str) -> bool:
    """Parse `true` / `false`, case-insensitively. Nothing else is accepted.

    Case is a formatting difference; `1`, `yes`, `y` and blank are semantic
    guesses. This column decides `allows_partial_payment`, so a silent
    truthiness coercion would flip payment-method eligibility on 80 requests.
    """
    text = parse_text(raw).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise DataError(f"{where}: {raw!r} is not 'true' or 'false'")


def parse_int_value(raw: Optional[str], *, where: str, allow_blank: bool = False) -> Optional[int]:
    """Parse an integer cell, tolerating a trailing `.0` (some exports write
    whole numbers as floats) but never a genuine fraction."""
    text = parse_text(raw)
    if not text:
        if allow_blank:
            return None
        raise DataError(f"{where}: blank integer where a value is required")
    try:
        value = Decimal(text)
    except Exception as exc:  # noqa: BLE001 - Decimal raises several types
        raise DataError(f"{where}: {text!r} is not an integer") from exc
    if value != value.to_integral_value():
        raise DataError(f"{where}: {text!r} is not a whole number")
    return int(value)


def parse_enum_value(raw: Optional[str], allowed: Iterable[str], *, where: str) -> str:
    value = parse_text(raw)
    if value not in allowed:
        raise DataError(f"{where}: {value!r} is not one of {sorted(allowed)}")
    return value


def parse_pipe_set(raw: Optional[str], allowed: Iterable[str], *, where: str) -> frozenset[str]:
    """Parse a `a|b|c` cell, validating each token. Blank yields an empty set --
    e.g. 39 profiles list nothing they are willing to reduce."""
    tokens = [t.strip() for t in parse_text(raw).split("|") if t.strip()]
    allowed = set(allowed)
    for token in tokens:
        if token not in allowed:
            raise DataError(f"{where}: {token!r} is not one of {sorted(allowed)}")
    return frozenset(tokens)


def parse_money(raw: Optional[str], *, where: str, allow_blank: bool = False) -> Optional[Decimal]:
    """Parse a monetary cell exactly, preserving the source precision.

    No rounding happens here. Quantization is an output policy applied to values
    the engine computes -- rounding a supplied rate or amount at load time would
    change the arithmetic the problem statement tells us to perform (R-M0-04).
    """
    try:
        return parse_decimal(raw, field=where, allow_blank=allow_blank)
    except MoneyError as exc:
        raise DataError(str(exc)) from exc


def read_rows(path: Path, expected_header: Sequence[str]) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield `(1-based data row number, row)` after checking the header *and*
    every row's width.

    The width check is not redundant with the header check. `csv.DictReader`
    silently tolerates malformed rows: surplus cells land under a single catch-all
    key and a truncated row back-fills missing columns with `None`. Either case
    would reach typed parsing as a plausible-looking record -- a shifted row can
    move an amount into a date column, and a truncated row can turn a real
    obligation into a blank (R-M0-01).

    `utf-8-sig` because a BOM on the first header cell would silently rename
    `request_id` and make every lookup miss.
    """
    if not path.exists():
        raise DataError(f"{path.name}: required file is missing at {path}")
    width = len(expected_header)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, restkey=_SURPLUS, restval=None)
        actual = tuple(reader.fieldnames or ())
        if actual != tuple(expected_header):
            raise DataError(
                f"{path.name}: unexpected header\n  expected: {list(expected_header)}\n"
                f"  actual:   {list(actual)}"
            )
        for offset, row in enumerate(reader, start=1):
            surplus = row.pop(_SURPLUS, None)
            if surplus:
                raise DataError(
                    f"{path.name}:{offset}: row has {width + len(surplus)} cells, expected {width} "
                    f"(surplus: {surplus!r})"
                )
            missing = [column for column, value in row.items() if value is None]
            if missing:
                raise DataError(
                    f"{path.name}:{offset}: row is truncated, missing cell(s) for {missing}"
                )
            yield offset, row


def file_sha256(path: Path) -> str:
    """Raw-byte identity: changes with line-ending style, not just content."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_content_sha256(path: Path) -> str:
    """Content identity that survives a CRLF/LF checkout difference.

    Used to gate the frozen split manifest (`evaluation/splits.py`): a clone
    on Linux/browser CI must not fail because `sample_requests.csv` was
    checked out with different line endings than the machine that froze the
    manifest. Normalizes `\\r\\n` and a bare `\\r` to `\\n` before hashing;
    an actual value change (a differing byte once newlines are normalized)
    still changes this hash.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        data = handle.read()
    digest.update(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return digest.hexdigest()


# -------------------------------------------------------------- loaders ------


def load_requests(path: Path, *, source: str) -> list[RequestInput]:
    """Load request *inputs*. Used for both `requests.csv` and the input half of
    `sample_requests.csv` -- the label columns are simply not read here."""
    header = EXPECTED_HEADERS[source]
    out: list[RequestInput] = []
    for line, row in read_rows(path, header):
        rid = parse_text(row["request_id"])
        if not rid:
            raise DataError(f"{source}:{line}: blank request_id")
        request_date = parse_date_value(row["request_date"], where=_where(source, line, "request_date"))
        completion = parse_date_value(
            row["desired_completion_date"], where=_where(source, line, "desired_completion_date")
        )
        assert request_date is not None and completion is not None
        if completion < request_date:
            raise DataError(
                f"{source}:{line}: desired_completion_date {completion} precedes request_date {request_date}"
            )
        amount = parse_money(row["requested_amount"], where=_where(source, line, "requested_amount"))
        assert amount is not None
        if amount <= 0:
            raise DataError(f"{source}:{line}: requested_amount must be positive, got {amount}")
        out.append(RequestInput(
            request_id=rid,
            user_id=parse_text(row["user_id"]),
            request_date=request_date,
            request_type=parse_enum_value(
                row["request_type"], REQUEST_TYPES, where=_where(source, line, "request_type")
            ),
            requested_amount=amount,
            desired_completion_date=completion,
            allows_partial_payment=parse_bool_value(
                row["allows_partial_payment"], where=_where(source, line, "allows_partial_payment")
            ),
            request_text=parse_text(row["request_text"]),
        ))
    return out


def load_profiles(path: Path) -> list[Profile]:
    source = "financial_profiles.csv"
    out: list[Profile] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        balance = parse_money(
            row["current_available_balance"], where=_where(source, line, "current_available_balance")
        )
        minimum = parse_money(
            row["minimum_balance_to_keep"], where=_where(source, line, "minimum_balance_to_keep")
        )
        assert balance is not None and minimum is not None
        months = parse_int_value(
            row["max_installment_months"], where=_where(source, line, "max_installment_months"),
            allow_blank=True,
        )
        if months is not None and months <= 0:
            raise DataError(f"{source}:{line}: max_installment_months must be positive when present")
        # Priorities are a ranking preference, not an authorization: no priority
        # token can unlock a payment method or permit a spending change. An
        # unknown value here therefore cannot make an unsafe decision possible,
        # so it is accepted and reported by audit.py (A01, warning) rather than
        # failing the run. The categories that DO authorize interventions
        # (protect / reduce / stop, below) are validated strictly.
        priorities = tuple(
            t.strip() for t in parse_text(row["financial_priorities"]).split("|") if t.strip()
        )
        out.append(Profile(
            user_id=parse_text(row["user_id"]),
            home_currency=parse_enum_value(
                row["home_currency"], CURRENCIES, where=_where(source, line, "home_currency")
            ),
            current_available_balance=balance,
            minimum_balance_to_keep=minimum,
            financial_priorities=priorities,
            expense_categories_to_protect=parse_pipe_set(
                row["expense_categories_to_protect"], EVENT_CATEGORIES,
                where=_where(source, line, "expense_categories_to_protect"),
            ),
            expense_categories_user_is_willing_to_reduce=parse_pipe_set(
                row["expense_categories_user_is_willing_to_reduce"], EVENT_CATEGORIES,
                where=_where(source, line, "expense_categories_user_is_willing_to_reduce"),
            ),
            expense_categories_user_is_willing_to_stop=parse_pipe_set(
                row["expense_categories_user_is_willing_to_stop"], EVENT_CATEGORIES,
                where=_where(source, line, "expense_categories_user_is_willing_to_stop"),
            ),
            payment_methods_user_will_consider=parse_pipe_set(
                row["payment_methods_user_will_consider"], CONSIDERABLE_METHODS,
                where=_where(source, line, "payment_methods_user_will_consider"),
            ),
            max_installment_months=months,
        ))
    return out


def load_events(path: Path) -> list[FinancialEvent]:
    source = "financial_events.csv"
    out: list[FinancialEvent] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        event_date = parse_date_value(row["event_date"], where=_where(source, line, "event_date"))
        assert event_date is not None
        settlement = parse_date_value(
            row["settlement_date"], where=_where(source, line, "settlement_date"), allow_blank=True
        )
        if settlement is not None and settlement < event_date:
            raise DataError(f"{source}:{line}: settlement_date {settlement} precedes event_date {event_date}")
        flexibility = parse_enum_value(
            row["flexibility"], FLEXIBILITIES, where=_where(source, line, "flexibility")
        )
        floor = parse_money(
            row["minimum_allowed_amount"], where=_where(source, line, "minimum_allowed_amount"),
            allow_blank=True,
        )
        out.append(FinancialEvent(
            event_id=parse_text(row["event_id"]),
            user_id=parse_text(row["user_id"]),
            event_type=parse_enum_value(
                row["event_type"], EVENT_TYPES, where=_where(source, line, "event_type")
            ),
            description=parse_text(row["description"]),
            category=parse_enum_value(
                row["category"], EVENT_CATEGORIES, where=_where(source, line, "category")
            ),
            direction=parse_enum_value(
                row["direction"], DIRECTIONS, where=_where(source, line, "direction")
            ),
            # Blank is permitted and means UNKNOWN -- resolved from the linked
            # image in M2, never defaulted to zero.
            amount=parse_money(row["amount"], where=_where(source, line, "amount"), allow_blank=True),
            currency=parse_enum_value(
                row["currency"], CURRENCIES, where=_where(source, line, "currency")
            ),
            event_date=event_date,
            settlement_date=settlement,
            status=parse_enum_value(
                row["status"], EVENT_STATUSES, where=_where(source, line, "status")
            ),
            linked_event_id=parse_optional_text(row["linked_event_id"]),
            flexibility=flexibility,
            minimum_allowed_amount=floor,
        ))
    return out


def load_payment_options(path: Path) -> list[PaymentOption]:
    source = "request_payment_options.csv"
    out: list[PaymentOption] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        method = parse_enum_value(
            row["payment_method"], PAYMENT_OPTION_METHODS, where=_where(source, line, "payment_method")
        )
        count = parse_int_value(
            row["number_of_payments"], where=_where(source, line, "number_of_payments")
        )
        assert count is not None
        if count < 1:
            raise DataError(f"{source}:{line}: number_of_payments must be >= 1")
        frequency = parse_int_value(
            row["payment_frequency_days"], where=_where(source, line, "payment_frequency_days"),
            allow_blank=True,
        )
        if count > 1 and frequency is None:
            raise DataError(f"{source}:{line}: multi-payment offer has no payment_frequency_days")
        if frequency is not None and frequency <= 0:
            raise DataError(f"{source}:{line}: payment_frequency_days must be positive")
        first = parse_date_value(
            row["first_payment_date"], where=_where(source, line, "first_payment_date")
        )
        amount = parse_money(row["payment_amount"], where=_where(source, line, "payment_amount"))
        fee = parse_money(row["financing_fee"], where=_where(source, line, "financing_fee"))
        total = parse_money(row["total_payable_amount"], where=_where(source, line, "total_payable_amount"))
        assert first is not None and amount is not None and fee is not None and total is not None
        out.append(PaymentOption(
            payment_option_id=parse_text(row["payment_option_id"]),
            request_id=parse_text(row["request_id"]),
            payment_method=method,
            payment_amount=amount,
            number_of_payments=count,
            first_payment_date=first,
            payment_frequency_days=frequency,
            financing_fee=fee,
            total_payable_amount=total,
        ))
    return out


def load_messages(path: Path) -> list[Message]:
    source = "messages.csv"
    out: list[Message] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        sent_at = parse_text(row["sent_at"])
        # Validate the shape without inventing a user timezone: we keep the
        # string verbatim and only prove it is parseable ISO-8601.
        try:
            datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataError(f"{_where(source, line, 'sent_at')}: {sent_at!r} is not ISO-8601") from exc
        out.append(Message(
            message_id=parse_text(row["message_id"]),
            user_id=parse_text(row["user_id"]),
            request_id=parse_optional_text(row["request_id"]),
            related_event_id=parse_optional_text(row["related_event_id"]),
            sent_at=sent_at,
            source_type=parse_enum_value(
                row["source_type"], SOURCE_TYPES, where=_where(source, line, "source_type")
            ),
            message_text=row["message_text"] or "",
        ))
    return out


def load_images(path: Path) -> list[ImageRef]:
    source = "images.csv"
    out: list[ImageRef] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        # Validated as a path component here because `<image_id>.png` becomes a
        # filesystem read in M2; see `safe_media_path`.
        image_id = parse_safe_id(row["image_id"], where=_where(source, line, "image_id"))
        out.append(ImageRef(
            image_id=image_id,
            user_id=parse_text(row["user_id"]),
            request_id=parse_optional_text(row["request_id"]),
            related_event_id=parse_optional_text(row["related_event_id"]),
        ))
    return out


def load_exchange_rates(path: Path) -> list[ExchangeRate]:
    source = "exchange_rates.csv"
    out: list[ExchangeRate] = []
    for line, row in read_rows(path, EXPECTED_HEADERS[source]):
        rate = parse_money(row["rate"], where=_where(source, line, "rate"))
        assert rate is not None
        if rate <= 0:
            raise DataError(f"{source}:{line}: rate must be positive")
        rate_date = parse_date_value(row["rate_date"], where=_where(source, line, "rate_date"))
        assert rate_date is not None
        frm = parse_enum_value(row["from_currency"], CURRENCIES, where=_where(source, line, "from_currency"))
        to = parse_enum_value(row["to_currency"], CURRENCIES, where=_where(source, line, "to_currency"))
        if frm == to:
            raise DataError(f"{source}:{line}: identity conversion {frm}->{to} should not be a data row")
        out.append(ExchangeRate(rate_date=rate_date, from_currency=frm, to_currency=to, rate=rate))
    return out


# -------------------------------------------------------------- dataset ------


@dataclass(frozen=True)
class DataSet:
    """Indexed, validated dataset. Immutable once loaded."""

    dataset_dir: Path
    requests: tuple[RequestInput, ...]
    sample_requests: tuple[RequestInput, ...]
    profiles: tuple[Profile, ...]
    events: tuple[FinancialEvent, ...]
    payment_options: tuple[PaymentOption, ...]
    messages: tuple[Message, ...]
    images: tuple[ImageRef, ...]
    exchange_rates: tuple[ExchangeRate, ...]
    #: sha256 of every input CSV.
    manifest: dict[str, str]
    #: sha256 of every supplied media file, keyed by dataset-relative path.
    media_manifest: dict[str, str]

    # -- indexes (file order preserved everywhere) --
    profiles_by_user: dict[str, Profile]
    events_by_user: dict[str, tuple[FinancialEvent, ...]]
    events_by_id: dict[str, FinancialEvent]
    messages_by_user: dict[str, tuple[Message, ...]]
    images_by_user: dict[str, tuple[ImageRef, ...]]
    images_by_event: dict[str, tuple[ImageRef, ...]]
    options_by_request: dict[str, tuple[PaymentOption, ...]]
    rates_by_key: dict[tuple[date, str, str], ExchangeRate]
    #: Every known request, evaluation and sample, keyed by id. The authority on
    #: which user owns which request.
    requests_by_id: dict[str, RequestInput]

    @property
    def media_dir(self) -> Path:
        return self.dataset_dir / "media" / "images"

    def media_path(self, image: ImageRef) -> Path:
        """Containment-checked path to an image's bytes."""
        return safe_media_path(self.media_dir, image.image_id)

    def request_owner(self, request_id: str) -> Optional[str]:
        known = self.requests_by_id.get(request_id)
        return known.user_id if known else None

    def context_for(self, request_id: str) -> RequestContext:
        """Preferred entry point: look the request up, then scope it."""
        known = self.requests_by_id.get(request_id)
        if known is None:
            raise DataError(f"unknown request_id {request_id!r}")
        return self.request_context(known)

    def request_context(self, request: RequestInput) -> RequestContext:
        """Assemble the request-scoped view.

        Scoping: user-level records come from the user's index; records that
        carry their own `request_id` are admitted only when it matches *and*
        that request belongs to the same user, so one request never sees
        another request's -- or another user's -- evidence.

        The request object must be one this dataset loaded. A caller that
        assembles its own `RequestInput` could otherwise pair a known request id
        with a different user's id and receive a mixed-user financial state:
        user B's profile and events alongside request A's payment options
        (R-M0-07). M1 should not have to trust its callers for that.
        """
        known = self.requests_by_id.get(request.request_id)
        if known is None:
            raise DataError(f"{request.request_id}: not a request in this dataset")
        if known != request:
            raise DataError(
                f"{request.request_id}: request object does not match the loaded record "
                f"(loaded user {known.user_id}, supplied user {request.user_id}); "
                f"use DataSet.context_for(request_id)"
            )
        profile = self.profiles_by_user.get(request.user_id)
        if profile is None:
            raise DataError(f"{request.request_id}: no profile for user {request.user_id}")
        def in_scope(record_request_id: Optional[str]) -> bool:
            # User-level evidence (blank request_id) is in scope. A
            # request-linked record is in scope only when it names THIS request
            # and that request is owned by this user -- the second half is a
            # backstop for the audit's cross-user check (R-M0-03).
            if record_request_id is None:
                return True
            if record_request_id != request.request_id:
                return False
            return self.request_owner(record_request_id) == request.user_id

        messages = tuple(
            m for m in self.messages_by_user.get(request.user_id, ()) if in_scope(m.request_id)
        )
        images = tuple(
            i for i in self.images_by_user.get(request.user_id, ()) if in_scope(i.request_id)
        )
        return RequestContext(
            request=request,
            profile=profile,
            events=self.events_by_user.get(request.user_id, ()),
            messages=messages,
            images=images,
            payment_options=self.options_by_request.get(request.request_id, ()),
        )


def _group(rows: Iterable, key: str) -> dict[str, tuple]:
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(getattr(row, key), []).append(row)
    return {k: tuple(v) for k, v in grouped.items()}


def _unique_index(rows: Sequence, key: str, source: str) -> dict[str, object]:
    index: dict[str, object] = {}
    for row in rows:
        value = getattr(row, key)
        if value in index:
            raise DataError(f"{source}: duplicate {key} {value!r}")
        index[value] = row
    return index


def load_dataset(dataset_dir: Path) -> DataSet:
    """Load and validate the whole dataset, or raise `DataError`."""
    dataset_dir = Path(dataset_dir)
    if not dataset_dir.is_dir():
        raise DataError(f"dataset directory not found: {dataset_dir}")

    missing = [name for name in REQUIRED_FILES if not (dataset_dir / name).exists()]
    if missing:
        raise DataError(f"missing required dataset file(s): {', '.join(sorted(missing))}")

    requests = load_requests(dataset_dir / "requests.csv", source="requests.csv")
    sample_path = dataset_dir / "sample_requests.csv"
    samples = (
        load_requests(sample_path, source="sample_requests.csv") if sample_path.exists() else []
    )
    profiles = load_profiles(dataset_dir / "financial_profiles.csv")
    events = load_events(dataset_dir / "financial_events.csv")
    options = load_payment_options(dataset_dir / "request_payment_options.csv")
    messages = load_messages(dataset_dir / "messages.csv")
    images = load_images(dataset_dir / "images.csv")
    rates = load_exchange_rates(dataset_dir / "exchange_rates.csv")

    _unique_index(requests, "request_id", "requests.csv")
    _unique_index(samples, "request_id", "sample_requests.csv")
    overlap = {r.request_id for r in requests} & {s.request_id for s in samples}
    if overlap:
        raise DataError(f"sample_requests.csv reuses evaluation request_id(s): {sorted(overlap)}")

    events_by_id = _unique_index(events, "event_id", "financial_events.csv")
    profiles_by_user = _unique_index(profiles, "user_id", "financial_profiles.csv")
    _unique_index(options, "payment_option_id", "request_payment_options.csv")
    _unique_index(messages, "message_id", "messages.csv")
    _unique_index(images, "image_id", "images.csv")

    rates_by_key: dict[tuple[date, str, str], ExchangeRate] = {}
    for rate in rates:
        key = (rate.rate_date, rate.from_currency, rate.to_currency)
        if key in rates_by_key:
            raise DataError(f"exchange_rates.csv: duplicate rate for {key}")
        rates_by_key[key] = rate

    manifest = {
        name: file_sha256(dataset_dir / name)
        for name in sorted(EXPECTED_HEADERS)
        if (dataset_dir / name).exists()
    }

    # Media bytes are hashed separately from the CSVs. `images.csv` records only
    # the metadata, so editing a PNG in place would otherwise leave the manifest
    # unchanged and let a final run be attributed to image content it never read
    # (R-M0-05). Kept in its own map so provenance can distinguish "the index
    # changed" from "the evidence changed".
    media_dir = dataset_dir / "media" / "images"
    media_manifest: dict[str, str] = {}
    for image in sorted(images, key=lambda i: i.image_id):
        path = safe_media_path(media_dir, image.image_id)
        if path.exists():
            media_manifest[f"media/images/{image.image_id}.png"] = file_sha256(path)

    requests_by_id: dict[str, RequestInput] = {r.request_id: r for r in requests}
    requests_by_id.update({r.request_id: r for r in samples})

    return DataSet(
        dataset_dir=dataset_dir,
        requests=tuple(requests),
        sample_requests=tuple(samples),
        profiles=tuple(profiles),
        events=tuple(events),
        payment_options=tuple(options),
        messages=tuple(messages),
        images=tuple(images),
        exchange_rates=tuple(rates),
        manifest=manifest,
        media_manifest=media_manifest,
        profiles_by_user=profiles_by_user,           # type: ignore[arg-type]
        events_by_user=_group(events, "user_id"),
        events_by_id=events_by_id,                   # type: ignore[arg-type]
        messages_by_user=_group(messages, "user_id"),
        images_by_user=_group(images, "user_id"),
        images_by_event=_group([i for i in images if i.related_event_id], "related_event_id"),
        options_by_request=_group(options, "request_id"),
        rates_by_key=rates_by_key,
        requests_by_id=requests_by_id,
    )
