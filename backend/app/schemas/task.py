"""Schemele pentru sarcini.

Forma exactă a tipului `Task` din `frontend/src/types/domain.ts`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import StringConstraints

from app.domain.enums import TaskPriority, TaskStatus
from app.schemas.common import ApiModel


class TaskOut(ApiModel):
    id: uuid.UUID
    title: str
    description: str
    client_id: uuid.UUID | None
    client_name: str | None
    assigned_to_id: uuid.UUID | None
    assigned_to_name: str | None
    priority: TaskPriority
    status: TaskStatus
    due_date: date | None
    created_at: datetime
    completed_at: datetime | None


class TaskCreate(ApiModel):
    """O sarcină nouă.

    Doar titlul este obligatoriu. Restul se completează dacă se știe: o sarcină
    pe care nu o poți nota în trei secunde nu se notează deloc, iar una notată
    fără termen este mai bună decât una uitată.
    """

    #: `strip_whitespace` **înaintea** verificării de lungime: altfel „   " trece
    #: de `min_length=1` și ajunge în bază ca sarcină fără nume.
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""
    client_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: date | None = None


class TaskStatusUpdate(ApiModel):
    """Singura modificare pe care o face ecranul kanban."""

    status: TaskStatus


class TaskFilters(ApiModel):
    status: TaskStatus | None = None
    assigned_to_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
