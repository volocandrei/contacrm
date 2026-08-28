"""Utilizatorii organizației (§32).

Prima rută care demonstrează autorizarea la nivel de permisiune, nu doar de
autentificare: listarea cere `admin:users`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter

from app.api.deps import DbSession, require_permission
from app.domain.permissions import Permission
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import UserSummaryOut

router = APIRouter(tags=["administrare"])


@router.get("/users", response_model=list[UserSummaryOut])
def list_users(
    session: DbSession,
    user: Annotated[User, require_permission(Permission.ADMIN_USERS)],
) -> list[UserSummaryOut]:
    # Filtrarea pe organizația utilizatorului curent, nu pe una primită din cerere.
    users = UserRepository(session).list_for_organization(user.organization_id)
    return [
        UserSummaryOut(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            role=u.primary_role,
            is_active=u.is_active,
            last_login_at=u.last_login_at,
        )
        for u in users
    ]
