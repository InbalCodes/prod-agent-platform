"""Structured logging.

All logs — ours and third-party (uvicorn, httpx, ...) — go through one stdlib
handler and one structlog formatter, so every line has the same shape:
JSON in deployed environments, human-readable console output locally.
"""

import logging
import sys

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from agent_platform.core.request_context import get_request_id


def _add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderers: list[Processor] = (
        [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
        if json_logs
        else [structlog.dev.ConsoleRenderer()]
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # Applied to records from stdlib loggers (uvicorn etc.) that didn't go through structlog.
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderers],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn's own logs through our formatter instead of its default one.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # We emit our own access log (with request_id and duration), so silence uvicorn's.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
