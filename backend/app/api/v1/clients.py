"""Rutele CRM.

Contractul este cel pe care `clients-page.tsx` și `client-detail-page.tsx` îl
consumă deja din backendul simulat: aceleași filtre, aceeași paginare, aceleași
câmpuri.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import DbSession, client_ip, require_permission
from app.api.v1.documents import to_list_item
from app.api.v1.periods import MissingFilters
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.domain.periods import filing_deadline
from app.domain.permissions import Permission
from app.models.client import Client
from app.models.organization import Organization
from app.models.user import User
from app.repositories.client import ClientRepository
from app.repositories.document import DocumentRepository
from app.schemas.client import (
    ClientCreate,
    ClientFilters,
    ClientNoteCreate,
    ClientNoteOut,
    ClientOut,
    ClientUpdate,
    ContactCreate,
    ContactOut,
    ContactUpdate,
)
from app.schemas.common import ApiModel, PageParams, Paginated
from app.schemas.document import DocumentFilters, DocumentListItemOut
from app.services.audit import AuditService
from app.services.client_aliases import ClientAliasService
from app.services.client_service import ActorContext, ClientService
from app.services.document_request import build_request_message
from app.services.period_service import PeriodService

router = APIRouter(prefix="/clients", tags=["crm"])

ClientReader = Annotated[User, require_permission(Permission.CLIENTS_READ)]
ClientWriter = Annotated[User, require_permission(Permission.CLIENTS_WRITE)]


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


class ClientAliasOut(ApiModel):
    """Ce a învățat sistemul despre cine trimite documentele acestui client."""

    id: uuid.UUID
    kind: str
    value: str
    matched_count: int
    created_at: datetime


@router.get("/{client_id}/aliases", response_model=list[ClientAliasOut])
def list_aliases(
    session: DbSession, user: ClientReader, client_id: uuid.UUID
) -> list[ClientAliasOut]:
    """Adresele de la care documentele ajung singure la clientul ăsta.

    **De ce se văd.** Sistemul învață din atribuirile făcute de oameni: după ce
    cineva atribuie un document venit de la o adresă, următoarele merg singure
    acolo. Un alias pus din greșeală ar misruta tăcut, lună de lună — de aceea
    lista este vizibilă și fiecare rând se poate șterge.
    """
    aliases = ClientAliasService(session).for_client(user.organization_id, client_id)
    return [
        ClientAliasOut(
            id=alias.id,
            kind=alias.kind.value,
            value=alias.value,
            matched_count=alias.matched_count,
            created_at=alias.created_at,
        )
        for alias in aliases
    ]


@router.delete("/{client_id}/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget_alias(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    client_id: uuid.UUID,
    alias_id: uuid.UUID,
) -> None:
    """Uită ce a învățat de la o adresă.

    Cere `clients:write`, nu doar citire: ștergerea schimbă unde ajung
    documentele viitoare.
    """
    del client_id  # aliasul se identifică singur; clientul stă în adresă pentru citit
    alias = ClientAliasService(session).forget(user.organization_id, alias_id)
    if alias is None:
        raise NotFoundError("Alias", alias_id)

    AuditService(session).record(
        organization_id=user.organization_id,
        action="CLIENT_ALIAS_FORGOTTEN",
        entity_type="ClientAlias",
        entity_id=str(alias_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=alias.value,
        ip=client_ip(request),
    )


class DocumentRequestOut(ApiModel):
    """Solicitarea de documente, gata de trimis."""

    message: str


@router.get("/{client_id}/document-request", response_model=DocumentRequestOut)
def document_request(
    session: DbSession,
    user: ClientReader,
    client_id: uuid.UUID,
    filters: Annotated[MissingFilters, Query()],
) -> DocumentRequestOut:
    """Textul prin care i se cer clientului documentele lipsă.

    **De ce vine de la server.** Mesajul spune numele cabinetului, listează ce
    lipsește și dă termenul lunii: este conținut de business, nu formatare de
    ecran. A stat o vreme în frontend, unde îl folosea butonul „Copiază
    solicitarea". Din momentul în care îl cere și asistentul, două implementări
    ar însemna că doi clienți primesc, în aceeași zi, două mesaje diferite de la
    același cabinet.

    Nu trimite nimic. Trimiterea cere un provider și rămâne în Faza 2; până
    atunci textul pleacă din clientul de email al contabilului, cu semnătura lui.
    """
    client = ClientRepository(session).get(user.organization_id, client_id)
    if client is None:
        raise NotFoundError("Client", client_id)

    views = PeriodService(session).list_periods(
        user.organization_id, reference_month=filters.reference_month, client_id=client_id
    )
    missing = [item for item in views[0].checklist if not item.is_satisfied] if views else []
    if not missing:
        raise ValidationError(
            "Clientul nu are documente lipsă în luna cerută.",
            {"referenceMonth": ["Nimic de cerut."]},
        )

    organization = session.get(Organization, user.organization_id)
    return DocumentRequestOut(
        message=build_request_message(
            client_name=client.name,
            reference_month=filters.reference_month,
            deadline=filing_deadline(filters.reference_month, day=settings.filing_deadline_day),
            missing=missing,
            organization_name=organization.name if organization else "Cabinetul dumneavoastră",
        )
    )


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


# ── Scriere (§61) ────────────────────────────────────────────────────────────
#
# **Nu există ștergere, deliberat.** Un client cu documente este istorie
# contabilă; ce se cere de fapt este „nu mai lucrez cu el", iar asta se face
# trecându-l în `INACTIVE`. O rută `DELETE` ar fi arătat ca soluția evidentă
# exact în momentul greșit.


def _actor(user: User, request: Request) -> ActorContext:
    return ActorContext(
        user=user, ip=client_ip(request), user_agent=request.headers.get("User-Agent")
    )


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    payload: ClientCreate,
) -> ClientOut:
    repository = ClientRepository(session)
    client = ClientService(session).create(
        user.organization_id, payload.model_dump(), _actor(user, request)
    )
    return _to_out(client, repository.accountant_names([client]))


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    client_id: uuid.UUID,
    payload: ClientUpdate,
) -> ClientOut:
    repository = ClientRepository(session)
    client = ClientService(session).update(
        user.organization_id,
        client_id,
        # `exclude_unset`: un câmp netrimis nu se atinge, unul trimis `null` se
        # golește. Fără el, un formular care trimite doar statusul ar șterge CUI-ul.
        payload.model_dump(exclude_unset=True),
        _actor(user, request),
    )
    return _to_out(client, repository.accountant_names([client]))


@router.post(
    "/{client_id}/notes", response_model=ClientNoteOut, status_code=status.HTTP_201_CREATED
)
def create_note(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    client_id: uuid.UUID,
    payload: ClientNoteCreate,
) -> ClientNoteOut:
    """Scrie o notă internă pe client.

    Nu există modificare și nu există ștergere, deliberat: o notă este o
    consemnare, iar o consemnare care se poate rescrie nu mai este una. Când
    cineva greșește, se scrie următoarea.
    """
    note = ClientService(session).add_note(
        user.organization_id, client_id, payload.model_dump(), _actor(user, request)
    )
    return ClientNoteOut.model_validate(note)


@router.post(
    "/{client_id}/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED
)
def create_contact(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    client_id: uuid.UUID,
    payload: ContactCreate,
) -> ContactOut:
    contact = ClientService(session).add_contact(
        user.organization_id, client_id, payload.model_dump(), _actor(user, request)
    )
    return ContactOut.model_validate(contact)


@router.patch("/{client_id}/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    session: DbSession,
    user: ClientWriter,
    request: Request,
    client_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: ContactUpdate,
) -> ContactOut:
    contact = ClientService(session).update_contact(
        user.organization_id,
        client_id,
        contact_id,
        payload.model_dump(exclude_unset=True),
        _actor(user, request),
    )
    return ContactOut.model_validate(contact)
