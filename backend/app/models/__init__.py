"""Modelele ORM.

`ALL_MODELS` există ca Alembic să aibă un singur import de făcut: orice model nou
se adaugă aici, altfel autogenerarea nu îl vede și migrarea iese goală.
"""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.organization import Organization
from app.models.user import Permission, RefreshToken, Role, User, role_permissions, user_roles

ALL_MODELS = (Organization, User, Role, Permission, RefreshToken, AuditLog)

__all__ = [
    "ALL_MODELS",
    "AuditLog",
    "Base",
    "Organization",
    "Permission",
    "RefreshToken",
    "Role",
    "User",
    "role_permissions",
    "user_roles",
]
