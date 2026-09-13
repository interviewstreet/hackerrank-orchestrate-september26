"""Reviewed, static financial facts extracted from linked PNG evidence.

Runtime OCR is deliberately not used: these values are reviewed evidence for the
specific blank event amounts in the supplied dataset.
"""

from decimal import Decimal

from .models import Currency

IMAGE_EVIDENCE_AMOUNTS: dict[str, tuple[Decimal, Currency]] = {
    "event_253": (Decimal("4365000"), "IDR"),
    "event_1442": (Decimal("100000"), "INR"),
    "event_1545": (Decimal("41272"), "INR"),
    "event_1700": (Decimal("2854"), "INR"),
    "event_1786": (Decimal("704.05"), "INR"),
    "event_3051": (Decimal("1995"), "INR"),
    "event_3231": (Decimal("8528.10"), "INR"),
    "event_4535": (Decimal("15339"), "INR"),
    "event_5170": (Decimal("723"), "INR"),
    "event_6033": (Decimal("79679.26"), "INR"),
    "event_6859": (Decimal("3650"), "INR"),
    "event_7307": (Decimal("33.50"), "USD"),
    "event_7941": (Decimal("2298"), "INR"),
    "event_9421": (Decimal("4543"), "INR"),
    "event_9806": (Decimal("9968"), "INR"),
    "event_10521": (Decimal("393.22"), "INR"),
}
