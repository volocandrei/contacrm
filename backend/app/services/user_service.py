"""Administrarea colegilor din cabinet (M12).

Până acum `/users` era doar citire: lista exista, iar singurul mod de a adăuga pe
cineva era `python -m app.cli create-admin`, o comandă gândită pentru **primul**
cont al unei baze goale. Un cabinet care angajează pe cineva marți nu are de ce
să deschidă un terminal.

**Parola o pune administratorul și o comunică el.** Nu există „invitație prin
email" pentru că nu există încă un provider de email (Faza 2), iar o invitație
care nu pleacă este mai rea decât absența ei. Nu se generează nici o parolă pe
care apoi să o afișăm: un secret care trece prin ecran și prin log-ul unui proxy
nu mai este un secret. Administratorul o alege și o spune colegului direct, iar
acesta o schimbă la prima autentificare — pasul acela este în backlog și este
notat ca atare, nu pretins.

**Două lucruri pe care nimeni nu și le poate face singur**, pentru că amândouă
sună la fel: „nu mai am acces". Nu te poți dezactiva, și nu îți poți lua rolul
prin care administrezi. Un cabinet cu un singur administrator care își schimbă
din greșeală rolul rămâne afară din propria aplicație, iar remediul este atunci
un terminal și un SQL — exact ce încearcă modulul ăsta să nu mai fie necesar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode, NotFoundError, ValidationError
from app.core.security import hash_password
from app.domain.permissions import RoleCode
from app.models.user import Role, User
from app.services.audit import AuditService

#: Aceeași lungime minimă ca la `create-admin`. Un prag mai mic aici ar fi
#: însemnat că drumul comod produce conturi mai slabe decât cel incomod.
MIN_PASSWORD_LENGTH = 12

#: Ce se scrie în audit despre un utilizator. Parola nu este printre ele și nu
#: are cum să ajungă: nu apare în niciun instantaneu.
USER_FIELDS = ("email", "full_name", "is_active")


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Cine face schimbarea, de unde. Ajunge întreg în jurnalul de audit."""

    user: User
    ip: str | None = None
    user_agent: str | None = None


def _snapshot(user: User) -> dict[str, Any]:
    values: dict[str, Any] = {field: getattr(user, field) for field in USER_FIELDS}
    values["role"] = user.primary_role.value
    return values


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ── Creare ──────────────────────────────────────────────────────────────

    def create(
        self, organization_id: uuid.UUID, values: dict[str, Any], actor: ActorContext
    ) -> User:
        email = _normalized_email(values.get("email"))
        full_name = _required_text(values.get("full_name"), "fullName", "Numele")
        password = str(values.get("password") or "")
        role = self._role(values.get("role"))

        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Parola are minimum {MIN_PASSWORD_LENGTH} caractere.",
                {"password": ["Prea scurtă."]},
            )
        self._assert_email_is_free(organization_id, email)

        user = User(
            organization_id=organization_id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            roles=[role],
        )
        self.session.add(user)
        self.session.flush()

        self.audit.record(
            organization_id=organization_id,
            action="USER_CREATED",
            entity_type="User",
            entity_id=str(user.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            detail=f"{full_name} ({email}) · {role.code}",
            new_value=_snapshot(user),
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return user

    # ── Modificare ──────────────────────────────────────────────────────────

    def update(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        values: dict[str, Any],
        actor: ActorContext,
    ) -> User:
        user = self._user(organization_id, user_id)
        before = _snapshot(user)

        if "is_active" in values:
            active = bool(values["is_active"])
            if not active and user.id == actor.user.id:
                # Sună a „nu mai am acces" și nu se poate repara din aplicație.
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "Nu te poți dezactiva pe tine. Roagă alt administrator.",
                )
            user.is_active = active

        if values.get("role") is not None:
            role = self._role(values["role"])
            if user.id == actor.user.id and role.code != user.primary_role.value:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "Nu îți poți schimba propriul rol. Roagă alt administrator.",
                )
            user.roles = [role]

        if values.get("full_name") is not None:
            user.full_name = _required_text(values["full_name"], "fullName", "Numele")

        self.session.flush()
        self.audit.record(
            organization_id=organization_id,
            action="USER_UPDATED",
            entity_type="User",
            entity_id=str(user.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            detail=f"{user.full_name} ({user.email})",
            old_value=before,
            new_value=_snapshot(user),
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return user

    def set_password(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        password: str,
        actor: ActorContext,
    ) -> User:
        """Resetarea parolei unui coleg care a uitat-o.

        **Nu se cere parola veche**, pentru că nu o știe nici cel care resetează:
        asta este o resetare făcută de un administrator, nu o schimbare făcută de
        proprietar. De aceea se auditează cu numele amândurora — este singurul
        moment în care cineva capătă acces la contul altcuiva.
        """
        user = self._user(organization_id, user_id)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Parola are minimum {MIN_PASSWORD_LENGTH} caractere.",
                {"password": ["Prea scurtă."]},
            )

        user.password_hash = hash_password(password)
        self.session.flush()
        self.audit.record(
            organization_id=organization_id,
            action="USER_PASSWORD_RESET",
            entity_type="User",
            entity_id=str(user.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            # Nici parola veche, nici cea nouă: auditul spune că s-a întâmplat.
            detail=f"Parolă resetată pentru {user.full_name} ({user.email})",
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return user

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
        found = self.session.scalars(
            select(User).where(
                User.id == user_id,
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
            )
        ).first()
        if found is None:
            # NOT_FOUND, nu FORBIDDEN: răspunsul nu confirmă că id-ul există (§72).
            raise NotFoundError("Utilizator", user_id)
        return found

    def _role(self, code: object) -> Role:
        if not isinstance(code, str) or code not in {member.value for member in RoleCode}:
            raise ValidationError(f"Rol necunoscut: {code!r}.", {"role": ["Rol invalid."]})

        role = self.session.scalars(select(Role).where(Role.code == code)).first()
        if role is None:
            # Rolurile vin din cod, prin `sync-roles`. Absența lor din bază este o
            # instalare incompletă, nu o cerere greșită — se spune ce lipsește.
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"Rolul {code} nu există în baza de date. Rulează `app.cli sync-roles`.",
            )
        return role

    def _assert_email_is_free(self, organization_id: uuid.UUID, email: str) -> None:
        taken = self.session.scalars(
            select(User).where(
                User.organization_id == organization_id,
                func.lower(User.email) == email,
            )
        ).first()
        if taken is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                f"Adresa {email} este deja folosită în cabinet.",
                details={"email": ["Adresă folosită."]},
            )


def _required_text(value: object, field: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{label} este obligatoriu.", {field: ["Câmp obligatoriu."]})
    return text


def _normalized_email(value: object) -> str:
    """Adresa, în litere mici.

    Aceeași normalizare ca la autentificare: altfel `Ion@` și `ion@` ar fi două
    conturi diferite, iar al doilea ar trece de verificarea de unicitate.
    """
    email = str(value or "").strip().lower()
    if not email or "@" not in email:
        raise ValidationError("Adresă de email invalidă.", {"email": ["Adresă invalidă."]})
    return email


__all__ = ["MIN_PASSWORD_LENGTH", "ActorContext", "UserService"]
