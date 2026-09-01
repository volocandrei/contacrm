"""Logging structurat.

Fiecare linie de log este JSON în staging/producție și text lizibil în development.
Fiecare cerere primește un `request_id` care apare în toate liniile emise pe parcursul
ei și în corpul răspunsurilor de eroare — ca un incident raportat de utilizator să
poată fi găsit în log fără ghicit.

Regulă (§35): în log nu intră niciodată conținut de document, parole sau tokenuri.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import Environment, settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _inject_request_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging() -> None:
    """Se apelează o singură dată, la pornirea aplicației."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Mesajele aplicației sunt în română. Pe o consolă Windows (cp1252) un simplu
    # diacritic într-un mesaj de eroare ar arunca UnicodeEncodeError **din interiorul
    # loggerului** — adică exact atunci când ai cea mai mare nevoie de el.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # Uvicorn își are propriile handlere; le lăsăm să treacă prin structlog.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _inject_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if settings.environment is Environment.DEVELOPMENT
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
