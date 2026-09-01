"""Jurnalul de audit (§31).

Append-only prin convenție: nimic din aplicație nu actualizează sau șterge rânduri
de aici. Nu are `updated_at` și nici `deleted_at` — un jurnal care poate fi rescris
nu este un jurnal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, uuid_pk


class AuditLog(Base, OrganizationMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
    )

    id: Mapped[uuid_pk]
    # Utilizatorul se păstrează chiar dacă e șters: cine a făcut acțiunea nu dispare.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[str | None] = mapped_column(String(512), default=None)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    # Leagă intrarea de linia de log a cererii care a produs-o.
    request_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # `clock_timestamp()`, nu `now()`: în Postgres `now()` întoarce momentul de
    # început al **tranzacției**, deci toate intrările scrise într-o cerere ar avea
    # exact aceeași valoare — iar ordinea lor ar deveni arbitrară. Un jurnal de
    # audit care nu se poate ordona nu spune ce s-a întâmplat după ce.
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"
