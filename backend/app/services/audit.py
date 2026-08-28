"""Scrierea în jurnalul de audit (§31).

Un singur loc care știe cum arată o intrare, ca acțiunile să fie comparabile între
module. `request_id` se ia din contextul cererii, deci o intrare de audit poate fi
urmărită înapoi în loguri.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.models.audit import AuditLog


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        organization_id: uuid.UUID,
        action: str,
        entity_type: str,
        user_id: uuid.UUID | None,
        user_name: str,
        entity_id: str | None = None,
        detail: str | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            user_name=user_name,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            old_value=old_value,
            new_value=new_value,
            ip=ip,
            # Antetele de user-agent pot fi arbitrar de lungi; coloana are 255.
            user_agent=user_agent[:255] if user_agent else None,
            request_id=request_id_var.get(),
        )
        self.session.add(entry)
        return entry
