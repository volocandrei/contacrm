"""Rutele de autentificare.

Contractul este cel pe care frontend-ul îl are deja în `api/endpoints.ts`:
`POST /auth/login` → `CurrentUser`, `POST /auth/logout` → `{ok}`, `GET /me` →
`CurrentUser`. Tokenurile călătoresc în cookie-uri httpOnly, deci corpul
răspunsului rămâne exact cel așteptat și frontend-ul nu are nimic de schimbat.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Request, Response

from app.api.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    CurrentUser,
    DbSession,
    client_ip,
    refresh_token_from,
)
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.rate_limit import FixedWindowLimiter
from app.schemas.auth import CurrentUserOut, LoginRequest, LogoutResponse
from app.services.auth import AuthService, IssuedTokens

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])

#: Contoare per proces. Vezi `app/core/rate_limit.py` pentru ce acoperă (o
#: instalare cu un proces de API) și ce nu (mai multe procese, sau o platformă
#: care pornește un proces per cerere).
#:
#: Două, nu unul, pentru că sunt două atacuri diferite: multe parole pe un cont,
#: și o parolă pe multe conturi.
LOGIN_LIMITERS: Final = {
    "cont": FixedWindowLimiter(limit=settings.login_attempts_per_minute),
    "adresa": FixedWindowLimiter(limit=settings.login_attempts_per_address_per_minute),
}


def _login_keys(request: Request, email: str) -> list[tuple[FixedWindowLimiter, str]]:
    """Cele două chei sub care se numără eșecurile unei încercări.

    Adresa vine prin aceeași regulă ca în jurnalul de audit, deci un antet
    `X-Forwarded-For` se citește doar dacă cineva a declarat câte proxy-uri stau în
    față. Fără asta, oricine și-ar alege o adresă nouă la fiecare încercare.

    Cheia contului include adresa: un contor legat numai de cont ar lăsa pe oricine
    să blocheze de la distanță autentificarea unui contabil, adică ar transforma
    protecția într-un atac.
    """
    address = client_ip(request) or "necunoscut"
    return [
        (LOGIN_LIMITERS["cont"], f"{address}|{email.strip().lower()}"),
        (LOGIN_LIMITERS["adresa"], address),
    ]


def _refuse_if_blocked(keys: list[tuple[FixedWindowLimiter, str]], *, address: str) -> None:
    """Prea multe eșecuri, prea repede. Se verifică **înainte** de a atinge parola."""
    refused = [decision for limiter, key in keys if not (decision := limiter.blocked(key)).allowed]
    if not refused:
        return

    logger.warning("login_rate_limited", ip=address)
    raise AppError(
        ErrorCode.RATE_LIMITED,
        "Prea multe încercări eșuate. Așteaptă un minut și încearcă din nou.",
        headers={"Retry-After": str(max(d.retry_after for d in refused))},
    )


def _set_session_cookies(response: Response, tokens: IssuedTokens) -> None:
    """Cookie-uri de sesiune.

    `httponly` — JavaScript-ul paginii nu le poate citi, deci un XSS nu le poate fura.
    `samesite=lax` — nu pleacă la cereri cross-site declanșate de alt site (CSRF).
    `secure` doar în afara development-ului: pe http://localhost browserul ar
    refuza un cookie `Secure`.
    """
    common = {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment.value != "development",
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        **common,  # type: ignore[arg-type]
    )


def _clear_session_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/")


@router.post("/auth/login", response_model=CurrentUserOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> CurrentUserOut:
    address = client_ip(request) or "necunoscut"
    keys = _login_keys(request, payload.email)
    _refuse_if_blocked(keys, address=address)

    try:
        result = AuthService(session).login(
            payload.email,
            payload.password,
            ip=address,
            user_agent=request.headers.get("User-Agent"),
        )
    except AppError:
        # Se numără **eșecul**, nu încercarea: o autentificare reușită nu are de ce
        # să apropie utilizatorul de un refuz.
        for limiter, key in keys:
            limiter.record(key)
        raise

    _set_session_cookies(response, result.tokens)
    return result.user


@router.post("/auth/refresh", response_model=CurrentUserOut)
def refresh(request: Request, response: Response, session: DbSession) -> CurrentUserOut:
    token = refresh_token_from(request)
    result = AuthService(session).refresh(
        token or "",
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    _set_session_cookies(response, result.tokens)
    return result.user


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(request: Request, response: Response, session: DbSession) -> LogoutResponse:
    """Deconectarea reușește și fără sesiune validă — altfel un token expirat ar
    lăsa utilizatorul blocat cu cookie-uri pe care nu le poate șterge."""
    user = None
    try:
        from app.api.deps import get_current_user

        user = get_current_user(request, session)
    except Exception:  # logout nu trebuie să eșueze, oricare ar fi starea sesiunii
        user = None

    AuthService(session).logout(refresh_token_from(request), user)
    _clear_session_cookies(response)
    return LogoutResponse()


@router.get("/me", response_model=CurrentUserOut)
def me(user: CurrentUser, session: DbSession) -> CurrentUserOut:
    return AuthService(session).describe(user)
