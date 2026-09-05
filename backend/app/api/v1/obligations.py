"""Termenele de depunere (§18).

Ecranul răspunde la o singură întrebare, care este cea pe care și-o pune un
cabinet dimineața: **ce am de depus și pentru cine, până când.**

Permisiunile refolosesc ce există. Citirea cere `clients:read` — termenele sunt
despre clienți. Marcarea unei depuneri și editarea catalogului cer
`periods:manage`: sunt decizii contabile, iar rolul care închide o lună este
același care știe ce s-a depus.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import Field

from app.api.deps import DbSession, require_permission
from app.api.route import CommittingRoute
from app.api.v1.periods import REFERENCE_MONTH
from app.domain.enums import ObligationFrequency
from app.domain.permissions import Permission
from app.models.obligation import ObligationType
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.obligations import (
    DEFAULT_HORIZON_DAYS,
    OVERDUE_LOOKBACK_DAYS,
    DueObligation,
    ObligationService,
)

router = APIRouter(route_class=CommittingRoute, prefix="/obligations", tags=["obligations"])

ObligationReader = Annotated[User, require_permission(Permission.CLIENTS_READ)]
ObligationManager = Annotated[User, require_permission(Permission.PERIODS_MANAGE)]


class ObligationTypeOut(ApiModel):
    id: uuid.UUID
    code: str
    label: str
    frequency: ObligationFrequency
    months_after: int
    deadline_day: int
    is_active: bool


class ObligationTypeIn(ApiModel):
    """Ce se poate schimba la o declarație.

    Codul nu: el leagă rândurile de depuneri deja existente, iar redenumirea lui
    ar rupe istoricul fără ca cineva să observe. Eticheta se poate schimba
    oricând — ea este doar ce citește omul.
    """

    label: str | None = Field(default=None, min_length=1, max_length=128)
    frequency: ObligationFrequency | None = None
    months_after: int | None = Field(default=None, ge=0, le=24)
    deadline_day: int | None = Field(default=None, ge=1, le=31)
    is_active: bool | None = None


class DueObligationOut(ApiModel):
    client_id: uuid.UUID
    client_name: str
    obligation_type_id: uuid.UUID
    code: str
    label: str
    frequency: ObligationFrequency
    #: Luna în care se **încheie** perioada acoperită, `YYYY-MM`.
    period: str
    deadline: date
    #: `null` = nedepus. Nu există o a treia stare.
    filed_at: datetime | None
    filed_by_name: str | None
    note: str | None
    #: Calculat aici, ca ecranul să nu compare date de unul singur și să ajungă,
    #: într-un fus orar, la alt răspuns decât serverul.
    is_overdue: bool


class FilingOut(ApiModel):
    """Ce s-a întâmplat la marcare, și nimic altceva.

    Nu un rând de listă: acela poartă și numele clientului, și termenul perioadei
    — lucruri pe care ruta aceasta ar trebui să le recompună ca să le poată
    întoarce. Recompuse greșit, ar arăta exact ca niște valori adevărate.
    Interfața reîncarcă lista, care le are din calcul.
    """

    client_id: uuid.UUID
    obligation_type_id: uuid.UUID
    period: str
    filed_at: datetime
    filed_by_name: str | None
    note: str | None


class FilingIn(ApiModel):
    client_id: uuid.UUID
    obligation_type_id: uuid.UUID
    period: str = Field(pattern=REFERENCE_MONTH)
    note: str | None = Field(default=None, max_length=255)


class FilingKey(ApiModel):
    """Tripletul care identifică o depunere, ca parametri de query.

    Model, nu parametri declarați unul câte unul: aceia ar rămâne `snake_case`,
    iar contractul este camelCase în ambele direcții. Aceeași lecție ca la
    filtrele de rapoarte — acolo un filtru ignorat în tăcere răspundea la altă
    întrebare; aici ștergerea ar fi refuzată cu 422 pentru un motiv care nu se
    vede de pe ecran.
    """

    client_id: uuid.UUID
    obligation_type_id: uuid.UUID
    period: str = Field(pattern=REFERENCE_MONTH)


class UpcomingFilters(ApiModel):
    client_id: uuid.UUID | None = None
    since: date | None = None
    until: date | None = None


class ClientObligationsIn(ApiModel):
    """Setul complet al clientului, nu o adăugare.

    Ecranul arată bifele tuturor declarațiilor; ce se trimite înapoi este starea
    de pe ecran. O rută care doar adaugă ar face imposibilă scoaterea uneia.
    """

    obligation_type_ids: list[uuid.UUID]


def _type_out(row: ObligationType) -> ObligationTypeOut:
    return ObligationTypeOut(
        id=row.id,
        code=row.code,
        label=row.label,
        frequency=row.frequency,
        months_after=row.months_after,
        deadline_day=row.deadline_day,
        is_active=row.is_active,
    )


def _due_out(row: DueObligation, today: date) -> DueObligationOut:
    return DueObligationOut(
        client_id=row.client_id,
        client_name=row.client_name,
        obligation_type_id=row.obligation_type_id,
        code=row.code,
        label=row.label,
        frequency=row.frequency,
        period=row.period,
        deadline=row.deadline,
        filed_at=row.filed_at,
        filed_by_name=row.filed_by_name,
        note=row.note,
        is_overdue=row.is_overdue(today),
    )


@router.get("/types", response_model=list[ObligationTypeOut])
def list_types(session: DbSession, user: ObligationReader) -> list[ObligationTypeOut]:
    """Catalogul cabinetului.

    Inclusiv declarațiile dezactivate: ecranul de administrare trebuie să poată
    reactiva una, iar una care dispare din listă când o dezactivezi nu se mai
    poate găsi.
    """
    return [_type_out(row) for row in ObligationService(session, user.organization_id).types()]


@router.patch("/types/{obligation_type_id}", response_model=ObligationTypeOut)
def update_type(
    session: DbSession,
    user: ObligationManager,
    obligation_type_id: uuid.UUID,
    payload: ObligationTypeIn,
) -> ObligationTypeOut:
    """Termenele sunt ale cabinetului, nu ale aplicației.

    Catalogul pornește cu valorile uzuale, dar aplicația nu pretinde că știe
    legea: cine constată că un termen este altul îl schimbă de aici, fără deploy.
    """
    service = ObligationService(session, user.organization_id)
    row = service.get_type(obligation_type_id)

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field_name, value in changes.items():
        setattr(row, field_name, value)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="OBLIGATION_TYPE_UPDATED",
        entity_type="ObligationType",
        entity_id=str(row.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=row.code,
        new_value={key: str(value) for key, value in changes.items()},
    )
    return _type_out(row)


@router.get("/clients/{client_id}", response_model=list[ObligationTypeOut])
def client_obligations(
    session: DbSession, user: ObligationReader, client_id: uuid.UUID
) -> list[ObligationTypeOut]:
    return [
        _type_out(row)
        for row in ObligationService(session, user.organization_id).for_client(client_id)
    ]


@router.put("/clients/{client_id}", response_model=list[ObligationTypeOut])
def set_client_obligations(
    session: DbSession,
    user: ObligationManager,
    client_id: uuid.UUID,
    payload: ClientObligationsIn,
) -> list[ObligationTypeOut]:
    service = ObligationService(session, user.organization_id)
    rows = service.set_for_client(client_id, payload.obligation_type_ids)

    AuditService(session).record(
        organization_id=user.organization_id,
        action="CLIENT_OBLIGATIONS_SET",
        entity_type="Client",
        entity_id=str(client_id),
        user_id=user.id,
        user_name=user.full_name,
        # Câte, nu care: jurnalul spune cine a schimbat ce configurare, nu
        # reproduce conținutul ei (§33).
        detail=f"{len(rows)} declarații",
    )
    return [_type_out(row) for row in rows]


@router.post("/filings", response_model=FilingOut, status_code=status.HTTP_201_CREATED)
def mark_filed(session: DbSession, user: ObligationManager, payload: FilingIn) -> FilingOut:
    """Marchează perioada ca depusă.

    Idempotent: a doua apăsare nu creează o a doua depunere și nu rescrie cine a
    depus prima oară.
    """
    service = ObligationService(session, user.organization_id)
    obligation = service.get_type(payload.obligation_type_id)
    filing = service.mark_filed(
        client_id=payload.client_id,
        obligation_type_id=obligation.id,
        period=payload.period,
        user=user,
        note=payload.note,
    )

    AuditService(session).record(
        organization_id=user.organization_id,
        action="OBLIGATION_FILED",
        entity_type="Client",
        entity_id=str(payload.client_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{obligation.code} · {payload.period}",
    )

    return FilingOut(
        client_id=filing.client_id,
        obligation_type_id=filing.obligation_type_id,
        period=filing.period,
        filed_at=filing.filed_at,
        filed_by_name=user.full_name,
        note=filing.note,
    )


@router.delete("/filings", status_code=status.HTTP_204_NO_CONTENT)
def unmark_filed(
    session: DbSession,
    user: ObligationManager,
    key: Annotated[FilingKey, Query()],
) -> Response:
    """Cineva a apăsat pe rândul greșit."""
    service = ObligationService(session, user.organization_id)
    service.unmark(
        client_id=key.client_id,
        obligation_type_id=key.obligation_type_id,
        period=key.period,
    )

    AuditService(session).record(
        organization_id=user.organization_id,
        action="OBLIGATION_UNFILED",
        entity_type="Client",
        entity_id=str(key.client_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{service.get_type(key.obligation_type_id).code} · {key.period}",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[DueObligationOut])
def upcoming(
    session: DbSession,
    user: ObligationReader,
    filters: Annotated[UpcomingFilters, Query()],
) -> list[DueObligationOut]:
    """Ce are termen în fereastră, depus sau nu.

    Fereastra implicită pornește **din urmă**: un termen ratat nu se rezolvă
    trecând timpul, iar o listă care ar începe de azi l-ar ascunde exact pe cel
    care contează cel mai mult.
    """
    today = datetime.now(UTC).date()
    rows = ObligationService(session, user.organization_id).upcoming(
        since=filters.since or today - timedelta(days=OVERDUE_LOOKBACK_DAYS),
        until=filters.until or today + timedelta(days=DEFAULT_HORIZON_DAYS),
        client_id=filters.client_id,
    )
    return [_due_out(row, today) for row in rows]
