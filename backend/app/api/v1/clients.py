"""Rutele CRM.

Contractul este cel pe care `clients-page.tsx` și `client-detail-page.tsx` îl
consumă deja din backendul simulat: aceleași filtre, aceeași paginare, aceleași
câmpuri.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_permission
from app.api.v1.documents import to_list_item
from app.core.errors import NotFoundError
from app.domain.permissions import Permission
from app.models.client import Client
from app.models.user import User
from app.repositories.client import ClientRepository
from app.repositories.document import DocumentRepository
from app.schemas.client import ClientFilters, ClientNoteOut, ClientOut, ContactOut
from app.schemas.common import PageParams, Paginated
from app.schemas.document import DocumentFilters, DocumentListItemOut

router = APIRouter(prefix="/clients", tags=["crm"])

ClientReader = Annotated[User, require_permission(Permission.CLIENTS_READ)]


def _to_out(client: Client, accountant_names: dict[uuid.UUID, str]) -> ClientOut:
    return ClientOut(
        id=client.id,
        name=client.name,
        tax_id=client.tax_id,
        registration_number=client.registration_number,
        address=client.address,
        status=client.status,
        assigned_accountant_id=client.assigned_accountant_id,
        assigned_accountant_name=(
            accountant_names.get(client.assigned_accountant_id)
            if client.assigned_accountant_id
            else None
        ),
        tags=client.tag_names,
        last_interaction_at=client.last_interaction_at,
        created_at=client.created_at,
    )


@router.get("", response_model=Paginated[ClientOut])
def list_clients(
    session: DbSession,
    user: ClientReader,
    filters: Annotated[ClientFilters, Depends()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[ClientOut]:
    repository = ClientRepository(session)
    clients, total = repository.list(user.organization_id, filters, page)
    names = repository.accountant_names(clients)
    return Paginated[ClientOut].build(
        items=[_to_out(client, names) for client in clients],
        total=total,
        params=page,
    )


@router.get("/{client_id}", response_model=ClientOut)
def get_client(session: DbSession, user: ClientReader, client_id: uuid.UUID) -> ClientOut:
    repository = ClientRepository(session)
    client = repository.get(user.organization_id, client_id)
    if client is None:
        # Un client din altă organizație dă tot NOT_FOUND, nu FORBIDDEN: altfel
        # răspunsul confirmă că id-ul există undeva.
        raise NotFoundError("Client", client_id)
    return _to_out(client, repository.accountant_names([client]))


@router.get("/{client_id}/contacts", response_model=list[ContactOut])
def list_contacts(session: DbSession, user: ClientReader, client_id: uuid.UUID) -> list[ContactOut]:
    repository = ClientRepository(session)
    if repository.get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)
    return [
        ContactOut.model_validate(contact)
        for contact in repository.contacts(user.organization_id, client_id)
    ]


@router.get("/{client_id}/notes", response_model=list[ClientNoteOut])
def list_notes(session: DbSession, user: ClientReader, client_id: uuid.UUID) -> list[ClientNoteOut]:
    repository = ClientRepository(session)
    if repository.get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)
    return [
        ClientNoteOut.model_validate(note)
        for note in repository.notes(user.organization_id, client_id)
    ]


@router.get("/{client_id}/documents", response_model=Paginated[DocumentListItemOut])
def list_client_documents(
    session: DbSession,
    user: ClientReader,
    client_id: uuid.UUID,
    filters: Annotated[DocumentFilters, Query()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[DocumentListItemOut]:
    """Documentele unui client (§35).

    Filtrul de client vine din calea rutei, nu din query — altfel un utilizator ar
    putea cere documentele altui client prin parametru.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)

    scoped = filters.model_copy(update={"client_id": client_id})
    rows, total = DocumentRepository(session).list(user.organization_id, scoped, page)
    return Paginated[DocumentListItemOut].build(
        items=[to_list_item(row) for row in rows], total=total, params=page
    )
