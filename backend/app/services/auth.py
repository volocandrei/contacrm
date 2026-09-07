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
from app.domain.passwords import ensure_strong
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


@dataclass(frozen=True, slots=True)
class ActiveSession:
    """O fereastră deschisă pe cont. Fără niciun token — doar urma ei."""

    family_id: uuid.UUID
    started_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


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

    def _family_of(self, refresh_token: str | None) -> uuid.UUID | None:
        """Din ce sesiune vine cererea de față, dacă se poate ști.

        Un token expirat, revocat sau lipsă întoarce `None` — nu o eroare: cine
        întreabă ce sesiuni are deschise nu trebuie refuzat pentru că tocmai i-a
        expirat cookie-ul de reîmprospătare.
        """
        if not refresh_token:
            return None
        try:
            claims = decode_token(refresh_token, "refresh")
        except TokenError:
            return None
        stored = self.users.get_refresh_token(claims.token_id)
        return stored.family_id if stored is not None else None

    # ── Sesiuni ─────────────────────────────────────────────────────────────

    def sessions(self, user: User, *, current_token: str | None = None) -> list[ActiveSession]:
        """Ferestrele deschise pe contul acesta, cea curentă întâi.

        **De ce este un ecran, nu o curiozitate.** Întrebarea „mai are cineva
        sesiune deschisă pe contul meu?" nu avea până acum niciun răspuns în
        aplicație. Ea se pune exact în ziua proastă: după un laptop uitat
        deschis, după o parolă tastată pe alt calculator, după un email dubios.

        O sesiune este o **familie** de tokenuri, nu un rând: tokenul se rotește
        la fiecare reîmprospătare, deci o fereastră lăsată deschisă o zi lasă în
        urmă zeci de rânduri. Se arată începutul familiei, ultima activitate,
        adresa și browserul — niciodată vreun token.
        """
        now = datetime.now(UTC)
        current_family = self._family_of(current_token)

        grouped: dict[uuid.UUID, list[RefreshToken]] = {}
        for token in self.users.active_tokens_for_user(user.id, now=now):
            grouped.setdefault(token.family_id, []).append(token)

        found = [
            ActiveSession(
                family_id=family,
                started_at=min(token.created_at for token in tokens),
                last_seen_at=max(token.created_at for token in tokens),
                expires_at=max(token.expires_at for token in tokens),
                ip=tokens[0].ip,
                user_agent=tokens[0].user_agent,
                current=family == current_family,
            )
            for family, tokens in grouped.items()
        ]
        # Cea curentă întâi, apoi de la cea mai recentă: omul caută intrusul, iar
        # intrusul este cel pe care nu-l recunoaște, nu cel de sus.
        found.sort(key=lambda item: (not item.current, item.last_seen_at), reverse=False)
        found.sort(key=lambda item: item.current, reverse=True)
        return found

    def revoke_other_sessions(
        self,
        user: User,
        current_token: str | None,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """Închide toate celelalte ferestre. Întoarce câte.

        Nu cere parola: cine este deja autentificat poate oricum face totul cu
        contul. Ce ar fi cerut parola este o acțiune **distructivă pentru date**;
        asta doar deconectează, iar a o îngreuna ar însemna că omul care bănuiește
        ceva stă să-și amintească parola în loc să apese.
        """
        keep = self._family_of(current_token)

        if keep is None:
            # Fără o sesiune curentă identificabilă, „celelalte" înseamnă toate.
            closed = self.users.revoke_all_for_user(user.id)
        else:
            closed = self.users.revoke_families_except(user.id, keep)

        self.audit.record(
            organization_id=user.organization_id,
            action="USER_SESSIONS_REVOKED",
            entity_type="User",
            entity_id=str(user.id),
            user_id=user.id,
            user_name=user.full_name,
            detail=f"{closed} sesiuni închise",
            ip=ip,
            user_agent=user_agent,
        )
        logger.info("sessions_revoked", user_id=str(user.id), closed=closed)
        return closed

    # ── Schimbarea parolei ──────────────────────────────────────────────────

    def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        """Schimbarea parolei de către proprietarul contului.

        **De ce trebuie să existe.** Până acum exista doar resetarea făcută de un
        administrator asupra altcuiva. Pe o instalare proaspătă administratorul
        este unul singur, deci parola pusă la instalare nu mai putea fi schimbată
        din aplicație de nimeni — nici de el. Iar parola aceea păzește documentele
        financiare ale tuturor clienților cabinetului.

        **Se cere parola veche**, spre deosebire de resetare. Nu ca formalitate: o
        filă lăsată deschisă pe un calculator din birou este exact scenariul în
        care cineva ar schimba parola și ar păstra contul. Cine o știe pe cea
        veche este proprietarul.

        **Toate celelalte sesiuni cad.** Motivul obișnuit pentru care cineva își
        schimbă parola este bănuiala că altcineva o are. Dacă sesiunile vechi
        rămân valabile, schimbarea nu a rezolvat nimic: tokenul de reîmprospătare
        furat mai trăiește două săptămâni. Sesiunea celui care apasă se reface pe
        loc — altfel s-ar deconecta singur exact când face lucrul corect.
        """
        if not verify_password(current_password, user.password_hash):
            logger.info("password_change_rejected", reason="bad_current", user_id=str(user.id))
            raise UnauthorizedError("Parola actuală nu este corectă.")

        ensure_strong(new_password, email=user.email, full_name=user.full_name)

        user.password_hash = hash_password(new_password)
        self.session.flush()

        revoked = self.users.revoke_all_for_user(user.id)

        now = datetime.now(UTC)
        tokens = self._issue(user, family_id=uuid.uuid4(), ip=ip, user_agent=user_agent, now=now)

        self.audit.record(
            organization_id=user.organization_id,
            action="USER_PASSWORD_CHANGED",
            entity_type="User",
            entity_id=str(user.id),
            user_id=user.id,
            user_name=user.full_name,
            # Nici parola veche, nici cea nouă. Câte sesiuni au căzut este exact
            # ce se caută într-un jurnal după o bănuială de acces străin.
            detail=f"Parolă schimbată de proprietar; {revoked} sesiuni închise",
            ip=ip,
            user_agent=user_agent,
        )
        logger.info("password_changed", user_id=str(user.id), revoked=revoked)
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
