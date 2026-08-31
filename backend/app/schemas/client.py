"""Schemele CRM.

Forma exactă a tipurilor `Client`, `Contact` și `ClientNote` din
`frontend/src/types/domain.ts`. Numele contabilului și al clientului sunt
denormalizate în răspuns pentru că interfața le afișează fără să mai ceară o rută.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.domain.enums import ClientStatus
from app.schemas.common import ApiModel
from app.schemas.email import EmailAddress


class ContactOut(ApiModel):
    id: uuid.UUID
    client_id: uuid.UUID
    full_name: str
    role: str
    email: EmailAddress | None
    phone: str | None
    whatsapp_number: str | None
    is_primary: bool
    is_active: bool


class ClientNoteOut(ApiModel):
    id: uuid.UUID
    client_id: uuid.UUID
    author_name: str
    body: str
    created_at: datetime


class ClientOut(ApiModel):
    id: uuid.UUID
    name: str
    tax_id: str | None
    registration_number: str | None
    address: str
    status: ClientStatus
    assigned_accountant_id: uuid.UUID | None
    assigned_accountant_name: str | None
    tags: list[str]
    last_interaction_at: datetime | None
    created_at: datetime


class ClientFilters(ApiModel):
    """Filtrele pe care le trimite `clients-page.tsx`."""

    q: str | None = Field(default=None, max_length=200)
    status: ClientStatus | None = None
    accountant_id: uuid.UUID | None = None
