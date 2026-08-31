"""Statusurile de domeniu.

Oglinda exactă a listelor din `frontend/src/types/domain.ts` (§53). Cele două sunt
comparate automat de `tests/test_contract_enums.py` — statusurile trăiesc într-un
singur loc conceptual, chiar dacă sunt scrise în două limbaje.

Se stochează ca text în baza de date, nu ca `ENUM` nativ: un tip enum Postgres cere
o migrare pentru fiecare valoare nouă, iar statusurile astea se vor extinde.
Constrângerea o impune aplicația, plus un CHECK în migrare.
"""

from __future__ import annotations

from enum import StrEnum


class ClientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PROSPECT = "PROSPECT"
    SUSPENDED = "SUSPENDED"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class TaskPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class DocumentStatus(StrEnum):
    """Definit acum pentru că `documents` apare în M5, dar contractul e deja fix."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    UNMATCHED = "UNMATCHED"


class DocumentSource(StrEnum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    UPLOAD = "UPLOAD"
    API = "API"


class PeriodStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING = "COLLECTING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"


# Ordinea în care sarcinile apar în interfață: ce e de făcut, înaintea ce e gata.
TASK_STATUS_ORDER: dict[TaskStatus, int] = {
    TaskStatus.TODO: 0,
    TaskStatus.IN_PROGRESS: 1,
    TaskStatus.BLOCKED: 2,
    TaskStatus.DONE: 3,
}
