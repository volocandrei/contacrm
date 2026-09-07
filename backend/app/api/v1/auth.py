"""Rutele de autentificare.

Contractul este cel pe care frontend-ul îl are deja în `api/endpoints.ts`:
`POST /auth/login` → `CurrentUser`, `POST /auth/logout` → `{ok}`, `GET /me` →
`CurrentUser`. Tokenurile călătoresc în cookie-uri httpOnly, deci corpul
răspunsului rămâne exact cel așteptat și frontend-ul nu are nimic de schimbat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.api.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    CurrentUser,
    DbSession,
    client_ip,
    refresh_token_from,
)
from app.api.route import CommittingRoute
from app.core.config import settings
from app.core.errors import AppError, ErrorCode, ValidationError
from app.core.logging import get_logger
from app.core.rate_limit import FixedWindowLimiter
from app.domain.passwords import MIN_LENGTH, PasswordTooWeakError
from app.schemas.auth import CurrentUserOut, LoginRequest, LogoutResponse
from app.schemas.common import ApiModel
from app.services.auth import ActiveSession, AuthService, IssuedTokens

logger = get_logger(__name__)

router = APIRouter(route_class=CommittingRoute, tags=["auth"])

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


class PasswordChangeRequest(ApiModel):
    """Parola veche și cea nouă. Lungimea se verifică și aici, și în domeniu.

    Aici, ca cererea evident greșită să nu ajungă până la hashing; acolo, ca
    regula să rămână una singură indiferent pe ce drum se schimbă o parolă.
    """

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=MIN_LENGTH, max_length=1024)


@router.post("/auth/password", response_model=CurrentUserOut)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    session: DbSession,
    user: CurrentUser,
) -> CurrentUserOut:
    """Îți schimbi propria parolă.

    Este singurul drum prin care administratorul unei instalări proaspete își
    poate schimba parola: resetarea din *Administrare → Utilizatori* o face un
    administrator **altcuiva**, iar la început administratorul este unul singur.

    Reușita închide toate celelalte sesiuni și o deschide pe a ta din nou — vezi
    `AuthService.change_password` pentru de ce amândouă.
    """
    try:
        result = AuthService(session).change_password(
            user,
            payload.current_password,
            payload.new_password,
            ip=client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
    except PasswordTooWeakError as exc:
        # Toate motivele deodată: cine primește unul, îl repară și primește
        # următorul, încearcă a treia oară ceva ce i se putea spune din prima.
        raise ValidationError(" ".join(exc.reasons), {"newPassword": exc.reasons}) from exc

    _set_session_cookies(response, result.tokens)
    return result.user


class SessionOut(ApiModel):
    """O fereastră deschisă pe cont. Fără niciun token, nici măcar trunchiat."""

    id: str
    started_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


class RevokedOut(ApiModel):
    closed: int


def _session_out(item: ActiveSession) -> SessionOut:
    return SessionOut(
        # Id-ul familiei, nu al vreunui token: nu deschide nimic, dar identifică
        # rândul dacă cineva raportează ce a văzut pe ecran.
        id=str(item.family_id),
        started_at=item.started_at,
        last_seen_at=item.last_seen_at,
        expires_at=item.expires_at,
        ip=item.ip,
        user_agent=item.user_agent,
        current=item.current,
    )


@router.get("/auth/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, session: DbSession, user: CurrentUser) -> list[SessionOut]:
    """Ce ferestre sunt deschise pe contul meu, chiar acum.

    Întrebarea „mai are cineva sesiune pe contul meu?" nu avea până acum niciun
    răspuns în aplicație, iar ea se pune exact în ziua proastă: după un laptop
    lăsat deschis, după o parolă tastată pe alt calculator.
    """
    found = AuthService(session).sessions(user, current_token=refresh_token_from(request))
    return [_session_out(item) for item in found]


@router.post("/auth/sessions/revoke-others", response_model=RevokedOut)
def revoke_other_sessions(request: Request, session: DbSession, user: CurrentUser) -> RevokedOut:
    """Închide toate celelalte ferestre; a mea rămâne.

    Perechea butonului de mai sus: cine vede o sesiune pe care nu o recunoaște
    trebuie să o poată închide de acolo, nu prin schimbarea parolei.
    """
    closed = AuthService(session).revoke_other_sessions(
        user,
        refresh_token_from(request),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    return RevokedOut(closed=closed)


@router.get("/me", response_model=CurrentUserOut)
def me(user: CurrentUser, session: DbSession) -> CurrentUserOut:
    return AuthService(session).describe(user)
