"""Dependențele de autentificare și autorizare.

Tokenul de acces este citit din cookie-ul httpOnly (browser) sau din antetul
`Authorization: Bearer` (clienți programatici). Cookie-ul e preferat pentru browser
pentru că JavaScript-ul paginii nu îl poate citi, deci un XSS nu îl poate fura.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import TokenError, decode_token
from app.domain.permissions import Permission, permissions_for
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.storage import StorageProvider
from app.services.storage.factory import get_storage_provider

ACCESS_COOKIE = "contacrm_access"
REFRESH_COOKIE = "contacrm_refresh"

DbSession = Annotated[Session, Depends(get_db)]


def access_token_from(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.removeprefix("Bearer ").strip() or None
    return request.cookies.get(ACCESS_COOKIE)


def refresh_token_from(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE)


def get_current_user(request: Request, session: DbSession) -> User:
    token = access_token_from(request)
    if not token:
        raise UnauthorizedError()

    try:
        claims = decode_token(token, "access")
    except TokenError as exc:
        raise UnauthorizedError("Sesiune expirată. Autentifică-te din nou.") from exc

    user = UserRepository(session).get_by_id(claims.subject, claims.organization_id)
    if user is None or not user.can_authenticate:
        # Contul a fost dezactivat sau șters după emiterea tokenului.
        raise UnauthorizedError("Contul nu mai este activ.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Any:
    """Autorizarea efectivă. Ascunderea butonului în UI este doar ergonomie.

    Se folosește ca adnotare de tip:

        user: Annotated[User, require_permission(Permission.ADMIN_USERS)]
    """

    def dependency(user: CurrentUser) -> User:
        if permission not in permissions_for(user.primary_role):
            raise ForbiddenError()
        return user

    return Depends(dependency)


def client_ip(request: Request) -> str | None:
    """IP-ul clientului.

    `X-Forwarded-For` se ia în seamă doar când aplicația chiar stă în spatele unui
    proxy de încredere — altfel orice client își poate falsifica IP-ul din audit.
    TODO: citește antetul doar pentru rețele de proxy configurate explicit.
    """
    return request.client.host if request.client else None


def get_storage() -> StorageProvider:
    """Providerul configurat, unul singur pentru tot procesul."""
    return get_storage_provider()


StorageDep = Annotated[StorageProvider, Depends(get_storage)]
