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


class ClientCreate(ApiModel):
    """Ce trimite formularul de client nou.

    Doar denumirea este obligatorie. Un prospect care încă nu și-a trimis datele
    are drept la un rând în CRM — restul se completează când se știe.
    """

    name: str = Field(min_length=1, max_length=255)
    tax_id: str | None = Field(default=None, max_length=32)
    registration_number: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=2000)
    #: Implicit ACTIVE: cine adaugă un client îi ține contabilitatea. `PROSPECT`
    #: rămâne disponibil pentru cineva cu care se discută încă.
    status: ClientStatus = ClientStatus.ACTIVE
    assigned_accountant_id: uuid.UUID | None = None


class ClientUpdate(ApiModel):
    """Modificarea unui client. Câmpurile **netrimise** rămân neatinse.

    `None` și „absent" înseamnă lucruri diferite: primul golește câmpul, al
    doilea nu îl atinge. Distincția se face cu `exclude_unset`, în rută.
    """

    name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=32)
    registration_number: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=2000)
    status: ClientStatus | None = None
    assigned_accountant_id: uuid.UUID | None = None


class ContactCreate(ApiModel):
    """Persoana de contact.

    **Adresa de email nu este un detaliu.** După ea ajunge un atașament primit la
    clientul potrivit (§8). Un client fără contact primește documente doar prin
    dosarul lui din OneDrive.
    """

    full_name: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=128)
    email: EmailAddress | None = None
    phone: str | None = Field(default=None, max_length=32)
    whatsapp_number: str | None = Field(default=None, max_length=32)
    is_primary: bool = False
    is_active: bool = True


class ContactUpdate(ApiModel):
    """La fel ca la client: ce nu se trimite nu se schimbă."""

    full_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=128)
    email: EmailAddress | None = None
    phone: str | None = Field(default=None, max_length=32)
    whatsapp_number: str | None = Field(default=None, max_length=32)
    is_primary: bool | None = None
    is_active: bool | None = None


class ClientFilters(ApiModel):
    """Filtrele pe care le trimite `clients-page.tsx`."""

    q: str | None = Field(default=None, max_length=200)
    status: ClientStatus | None = None
    accountant_id: uuid.UUID | None = None
