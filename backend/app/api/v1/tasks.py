"""Rutele pentru sarcini.

Citirea cere `tasks:read`, modificarea `tasks:write` — două permisiuni distincte,
pentru că un VIEWER trebuie să vadă sarcinile fără să le poată muta pe kanban.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, client_ip, require_permission
from app.core.errors import NotFoundError
from app.domain.enums import TaskStatus
from app.domain.permissions import Permission
from app.models.user import User
from app.repositories.task import TaskRepository, TaskRow
from app.schemas.task import TaskFilters, TaskOut, TaskStatusUpdate
from app.services.audit import AuditService

router = APIRouter(prefix="/tasks", tags=["crm"])

TaskReader = Annotated[User, require_permission(Permission.TASKS_READ)]
TaskWriter = Annotated[User, require_permission(Permission.TASKS_WRITE)]


def _to_out(row: TaskRow) -> TaskOut:
    task = row.task
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        client_id=task.client_id,
        client_name=row.client_name,
        assigned_to_id=task.assigned_to_id,
        assigned_to_name=row.assignee_name,
        priority=task.priority,
        status=task.status,
        due_date=task.due_date,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    session: DbSession,
    user: TaskReader,
    filters: Annotated[TaskFilters, Depends()],
) -> list[TaskOut]:
    rows = TaskRepository(session).list(user.organization_id, filters)
    return [_to_out(row) for row in rows]


@router.patch("/{task_id}", response_model=TaskOut)
def update_task_status(
    session: DbSession,
    user: TaskWriter,
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    request_ip: Annotated[str | None, Depends(client_ip)],
) -> TaskOut:
    repository = TaskRepository(session)
    task = repository.get(user.organization_id, task_id)
    if task is None:
        raise NotFoundError("Sarcină", task_id)

    previous = task.status
    task.status = payload.status
    # `completed_at` urmează statusul: o sarcină redeschisă nu mai are dată de final.
    task.completed_at = datetime.now(UTC) if payload.status is TaskStatus.DONE else None

    AuditService(session).record(
        organization_id=user.organization_id,
        action="TASK_UPDATED",
        entity_type="Task",
        entity_id=str(task.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{task.title} → {payload.status.value}",
        old_value={"status": previous.value},
        new_value={"status": payload.status.value},
        ip=request_ip,
    )
    session.flush()
    return _to_out(repository.describe(task))
