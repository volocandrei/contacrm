"""Middleware-ul aplicat fiecărei cereri.

Două lucruri, amândouă valabile pentru orice rută: contextul de cerere
(`request_id`) și antetele de securitate.

Un singur `request_id` leagă între ele: liniile de log emise pe parcursul cererii,
antetul `X-Request-ID` din răspuns și câmpul `requestId` din corpul erorilor.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Environment, settings
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


# ── Antete de securitate ─────────────────────────────────────────────────────

#: Antetele puse pe **orice** răspuns al API-ului.
#:
#: Existau deja, dar numai în două locuri: pe fișierele servite
#: (`document_delivery.SECURITY_HEADERS`) și în `vercel.json`, adică doar pentru
#: instalarea de pe Vercel. O instalare pe serverul cabinetului — `docker compose`,
#: exact varianta din documentație — nu avea niciunul. Locul lor este aplicația:
#: acolo nu depind de cine o pune în fața ei.
SECURITY_HEADERS: Final[dict[str, str]] = {
    # Browserul nu are voie să ghicească alt tip decât cel declarat.
    "X-Content-Type-Options": "nosniff",
    # Nicio pagină străină nu poate încadra aplicația (clickjacking). `X-Frame-Options`
    # pentru browserele vechi, `frame-ancestors` pentru cele care îl citesc.
    "X-Frame-Options": "DENY",
    # Adresele conțin id-uri de documente și de clienți: nu pleacă spre alte site-uri.
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    # Răspunsurile API-ului sunt JSON; nimic din ele nu are voie să încarce nimic.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}

#: Doar peste HTTPS. Trimis pe `http://localhost`, ar bloca development-ul: browserul
#: ține minte antetul și refuză apoi orice cerere necriptată către aceeași gazdă.
HSTS_HEADER: Final = "Strict-Transport-Security"
HSTS_VALUE: Final = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Pune antetele de mai sus pe orice răspuns care nu le are deja.

    „Care nu le are deja" contează: fișierele servite prin `/documents/{id}/preview`
    își aduc propria politică, mai strictă (`sandbox`), iar aceea nu trebuie
    înlocuită cu una mai permisivă.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.environment is not Environment.DEVELOPMENT:
            response.headers.setdefault(HSTS_HEADER, HSTS_VALUE)
        return response
