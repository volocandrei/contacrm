"""Jurnalul de audit (§33, §68).

Doar citire, și doar pentru cine are `audit:read`. Nu există rută de ștergere și nu
va exista: un jurnal din care se poate șterge nu mai este un jurnal. Nici de scriere
— intrările apar exclusiv ca efect al acțiunilor reale, prin `AuditService`.

Vechile valori și cele noi (`old_value` / `new_value`) **nu** ies prin API: pot
conține date de pe documente contabile, iar ecranul de audit răspunde la „cine, ce,
când", nu la „ce scria pe factură". Cine are nevoie de conținut deschide documentul,
și acea deschidere se auditează la rândul ei.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select

from app.api.deps import DbSession, require_permission
from app.api.route import CommittingRoute
from app.domain.permissions import Permission
from app.models.audit import AuditLog
from app.models.user import User
from app.repositories.document import escape_like
from app.schemas.common import ApiModel, PageParams, Paginated

router = APIRouter(route_class=CommittingRoute, tags=["administrare"])

AuditReader = Annotated[User, require_permission(Permission.AUDIT_READ)]


class AuditLogEntryOut(ApiModel):
    id: uuid.UUID
    at: datetime
    user_name: str
    action: str
    entity_type: str
    entity_id: str
    detail: str | None
    ip: str


class AuditFilters(ApiModel):
    """Filtrele ecranului de audit.

    Model, nu parametri separați: `ApiModel` aplică `alias_generator=to_camel`, deci
    numele din query sunt cele trimise de frontend. Parametrii declarați unul câte
    unul ar rămâne `snake_case` și ar fi ignorați în tăcere.
    """

    q: str | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None


@router.get("/audit-logs", response_model=Paginated[AuditLogEntryOut])
def list_audit_logs(
    session: DbSession,
    user: AuditReader,
    filters: Annotated[AuditFilters, Query()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[AuditLogEntryOut]:
    stmt = select(AuditLog).where(AuditLog.organization_id == user.organization_id)
    stmt = _apply(stmt, filters)

    total = session.scalar(
        select(func.count()).select_from(stmt.with_only_columns(AuditLog.id).subquery())
    )
    rows = session.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()

    return Paginated[AuditLogEntryOut].build(
        items=[_to_out(row) for row in rows], total=total or 0, params=page
    )


def _apply(stmt: Select[tuple[AuditLog]], filters: AuditFilters) -> Select[tuple[AuditLog]]:
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.entity_type:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.entity_id:
        stmt = stmt.where(AuditLog.entity_id == filters.entity_id)
    if filters.q:
        # Metacaracterele din input nu sunt jokeri: `%` scris de un utilizator
        # înseamnă procent, nu „orice".
        needle = f"%{escape_like(filters.q.lower())}%"
        stmt = stmt.where(
            func.lower(AuditLog.user_name).like(needle, escape="\\")
            | func.lower(AuditLog.action).like(needle, escape="\\")
            | func.lower(func.coalesce(AuditLog.detail, "")).like(needle, escape="\\")
        )
    return stmt


def _to_out(row: AuditLog) -> AuditLogEntryOut:
    return AuditLogEntryOut(
        id=row.id,
        at=row.created_at,
        user_name=row.user_name,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id or "",
        detail=row.detail,
        # Contractul frontend cere un text; un IP absent (acțiune de sistem) devine „—".
        ip=row.ip or "—",
    )
