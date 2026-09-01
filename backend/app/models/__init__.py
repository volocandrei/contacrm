"""Modelele ORM.

`ALL_MODELS` există ca Alembic să aibă un singur import de făcut: orice model nou
se adaugă aici, altfel autogenerarea nu îl vede și migrarea iese goală.
"""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.client import Client, ClientNote, Contact, Tag, client_tags
from app.models.document import (
    Document,
    DocumentFieldOverride,
    DocumentIntake,
    DocumentProcessingJob,
    DocumentType,
    DocumentVersion,
)
from app.models.organization import Organization
from app.models.period import AccountingPeriod, ClientExpectation
from app.models.task import Task
from app.models.user import Permission, RefreshToken, Role, User, role_permissions, user_roles

ALL_MODELS = (
    Organization,
    User,
    Role,
    Permission,
    RefreshToken,
    AuditLog,
    Client,
    Contact,
    ClientNote,
    Tag,
    Task,
    AccountingPeriod,
    ClientExpectation,
    DocumentType,
    DocumentIntake,
    Document,
    DocumentVersion,
    DocumentFieldOverride,
    DocumentProcessingJob,
)

__all__ = [
    "ALL_MODELS",
    "AccountingPeriod",
    "AuditLog",
    "Base",
    "Client",
    "ClientExpectation",
    "ClientNote",
    "Contact",
    "Document",
    "DocumentFieldOverride",
    "DocumentIntake",
    "DocumentProcessingJob",
    "DocumentType",
    "DocumentVersion",
    "Organization",
    "Permission",
    "RefreshToken",
    "Role",
    "Tag",
    "Task",
    "User",
    "client_tags",
    "role_permissions",
    "user_roles",
]
