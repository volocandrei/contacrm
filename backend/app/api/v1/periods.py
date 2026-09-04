"""Perioadele contabile și raportul de documente lipsă (§18, §19).

Forma răspunsului este cea pe care ecranele de contabilitate o consumă deja din
backendul simulat: `AccountingPeriod` și `MissingDocumentsEntry` din
`frontend/src/types/domain.ts`.

Citirea cere `documents:read` — cine vede documentele vede și starea lunii.
Închiderea cere `periods:manage`: a declara o lună gata este un act contabil, nu o
consultare.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DbSession, client_ip, require_permission
from app.core.errors import NotFoundError
from app.domain.enums import PeriodStatus
from app.domain.periods import ChecklistEntry
from app.domain.permissions import Permission
from app.models.document import DocumentType
from app.models.period import ClientExpectation
from app.models.user import User
from app.repositories.client import ClientRepository
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.period_service import PeriodService, PeriodView

router = APIRouter(tags=["contabilitate"])

PeriodReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]
PeriodManager = Annotated[User, require_permission(Permission.PERIODS_MANAGE)]

REFERENCE_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"

#: Cât de multe documente de un fel se pot aștepta într-o lună. Generos pentru un
#: client cu multe facturi, strâmt cât o greșeală de tastare să nu treacă.
MAX_EXPECTED_COUNT = 999


class ChecklistItemOut(ApiModel):
    document_type: str
    document_type_label: str
    expected_min_count: int
    received_count: int
    is_satisfied: bool


class ExpectationOut(ApiModel):
    """Un tip de document pe care îl așteptăm lunar de la un client.

    Tipul se numește prin **cod**, nu prin identificator: așa îl numește tot
    restul contractului (`documentTypeCode` pe document, `documentType` în
    checklist), iar `GET /document-types` nici nu publică id-uri. Un id intern
    scos aici doar pentru ruta asta ar fi fost un al doilea vocabular.
    """

    document_type_code: str
    document_type_label: str
    expected_min_count: int


class ExpectationIn(ApiModel):
    document_type_code: str = Field(min_length=1, max_length=64)
    #: Cel puțin unul: o așteptare de zero documente nu este o așteptare, este
    #: absența ei — și se exprimă scoțând rândul din listă.
    expected_min_count: int = Field(ge=1, le=MAX_EXPECTED_COUNT)


class ExpectationsIn(ApiModel):
    """Lista completă, nu o modificare.

    Ecranul arată toate tipurile de document deodată, cu bifă și număr; ce
    trimite înapoi este starea de după, întreagă. O rută care primește
    diferențe ar fi cerut interfeței să țină minte ce a schimbat, iar două
    tab-uri deschise ar fi produs rezultate care depind de ordine.
    """

    expectations: list[ExpectationIn]


class AccountingPeriodOut(ApiModel):
    # `null` cât timp nimeni nu a atins luna administrativ: perioada există prin
    # documentele din ea, dar nu are încă rând propriu.
    id: uuid.UUID | None
    client_id: uuid.UUID
    client_name: str
    year: int
    month: int
    reference_month: str
    status: PeriodStatus
    # Toate documentele primite pentru client în luna respectivă, de orice tip.
    received_count: int
    # Câte dintre cele **așteptate** au sosit: suma pe checklist a lui
    # min(primite, minim cerut). O factură în plus nu compensează un extras lipsă.
    satisfied_count: int
    expected_count: int
    checklist: list[ChecklistItemOut]
    opened_at: datetime | None
    closed_at: datetime | None
    completed_at: datetime | None


class MissingDocumentsEntryOut(ApiModel):
    period: AccountingPeriodOut
    missing: list[ChecklistItemOut]


class ClosePeriodIn(ApiModel):
    # Închiderea peste un checklist incomplet este posibilă, dar trebuie cerută.
    force: bool = False


class PeriodFilters(ApiModel):
    """Filtrele ecranului de perioade.

    Model, nu parametri separați: `ApiModel` aplică `alias_generator=to_camel`, deci
    numele din query sunt cele pe care le trimite frontend-ul (`referenceMonth`).
    Parametrii declarați unul câte unul ar rămâne `snake_case` și ar fi ignorați în
    tăcere — filtrul nu ar da eroare, doar ar returna tot.
    """

    reference_month: str | None = Field(default=None, pattern=REFERENCE_MONTH)
    client_id: uuid.UUID | None = None
    status: PeriodStatus | None = None


class MissingFilters(ApiModel):
    reference_month: str = Field(pattern=REFERENCE_MONTH)


def _to_item(entry: ChecklistEntry) -> ChecklistItemOut:
    return ChecklistItemOut(
        document_type=entry.document_type,
        document_type_label=entry.document_type_label,
        expected_min_count=entry.expected_min_count,
        received_count=entry.received_count,
        is_satisfied=entry.is_satisfied,
    )


def _known_types(session: DbSession, organization_id: uuid.UUID) -> dict[str, DocumentType]:
    """Tipurile organizației, după cod — cum le numește contractul."""
    return {
        row.code: row
        for row in session.scalars(
            select(DocumentType).where(DocumentType.organization_id == organization_id)
        )
    }


def _expectations_of(
    session: DbSession, organization_id: uuid.UUID, client_id: uuid.UUID
) -> list[ExpectationOut]:
    """Așteptările clientului, în ordinea în care tipurile apar pe ecran."""
    rows = session.execute(
        select(ClientExpectation, DocumentType)
        .join(DocumentType, DocumentType.id == ClientExpectation.document_type_id)
        .where(
            ClientExpectation.organization_id == organization_id,
            ClientExpectation.client_id == client_id,
        )
        .order_by(DocumentType.sort_order, DocumentType.label)
    ).all()
    return [
        ExpectationOut(
            document_type_code=document_type.code,
            document_type_label=document_type.label,
            expected_min_count=expectation.expected_min_count,
        )
        for expectation, document_type in rows
    ]


def to_period(view: PeriodView) -> AccountingPeriodOut:
    return AccountingPeriodOut(
        id=view.id,
        client_id=view.client_id,
        client_name=view.client_name,
        year=view.year,
        month=view.month,
        reference_month=view.reference_month,
        status=view.status,
        received_count=view.received_count,
        satisfied_count=view.satisfied_count,
        expected_count=view.expected_count,
        checklist=[_to_item(item) for item in view.checklist],
        opened_at=view.opened_at,
        closed_at=view.closed_at,
        completed_at=view.completed_at,
    )


@router.get("/periods", response_model=list[AccountingPeriodOut])
def list_periods(
    session: DbSession,
    user: PeriodReader,
    filters: Annotated[PeriodFilters, Query()],
) -> list[AccountingPeriodOut]:
    views = PeriodService(session).list_periods(
        user.organization_id,
        reference_month=filters.reference_month,
        client_id=filters.client_id,
        status=filters.status,
    )
    return [to_period(view) for view in views]


@router.get("/periods/missing", response_model=list[MissingDocumentsEntryOut])
def missing_documents(
    session: DbSession,
    user: PeriodReader,
    filters: Annotated[MissingFilters, Query()],
) -> list[MissingDocumentsEntryOut]:
    """Ce se așteaptă și încă nu a sosit, per client (§19).

    Doar clienții cărora chiar le lipsește ceva. Un raport care listează și clienții
    în regulă ajunge să nu mai fie citit, iar atunci nu mai raportează nimic.
    """
    return [
        MissingDocumentsEntryOut(period=to_period(view), missing=[_to_item(m) for m in gaps])
        for view, gaps in PeriodService(session).missing(
            user.organization_id, filters.reference_month
        )
    ]


@router.get("/clients/{client_id}/periods", response_model=list[AccountingPeriodOut])
def client_periods(
    session: DbSession, user: PeriodReader, client_id: uuid.UUID
) -> list[AccountingPeriodOut]:
    """Lunile unui client.

    Clientul se verifică explicit: fără asta, unul din altă organizație ar primi o
    listă goală în loc de 404 — nu o scurgere de date, dar o diferență de
    comportament față de restul rutelor pe același client, iar diferența aceea
    confirmă că id-ul nu există nicăieri. Nu este treaba noastră să o confirmăm.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)

    views = PeriodService(session).list_periods(user.organization_id, client_id=client_id)
    return [to_period(view) for view in views]


