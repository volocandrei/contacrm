"""Business logic de autentificare.

Regulile care contează, într-un singur loc:

- un email inexistent și o parolă greșită produc **același** răspuns și consumă
  aproximativ același timp — altfel formularul de login devine un oracol de
  enumerare a conturilor;
- refresh tokenurile se rotesc: fiecare reîmprospătare emite unul nou și îl revocă
  pe cel folosit;
- refolosirea unui token deja rotit înseamnă că cineva are o copie — revocăm
  întreaga familie, nu doar tokenul refolosit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.domain.permissions import sorted_permissions
from app.models.user import RefreshToken, User
from app.repositories.user import UserRepository
from app.schemas.auth import CurrentUserOut
from app.services.audit import AuditService

logger = get_logger(__name__)

# Un singur mesaj pentru orice eșec de autentificare — nu spunem care jumătate
# a fost greșită.
_INVALID_CREDENTIALS = "Email sau parolă incorecte."


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    user: CurrentUserOut
    tokens: IssuedTokens


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    # ── Login ───────────────────────────────────────────────────────────────

    def login(
        self,
        email: str,
        password: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        user = self.users.get_by_email(email)

        if user is None:
            # Consumăm timp de hashing ca durata să nu trădeze inexistența contului.
            dummy_verify()
            logger.info("login_failed", reason="unknown_email")
            raise UnauthorizedError(_INVALID_CREDENTIALS)

        if not verify_password(password, user.password_hash):
            logger.info("login_failed", reason="bad_password", user_id=str(user.id))
            raise UnauthorizedError(_INVALID_CREDENTIALS)

        if not user.can_authenticate:
            # Contul dezactivat merită un mesaj distinct: utilizatorul își știe deja
            # parola, iar „email sau parolă incorecte" l-ar trimite pe o pistă greșită.
            logger.info("login_rejected", reason="inactive", user_id=str(user.id))
            raise UnauthorizedError("Contul este dezactivat.")

        # Parametrii Argon2 se pot întări între versiuni; rehash-uim la login.
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        now = datetime.now(UTC)
        self.users.touch_last_login(user, now)
        tokens = self._issue(user, family_id=uuid.uuid4(), ip=ip, user_agent=user_agent, now=now)

        self.audit.record(
            organization_id=user.organization_id,
            action="USER_LOGIN",
            entity_type="User",
            entity_id=str(user.id),
            user_id=user.id,
            user_name=user.full_name,
            detail=user.email,
            ip=ip,
            user_agent=user_agent,
        )
        logger.info("login_ok", user_id=str(user.id), role=user.primary_role.value)
        return AuthSession(user=self.describe(user), tokens=tokens)

    # ── Refresh ─────────────────────────────────────────────────────────────

    def refresh(
        self,
        refresh_token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        try:
            claims = decode_token(refresh_token, "refresh")
        except TokenError as exc:
            logger.info("refresh_rejected", reason=str(exc))
            raise UnauthorizedError("Sesiune expirată. Autentifică-te din nou.") from exc

        stored = self.users.get_refresh_token(claims.token_id)
        if stored is None or stored.token_hash != hash_token(refresh_token):
            logger.warning("refresh_rejected", reason="unknown_token")
            raise UnauthorizedError("Sesiune expirată. Autentifică-te din nou.")

        now = datetime.now(UTC)

        if not stored.is_usable(now):
            # Tokenul a fost deja rotit sau revocat, dar cineva îl mai are. Tratăm
            # asta ca furt: toată familia cade, inclusiv sesiunea celui care o
            # folosește acum legitim — mai bine o reautentificare decât o sesiune furată.
            revoked = self.users.revoke_family(stored.family_id)
            logger.warning(
                "refresh_reuse_detected",
                user_id=str(stored.user_id),
                family_id=str(stored.family_id),
                revoked=revoked,
            )
            self.audit.record(
                organization_id=self._organization_of(stored.user_id),
                action="REFRESH_TOKEN_REUSE_DETECTED",
                entity_type="User",
                entity_id=str(stored.user_id),
                user_id=stored.user_id,
                user_name="sistem",
                detail=f"Familie revocată ({revoked} tokenuri)",
                ip=ip,
                user_agent=user_agent,
            )
            raise UnauthorizedError("Sesiune invalidă. Autentifică-te din nou.")

        user = self.users.get_by_id(claims.subject, claims.organization_id)
        if user is None or not user.can_authenticate:
            self.users.revoke_family(stored.family_id)
            raise UnauthorizedError("Contul nu mai este activ.")

        tokens = self._issue(
            user, family_id=stored.family_id, ip=ip, user_agent=user_agent, now=now
        )
        # Rotația: tokenul folosit se revocă și arată către succesorul lui.
        new_id = decode_token(tokens.refresh_token, "refresh").token_id
        self.users.revoke_refresh_token(stored, replaced_by_id=new_id)

        logger.info("refresh_ok", user_id=str(user.id))
        return AuthSession(user=self.describe(user), tokens=tokens)

    # ── Logout ──────────────────────────────────────────────────────────────

    def logout(self, refresh_token: str | None, user: User | None) -> None:
        """Revocă sesiunea curentă. Un token deja invalid nu este o eroare."""
        if refresh_token:
            try:
                claims = decode_token(refresh_token, "refresh")
            except TokenError:
                claims = None
            if claims is not None:
                stored = self.users.get_refresh_token(claims.token_id)
                if stored is not None:
                    self.users.revoke_family(stored.family_id)

        if user is not None:
            self.audit.record(
                organization_id=user.organization_id,
                action="USER_LOGOUT",
                entity_type="User",
                entity_id=str(user.id),
                user_id=user.id,
                user_name=user.full_name,
            )

    # ── Ajutătoare ──────────────────────────────────────────────────────────

    def describe(self, user: User) -> CurrentUserOut:
        organization = self.users.get_organization(user.organization_id)
        role = user.primary_role
        return CurrentUserOut(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=role,
            permissions=sorted_permissions(role),
            organization_id=user.organization_id,
            organization_name=organization.name if organization else "",
        )

    def _issue(
        self,
        user: User,
        *,
        family_id: uuid.UUID,
        ip: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> IssuedTokens:
        role = user.primary_role
        permissions = [p.value for p in sorted_permissions(role)]

        access_token, access_expires = create_access_token(
            user.id, user.organization_id, permissions
        )
        refresh_token, token_id, refresh_expires = create_refresh_token(
            user.id, user.organization_id
        )

        self.users.add_refresh_token(
            RefreshToken(
                user_id=user.id,
                token_id=token_id,
                token_hash=hash_token(refresh_token),
                family_id=family_id,
                expires_at=refresh_expires,
                user_agent=user_agent[:255] if user_agent else None,
                ip=ip,
                created_at=now,
            )
        )
        return IssuedTokens(
            access_token=access_token,
            access_expires_at=access_expires,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires,
        )

    def _organization_of(self, user_id: uuid.UUID) -> uuid.UUID:
        user = self.session.get(User, user_id)
        if user is None:  # pragma: no cover — FK garantează existența
            raise UnauthorizedError(_INVALID_CREDENTIALS)
        return user.organization_id
