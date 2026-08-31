"""Sarcini interne (§4).

O sarcină poate exista fără client („actualizează șabloanele de email") și fără
responsabil (nealocată încă), de aceea ambele legături sunt opționale.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import TaskPriority, TaskStatus
from app.models.base import (
    Base,
    EnumString,
    OrganizationMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid_pk,
)


class Task(Base, OrganizationMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('TODO', 'IN_PROGRESS', 'BLOCKED', 'DONE')", name="status"),
        CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')", name="priority"),
        # O sarcină este gata dacă și numai dacă are dată de finalizare.
        CheckConstraint("(status = 'DONE') = (completed_at IS NOT NULL)", name="completed_at"),
        Index("ix_tasks_organization_id_status", "organization_id", "status"),
        Index("ix_tasks_assigned_to_id", "assigned_to_id"),
        Index("ix_tasks_client_id", "client_id"),
        Index("ix_tasks_due_date", "due_date"),
    )

    id: Mapped[uuid_pk]
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), default=None
    )
    # SET NULL: plecarea unui coleg nu șterge sarcina, o lasă nealocată.
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    priority: Mapped[TaskPriority] = mapped_column(
        EnumString(TaskPriority, 16), default=TaskPriority.NORMAL, nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        EnumString(TaskStatus, 16), default=TaskStatus.TODO, nullable=False
    )
    # Termenul este o zi calendaristică, nu un moment: „până vineri", nu „vineri 17:00".
    due_date: Mapped[date | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)

    def __repr__(self) -> str:
        return f"<Task {self.title!r} {self.status}>"
