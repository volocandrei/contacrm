"""Ce a sosit, de la cine și când — cronologia recepțiilor (M12).

**De ce există ruta asta și de ce nu se numește `/messages`.** Interfața a avut
un ecran „Mesaje" care cerea `GET /messages`, o rută care nu a existat niciodată:
în modul simulat mergea, în cel real rămânea gol fără să spună nimic. Auditul de
producție l-a scos, iar în locul lui a rămas o pagină care explica cinstit că
sistemul nu trimite încă mesaje.

Explicația era adevărată, dar ecranul rămânea gol degeaba: **jumătate din
cronologie exista deja în date.** Fiecare atașament de email, fiecare fișier din
OneDrive și fiecare factură din SPV lasă un `document_intakes` cu expeditorul,
subiectul și momentul. Ce lipsea era o rută care să le arate.

Ruta se numește după ce arată — recepții, nu mesaje. Când sistemul va și trimite,
partea aceea se va adăuga; până atunci numele nu promite ce nu există.

**Ce nu iese pe aici (§73):** `raw_payload`. El poartă căi din OneDrive și
identificatori interni ai furnizorului, adică exact lucrurile care nu au ce căuta
într-un răspuns. Se publică doar câmpuri alese pe nume.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, require_permission
from app.api.route import CommittingRoute
from app.core.errors import NotFoundError
from app.domain.enums import DocumentSource, IntakeStatus
from app.domain.permissions import Permission
from app.models.client import Client
from app.models.document import Document, DocumentIntake
from app.models.user import User
from app.repositories.client import ClientRepository
from app.schemas.common import ApiModel, PageParams, Paginated

router = APIRouter(route_class=CommittingRoute, tags=["comunicare"])

IntakeReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]


class IntakeOut(ApiModel):
    """O recepție: un fișier care a intrat, cu de unde a venit."""

    id: uuid.UUID
    source: DocumentSource
    status: IntakeStatus
    #: Cine l-a trimis — adresa de email, dosarul din OneDrive, CUI-ul din SPV.
    sender: str | None
    subject: str | None
    original_filename: str
    received_at: datetime
    #: Documentul creat, când a fost creat. `null` pentru o recepție respinsă.
    document_id: uuid.UUID | None
    #: Clientul căruia i-a fost atribuit documentul, dacă s-a putut.
    client_id: uuid.UUID | None
    client_name: str | None
    #: De ce a fost respinsă, în cuvintele sistemului. `null` când nu a fost.
    rejection_reason: str | None


class IntakeFilters(ApiModel):
    client_id: uuid.UUID | None = None
    source: DocumentSource | None = None
    status: IntakeStatus | None = None


def _to_out(
    intake: DocumentIntake, client_name: str | None, client_id: uuid.UUID | None
) -> IntakeOut:
    return IntakeOut(
        id=intake.id,
        source=intake.source,
        status=intake.status,
        sender=intake.sender,
        subject=intake.subject,
        original_filename=intake.original_filename,
        received_at=intake.received_at,
        document_id=intake.document_id,
        client_id=client_id,
        client_name=client_name,
        rejection_reason=intake.rejection_reason,
    )


def _conditions(organization_id: uuid.UUID, filters: IntakeFilters) -> list[Any]:
    """Ce restrânge lista. Aceleași pentru pagină și pentru numărare.

    Clientul stă pe **document**, nu pe recepție: la momentul recepției încă nu se
    știe al cui este. De aceea filtrul pe client trece prin join, nu direct.
    """
    where: list[Any] = [DocumentIntake.organization_id == organization_id]
    if filters.client_id is not None:
        where.append(Document.client_id == filters.client_id)
    if filters.source is not None:
        where.append(DocumentIntake.source == filters.source)
    if filters.status is not None:
        where.append(DocumentIntake.status == filters.status)
    return where


def _page(
    session: DbSession,
    organization_id: uuid.UUID,
    filters: IntakeFilters,
    page: PageParams,
) -> Paginated[IntakeOut]:
    where = _conditions(organization_id, filters)

    # `LEFT JOIN` de două ori: o recepție respinsă nu are document, iar un
    # document neatribuit nu are client.
    rows = session.execute(
        select(DocumentIntake, Client.name, Document.client_id)
        .outerjoin(Document, Document.id == DocumentIntake.document_id)
        .outerjoin(Client, Client.id == Document.client_id)
        .where(*where)
        .order_by(DocumentIntake.received_at.desc(), DocumentIntake.id)
        .limit(page.page_size)
        .offset((page.page - 1) * page.page_size)
    ).all()

    # Numai cheia în numărare: o proiecție întreagă ar aduce și `raw_payload`,
    # exact ce nu vrem să atingem.
    total = (
        session.scalar(
            select(func.count())
            .select_from(DocumentIntake)
            .outerjoin(Document, Document.id == DocumentIntake.document_id)
            .where(*where)
        )
        or 0
    )

    return Paginated[IntakeOut].build(
        items=[_to_out(intake, name, client_id) for intake, name, client_id in rows],
        total=total,
        params=page,
    )


@router.get("/intakes", response_model=Paginated[IntakeOut])
def list_intakes(
    session: DbSession,
    user: IntakeReader,
    filters: Annotated[IntakeFilters, Query()],
    page: Annotated[PageParams, Depends()],
) -> Paginated[IntakeOut]:
    """Tot ce a sosit, de la cine și când."""
    return _page(session, user.organization_id, filters, page)


@router.get("/clients/{client_id}/intakes", response_model=Paginated[IntakeOut])
def client_intakes(
    session: DbSession,
    user: IntakeReader,
    client_id: uuid.UUID,
    page: Annotated[PageParams, Depends()],
) -> Paginated[IntakeOut]:
    """Cronologia unui singur client.

    Filtrul vine din calea rutei, nu din query: altfel cineva ar putea cere
    recepțiile altui client printr-un parametru.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)
    return _page(session, user.organization_id, IntakeFilters(client_id=client_id), page)
