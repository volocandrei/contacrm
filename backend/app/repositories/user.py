"""Acces la date pentru utilizatori și refresh tokenuri.

Toate interogările filtrează pe `organization_id` acolo unde entitatea îl are —
scurgerea între organizații se previne aici, nu în endpoint (R10).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.organization import Organization
from app.models.user import RefreshToken, Role, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Utilizatori ─────────────────────────────────────────────────────────

    def get_by_email(self, email: str) -> User | None:
        """Căutarea la login nu are încă organizație — emailul o determină.

        Emailurile se compară case-insensitive: nimeni nu ține minte cum le-a scris.
        """
        stmt = (
            select(User)
            .where(User.email == email.strip().lower(), User.deleted_at.is_(None))
            .options(selectinload(User.roles).selectinload(Role.permissions))
        )
        return self.session.scalars(stmt).first()

    def get_by_id(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> User | None:
        stmt = (
            select(User)
            .where(
                User.id == user_id,
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
            )
            .options(selectinload(User.roles).selectinload(Role.permissions))
        )
        return self.session.scalars(stmt).first()

    def list_for_organization(self, organization_id: uuid.UUID) -> list[User]:
        stmt = (
            select(User)
            .where(User.organization_id == organization_id, User.deleted_at.is_(None))
            .order_by(User.full_name)
            .options(selectinload(User.roles))
        )
        return list(self.session.scalars(stmt))

    def get_organization(self, organization_id: uuid.UUID) -> Organization | None:
        return self.session.get(Organization, organization_id)

    def touch_last_login(self, user: User, when: datetime) -> None:
        user.last_login_at = when

    # ── Refresh tokenuri ────────────────────────────────────────────────────

    def add_refresh_token(self, token: RefreshToken) -> None:
        self.session.add(token)

    def get_refresh_token(self, token_id: str) -> RefreshToken | None:
        return self.session.scalars(
            select(RefreshToken).where(RefreshToken.token_id == token_id)
        ).first()

    def revoke_refresh_token(self, token: RefreshToken, replaced_by_id: str | None = None) -> None:
        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
        token.replaced_by_id = replaced_by_id

    def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revocă toate tokenurile dintr-o familie. Folosit la detectarea refolosirii."""
        now = datetime.now(UTC)
        tokens = list(
            self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        for token in tokens:
            token.revoked_at = now
        return len(tokens)

    def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        now = datetime.now(UTC)
        tokens = list(
            self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        )
        for token in tokens:
            token.revoked_at = now
        return len(tokens)
