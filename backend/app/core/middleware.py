"""Middleware-ul aplicat fiecărei cereri.

Un singur `request_id` leagă între ele: liniile de log emise pe parcursul cererii,
antetul `X-Request-ID` din răspuns și câmpul `requestId` din corpul erorilor.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_var

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Nu logăm zgomotul de infrastructură.
_QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Un id venit din exterior este acceptat doar dacă arată a UUID, ca să nu
        # ajungă text arbitrar în log.
        request_id = _valid_uuid(request.headers.get(REQUEST_ID_HEADER)) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        # Resetul se face abia la final: liniile de log de mai jos trebuie să poarte
        # încă `request_id`.
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "request_failed",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=_elapsed_ms(started),
                )
                raise

            response.headers[REQUEST_ID_HEADER] = request_id
            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=_elapsed_ms(started),
                )
            return response
        finally:
            request_id_var.reset(token)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _valid_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None