@router.get("/clients/{client_id}/expectations", response_model=list[ExpectationOut])
def client_expectations(
    session: DbSession, user: PeriodReader, client_id: uuid.UUID
) -> list[ExpectationOut]:
    """Ce se așteaptă lunar de la un client.

    Fără ea, checklistul lunii este gol, „Documente lipsă" nu are ce raporta, iar
    o perioadă apare `COMPLETE` pentru că nu i se cerea nimic. Datele existau în
    `client_expectations` de la M6; nu exista niciun drum prin care cineva să le
    scrie sau măcar să le vadă.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)
    return _expectations_of(session, user.organization_id, client_id)


@router.put("/clients/{client_id}/expectations", response_model=list[ExpectationOut])
def set_client_expectations(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    client_id: uuid.UUID,
    payload: ExpectationsIn,
) -> list[ExpectationOut]:
    """Înlocuiește lista, nu o modifică.

    Cere `periods:manage`: a hotărî ce datorează un client în fiecare lună este
    o decizie contabilă, nu o editare de fișă. Aceeași permisiune ca închiderea
    lunii, și din același motiv.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)

    known = _known_types(session, user.organization_id)
    wanted: dict[uuid.UUID, int] = {}
    for entry in payload.expectations:
        document_type = known.get(entry.document_type_code)
        if document_type is None:
            raise NotFoundError("Tip de document", entry.document_type_code)
        # Ultima valoare câștigă: un formular care trimite același tip de două ori
        # este o greșeală de interfață, nu un motiv de 500.
        wanted[document_type.id] = entry.expected_min_count

    before = _expectations_of(session, user.organization_id, client_id)
    existing = {
        row.document_type_id: row
        for row in session.scalars(
            select(ClientExpectation).where(
                ClientExpectation.organization_id == user.organization_id,
                ClientExpectation.client_id == client_id,
            )
        )
    }

    for type_id, minimum in wanted.items():
        row = existing.get(type_id)
        if row is None:
            session.add(
                ClientExpectation(
                    organization_id=user.organization_id,
                    client_id=client_id,
                    document_type_id=type_id,
                    expected_min_count=minimum,
                )
            )
        else:
            row.expected_min_count = minimum
    for type_id, row in existing.items():
        if type_id not in wanted:
            # Ce nu mai apare în listă nu se mai așteaptă. Documentele deja
            # primite rămân — se schimbă așteptarea, nu istoria.
            session.delete(row)
    session.flush()

    after = _expectations_of(session, user.organization_id, client_id)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="CLIENT_EXPECTATIONS_UPDATED",
        entity_type="Client",
        entity_id=str(client_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{len(after)} tipuri așteptate lunar",
        old_value={"expectations": [item.model_dump(mode="json") for item in before]},
        new_value={"expectations": [item.model_dump(mode="json") for item in after]},
        ip=client_ip(request),
    )
    return after


