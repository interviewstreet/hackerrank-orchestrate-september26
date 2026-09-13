"""Structured logging bound to a request id.

Secrets never reach the log: only model names, token counts and decision
fields are recorded, never API keys or raw credentials.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logger(verbose: bool = False) -> structlog.stdlib.BoundLogger:
    """Configure structlog once and return the root agent logger."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if verbose else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger("buy_or_wait")


def bind_request(request_id: str) -> None:
    """Attach a request id to every subsequent log line on this thread."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
