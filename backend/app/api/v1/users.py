"""Utilizatorii organizației (§32, M12).

Prima rută care a demonstrat autorizarea la nivel de permisiune, nu doar de
autentificare: listarea cere `admin:users`.

**Ce lipsea.** Doar listarea exista. Singurul mod de a adăuga un coleg era
`python -m app.cli create-admin` — o comandă gândită pentru **primul** cont al
unei baze goale, cu parola citită de la tastatură. Un cabinet care angajează pe
cineva marți nu are de ce să deschidă un terminal, iar dacă cineva pleacă, contul
lui rămânea activ până se ocupa cineva de el prin SQL.

Regulile care contează stau în `services/user_service.py`, cu motivele lor.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import Field

from app.api.deps import DbSession, client_ip, require_permission
from app.api.route import CommittingRoute
from app.domain.permissions import ROLE_LABEL, Permission, RoleCode, sorted_permissions
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import UserSummaryOut
from app.schemas.common import ApiModel
from app.schemas.email import EmailAddress
from app.services.user_service import MIN_PASSWORD_LENGTH, ActorContext, UserService

router = APIRouter(route_class=CommittingRoute, tags=["administrare"])

UserAdmin = Annotated[User, require_permission(Permission.ADMIN_USERS)]


class UserCreate(ApiModel):
    email: EmailAddress
    full_name: str = Field(min_length=1, max_length=255)
    role: RoleCode
    #: O pune administratorul și o comunică el. Nu există invitație prin email
    #: pentru că nu există provider (Faza 2), iar o invitație care nu pleacă este
    #: mai rea decât absența ei.
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class UserUpdate(ApiModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: RoleCode | None = None
    is_active: bool | None = None


class PasswordReset(ApiModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


def _to_out(user: User) -> UserSummaryOut:
    return UserSummaryOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.primary_role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
    )


def _actor(user: User, request: Request) -> ActorContext:
    return ActorContext(
        user=user, ip=client_ip(request), user_agent=request.headers.get("User-Agent")
    )


class RoleOut(ApiModel):
    code: RoleCode
    label: str
    permissions: list[Permission]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(user: UserAdmin) -> list[RoleOut]:
    """Matricea rolurilor cu permisiunile lor, întreagă.

    Până acum ecranul de roluri putea completa **o singură coloană** — a rolului
    cu care ești autentificat — pentru că doar atât expunea API-ul: `/me`
    întoarce permisiunile *tale*. Ecranul își recunoștea limita într-o notă de
    subsol, ceea ce este cinstit dar inutil: cine deschide „Roluri" vrea să afle
    ce poate face un operator **înainte** de a-i da rolul, nu după.

    Harta există deja în `domain/permissions.py` și nu este un secret: nu spune
    cine ce rol are, ci ce înseamnă fiecare rol. Cere totuși `admin:users`,
    fiindcă doar cine împarte roluri are motiv să o citească.

    Nu atinge baza de date — de aceea nici nu cere sesiune.
    """
    del user  # doar autorizarea contează aici
    return [
        RoleOut(code=role, label=ROLE_LABEL[role], permissions=sorted_permissions(role))
        for role in RoleCode
    ]


@router.get("/users", response_model=list[UserSummaryOut])
def list_users(session: DbSession, user: UserAdmin) -> list[UserSummaryOut]:
    # Filtrarea pe organizația utilizatorului curent, nu pe una primită din cerere.
    users = UserRepository(session).list_for_organization(user.organization_id)
    return [_to_out(row) for row in users]


@router.post("/users", response_model=UserSummaryOut, status_code=status.HTTP_201_CREATED)
def create_user(
    session: DbSession, user: UserAdmin, request: Request, payload: UserCreate
) -> UserSummaryOut:
    """Adaugă un coleg.

    Parola nu se generează și nu se afișează: un secret care trece prin ecran și
    prin log-ul unui proxy nu mai este un secret. O alege administratorul și o
    spune direct.
    """
    created = UserService(session).create(
        user.organization_id, payload.model_dump(), _actor(user, request)
    )
    return _to_out(created)


@router.patch("/users/{user_id}", response_model=UserSummaryOut)
def update_user(
    session: DbSession,
    user: UserAdmin,
    request: Request,
    user_id: uuid.UUID,
    payload: UserUpdate,
) -> UserSummaryOut:
    """Schimbă rolul, numele, sau dezactivează contul.

    **Nu există ștergere.** Un utilizator apare în jurnalul de audit ca autor al
    unor acțiuni contabile; ștergerea lui ar rupe urma. Ce se cere de fapt când
    cineva pleacă este „să nu mai poată intra", iar asta se face dezactivând.
    """
    updated = UserService(session).update(
        user.organization_id,
        user_id,
        # `exclude_unset`: un câmp netrimis nu se atinge. Fără el, un formular
        # care schimbă doar rolul ar goli numele.
        payload.model_dump(exclude_unset=True),
        _actor(user, request),
    )
    return _to_out(updated)


@router.post("/users/{user_id}/password", response_model=UserSummaryOut)
def reset_password(
    session: DbSession,
    user: UserAdmin,
    request: Request,
    user_id: uuid.UUID,
    payload: PasswordReset,
) -> UserSummaryOut:
    """Resetează parola unui coleg care a uitat-o.

    Nu se cere parola veche: nici cel care resetează nu o știe. Este singurul
    moment în care cineva capătă acces la contul altcuiva, deci se auditează cu
    numele amândurora.
    """
    updated = UserService(session).set_password(
        user.organization_id, user_id, payload.password, _actor(user, request)
    )
    return _to_out(updated)
