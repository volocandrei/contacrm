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

from app.api.deps import DbSession, client_ip, require_permission
from app.core.errors import NotFoundError
from app.domain.enums import PeriodStatus
from app.domain.periods import ChecklistEntry
from app.domain.permissions import Permission
from app.models.user import User
from app.repositories.client import ClientRepository
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.period_service import PeriodService, PeriodView

router = APIRouter(tags=["contabilitate"])

PeriodReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]
PeriodManager = Annotated[User, require_permission(Permission.PERIODS_MANAGE)]

REFERENCE_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class ChecklistItemOut(ApiModel):
    document_type: str
    document_type_label: str
    expected_min_count: int
    received_count: int
    is_satisfied: bool


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
