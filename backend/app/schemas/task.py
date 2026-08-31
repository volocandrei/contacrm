"""Schemele pentru sarcini.

Forma exactă a tipului `Task` din `frontend/src/types/domain.ts`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

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


class TaskStatusUpdate(ApiModel):
    """Singura modificare pe care o face ecranul kanban."""

    status: TaskStatus


class TaskFilters(ApiModel):
    status: TaskStatus | None = None
    assigned_to_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
