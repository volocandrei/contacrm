"""Rutele de autentificare.

Contractul este cel pe care frontend-ul îl are deja în `api/endpoints.ts`:
`POST /auth/login` → `CurrentUser`, `POST /auth/logout` → `{ok}`, `GET /me` →
`CurrentUser`. Tokenurile călătoresc în cookie-uri httpOnly, deci corpul
răspunsului rămâne exact cel așteptat și frontend-ul nu are nimic de schimbat.
"""

from __future__ import annotations

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
from app.schemas.auth import CurrentUserOut, LoginRequest, LogoutResponse
from app.services.auth import AuthService, IssuedTokens

router = APIRouter(tags=["auth"])


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
    result = AuthService(session).login(
        payload.email,
        payload.password,
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
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