@router.post(
    "/clients/{client_id}/periods/{reference_month}/close",
    response_model=AccountingPeriodOut,
)
def close_period(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    client_id: uuid.UUID,
    reference_month: Annotated[str, Path(pattern=REFERENCE_MONTH)],
    payload: ClosePeriodIn,
) -> AccountingPeriodOut:
    """Declară luna gata.

    Refuză dacă mai lipsesc documente așteptate, cu excepția cazului în care i se
    cere explicit (`force`). Există motive legitime — un client care chiar nu a avut
    extras de cont — dar sistemul nu le cunoaște, așa că cere o afirmație umană.
    """
    service = PeriodService(session)
    service.close(
        user.organization_id,
        client_id,
        reference_month,
        closed_by=user.id,
        force=payload.force,
    )
    _audit(session, user, request, "PERIOD_CLOSED", client_id, reference_month, payload.force)
    return to_period(service.get(user.organization_id, client_id, reference_month))


@router.post(
    "/clients/{client_id}/periods/{reference_month}/reopen",
    response_model=AccountingPeriodOut,
)
def reopen_period(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    client_id: uuid.UUID,
    reference_month: Annotated[str, Path(pattern=REFERENCE_MONTH)],
) -> AccountingPeriodOut:
    """Redeschide o lună închisă. Cine și când rămâne în audit."""
    service = PeriodService(session)
    service.reopen(user.organization_id, client_id, reference_month)
    _audit(session, user, request, "PERIOD_REOPENED", client_id, reference_month, False)
    return to_period(service.get(user.organization_id, client_id, reference_month))


def _audit(
    session: DbSession,
    user: User,
    request: Request,
    action: str,
    client_id: uuid.UUID,
    reference_month: str,
    forced: bool,
) -> None:
    AuditService(session).record(
        organization_id=user.organization_id,
        action=action,
        entity_type="AccountingPeriod",
        entity_id=f"{client_id}:{reference_month}",
        user_id=user.id,
        user_name=user.full_name,
        detail=reference_month + (" (forțat)" if forced else ""),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    session.flush()
