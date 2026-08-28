"""Utilizatori, roluri, permisiuni și refresh tokenuri (§32, ADR-006).

Rolurile și permisiunile trăiesc în tabele, nu în cod, ca să poată fi administrate
fără deploy. `app/domain/permissions.py` rămâne sursa de adevăr pentru **conținutul
inițial** al acestor tabele, sincronizat prin seed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.permissions import RoleCode
from app.models.base import Base, OrganizationMixin, SoftDeleteMixin, TimestampMixin, uuid_pk

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
)


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid_pk]
    code: Mapped[RoleCode] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


class User(Base, OrganizationMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        # Emailul este unic per organizație, nu global: două cabinete pot avea
        # același contabil.
        UniqueConstraint("organization_id", "email", name="uq_users_organization_id_email"),
        Index("ix_users_email", "email"),
    )

    id: Mapped[uuid_pk]
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_codes(self) -> list[RoleCode]:
        return [RoleCode(role.code) for role in self.roles]

    @property
    def primary_role(self) -> RoleCode:
        """Interfața afișează un singur rol; îl alegem pe cel mai puternic."""
        order = list(RoleCode)
        return min(self.role_codes, key=order.index, default=RoleCode.VIEWER)

    @property
    def can_authenticate(self) -> bool:
        return self.is_active and self.deleted_at is None

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class RefreshToken(Base):
    """Un refresh token emis.

    Stocăm doar hash-ul. `family_id` leagă tokenurile care descind unul din altul:
    dacă un token deja rotit este refolosit, presupunem furt și revocăm toată
    familia, nu doar tokenul refolosit.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),
        Index("ix_refresh_tokens_family_id", "family_id"),
    )

    id: Mapped[uuid_pk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    replaced_by_id: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(nullable=False)

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"<RefreshToken {self.token_id} user={self.user_id}>"
