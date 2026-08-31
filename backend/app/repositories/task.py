"""Acces la date pentru sarcini.

Lista aduce într-o singură interogare și numele clientului și al responsabilului —
interfața le afișează pe fiecare card, iar altfel ar ieși două SELECT-uri per rând.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import case, select
from sqlalchemy.orm import Session, aliased

from app.domain.enums import TASK_STATUS_ORDER, TaskStatus
from app.models.client import Client
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskFilters


@dataclass(frozen=True, slots=True)
class TaskRow:
    """O sarcină plus numele pe care le afișează interfața."""

    task: Task
    client_name: str | None
    assignee_name: str | None


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, organization_id: uuid.UUID, filters: TaskFilters) -> list[TaskRow]:
        assignee = aliased(User)

        stmt = (
            select(Task, Client.name, assignee.full_name)
            .outerjoin(Client, Task.client_id == Client.id)
            .outerjoin(assignee, Task.assigned_to_id == assignee.id)
            .where(Task.organization_id == organization_id, Task.deleted_at.is_(None))
        )

        if filters.status is not None:
            stmt = stmt.where(Task.status == filters.status)
        if filters.assigned_to_id is not None:
            stmt = stmt.where(Task.assigned_to_id == filters.assigned_to_id)
        if filters.client_id is not None:
            stmt = stmt.where(Task.client_id == filters.client_id)

        # Ordinea din interfață: de făcut → în lucru → blocat → gata. `case` o duce
        # în SQL, ca sortarea să nu depindă de ordinea alfabetică a statusurilor.
        status_rank = case(
            {status.value: rank for status, rank in TASK_STATUS_ORDER.items()},
            value=Task.status,
            else_=len(TASK_STATUS_ORDER),
        )
        stmt = stmt.order_by(status_rank, Task.due_date.asc().nullslast(), Task.created_at)

        return [
            TaskRow(task=row[0], client_name=row[1], assignee_name=row[2])
            for row in self.session.execute(stmt).all()
        ]

    def get(self, organization_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
        return self.session.scalars(
            select(Task).where(
                Task.id == task_id,
                Task.organization_id == organization_id,
                Task.deleted_at.is_(None),
            )
        ).first()

    def describe(self, task: Task) -> TaskRow:
        """Numele pentru o singură sarcină — folosit după o actualizare."""
        assignee = aliased(User)
        row = self.session.execute(
            select(Client.name, assignee.full_name)
            .select_from(Task)
            .outerjoin(Client, Task.client_id == Client.id)
            .outerjoin(assignee, Task.assigned_to_id == assignee.id)
            .where(Task.id == task.id)
        ).first()
        if row is None:
            return TaskRow(task=task, client_name=None, assignee_name=None)
        return TaskRow(task=task, client_name=row[0], assignee_name=row[1])


__all__ = ["TaskRepository", "TaskRow", "TaskStatus"]
