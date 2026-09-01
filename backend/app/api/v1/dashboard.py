"""Contoarele din bara laterală.

Doar acest fragment de dashboard intră în M5: badge-urile din navigație trebuie să
funcționeze de îndată ce interfața vorbește cu API-ul real. Restul tabloului de
bord — indicatori, atenționări, cronologie — vine cu M6, împreună cu perioadele.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.domain.enums import DocumentStatus, TaskStatus
from app.domain.permissions import Permission
from app.models.task import Task
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.schemas.common import ApiModel

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DashboardReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]

# „Inbox" înseamnă „a intrat, sistemul încă lucrează la el".
INBOX_STATUSES = (DocumentStatus.RECEIVED, DocumentStatus.PROCESSING)


class SidebarCountsOut(ApiModel):
    inbox: int
    review: int
    unmatched: int
    tasks: int


@router.get("/counts", response_model=SidebarCountsOut)
def sidebar_counts(session: DbSession, user: DashboardReader) -> SidebarCountsOut:
    by_status = DocumentRepository(session).count_by_status(user.organization_id)

    open_tasks = session.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.organization_id == user.organization_id,
            Task.deleted_at.is_(None),
            Task.status != TaskStatus.DONE,
        )
    )

    return SidebarCountsOut(
        inbox=sum(by_status.get(s, 0) for s in INBOX_STATUSES),
        review=by_status.get(DocumentStatus.REVIEW_REQUIRED, 0),
        unmatched=by_status.get(DocumentStatus.UNMATCHED, 0),
        tasks=open_tasks or 0,
    )
