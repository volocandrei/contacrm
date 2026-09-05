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
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, status
from pydantic import Field, StringConstraints
from sqlalchemy import select

from app.api.deps import DbSession, client_ip, require_permission
from app.api.route import CommittingRoute
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.domain.enums import PeriodStatus
from app.domain.periods import ChecklistEntry, filing_deadline
from app.domain.permissions import Permission
from app.models.document import DocumentType
from app.models.period import ClientExpectation
from app.models.user import User
from app.repositories.client import ClientRepository
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.expectation_templates import (
    ExpectationTemplateService,
    TemplateView,
    replace_expectations,
)
from app.services.period_service import PeriodService, PeriodView
from app.services.upload_links import RequestTrace, UploadLinkService

router = APIRouter(route_class=CommittingRoute, tags=["contabilitate"])

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


#: Câți clienți poate atinge o singură aplicare de șablon.
#:
#: Nu este o limită de performanță, ci una de reversibilitate: aplicarea
#: **înlocuiește** listele, iar o greșeală pe toți clienții cabinetului deodată
#: se repară client cu client. Un cabinet mare selectează în două rânduri.
MAX_CLIENTS_PER_APPLY = 200


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


class ExpectationTemplateOut(ApiModel):
    """Un profil de client, cu numele pe care i-l dă cabinetul.

    `expectations` are exact forma listei unui client — același `ExpectationOut`
    — fiindcă asta și este: lista care i se va scrie. Două forme apropiate, dar
    nu identice, ar fi cerut interfeței să le traducă una în alta.
    """

    id: uuid.UUID
    name: str
    expectations: list[ExpectationOut]


#: Numele profilului, curățat înainte de validare. Fără `strip_whitespace`, un
#: nume din spații ar trece de `min_length` și ar ajunge în listă fără text.
TemplateName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class ExpectationTemplateIn(ApiModel):
    name: TemplateName
    expectations: list[ExpectationIn]


class TemplateFromClientIn(ApiModel):
    """Salvează ce s-a configurat deja pe un client, ca profil.

    Este drumul pe care se face primul șablon: cineva potrivește un client cu
    mâna, vede că e bun, și îi dă un nume — în loc să reintroducă aceleași bife
    într-un formular gol.
    """

    name: TemplateName


class ApplyTemplateIn(ApiModel):
    #: Cel puțin un client: o aplicare fără destinatar este o greșeală de
    #: interfață, nu o operație validă care nu face nimic.
    client_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_CLIENTS_PER_APPLY)


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
    #: Termenul de depunere al lunii, aceeași dată pentru toate rândurile. Se
    #: repetă pe fiecare intrare ca forma răspunsului să rămână o listă simplă.
    deadline: date
    #: Când s-a pregătit ultima cerere pentru clientul ăsta, pe luna asta.
    #:
    #: **Nul înseamnă „nu i s-a cerut niciodată"** — și este cel mai util lucru
    #: de pe rând: dintr-o listă de treizeci de clienți, aceia sunt cei la care
    #: mai e ceva de făcut; restul așteaptă răspuns.
    #:
    #: Spune că textul a fost **compus și copiat**, nu că a plecat: aplicația nu
    #: trimite (Faza 2), deci nu are de unde ști dacă omul l-a și lipit în email.
    #: Interfața nu are voie să promită mai mult decât atât.
    requested_at: datetime | None
    #: Câte documente au intrat prin linkul acelei cereri.
    #:
    #: Zero, la o cerere veche, este semnalul de urmărire: clientul n-a atins
    #: drumul. Documentele venite altfel închid golul singure, iar atunci rândul
    #: dispare cu totul din raport.
    received_through_link: int


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


def _to_missing_entry(
    view: PeriodView,
    gaps: list[ChecklistEntry],
    deadline: date,
    trace: RequestTrace | None,
) -> MissingDocumentsEntryOut:
    return MissingDocumentsEntryOut(
        period=to_period(view),
        missing=[_to_item(item) for item in gaps],
        deadline=deadline,
        requested_at=trace.requested_at if trace else None,
        received_through_link=trace.received_through_link if trace else 0,
    )


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
    deadline = filing_deadline(filters.reference_month, day=settings.filing_deadline_day)
    # O singură interogare pentru tot raportul, nu una pe rând: treizeci de
    # clienți ar fi însemnat treizeci de dus-întors pentru o coloană.
    traces = UploadLinkService(session).requests_for(user.organization_id, filters.reference_month)
    return [
        _to_missing_entry(view, gaps, deadline, traces.get(view.client_id))
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
    # Aceeași funcție pe care o cheamă și aplicarea unui șablon: a doua
    # implementare ar fi divergat exact în partea tăcută — ce se întâmplă cu
    # tipurile scoase din listă.
    replace_expectations(session, user.organization_id, client_id, wanted)
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


# ── Șabloane de așteptări ────────────────────────────────────────────────────


def _to_template(view: TemplateView) -> ExpectationTemplateOut:
    return ExpectationTemplateOut(
        id=view.id,
        name=view.name,
        expectations=[
            ExpectationOut(
                document_type_code=item.document_type_code,
                document_type_label=item.document_type_label,
                expected_min_count=item.expected_min_count,
            )
            for item in view.items
        ],
    )


def _audit_template(
    session: DbSession,
    user: User,
    request: Request,
    action: str,
    template: TemplateView,
) -> None:
    AuditService(session).record(
        organization_id=user.organization_id,
        action=action,
        entity_type="ExpectationTemplate",
        entity_id=str(template.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{template.name} · {len(template.items)} tipuri",
        ip=client_ip(request),
    )


def _check_unique_name(
    service: ExpectationTemplateService,
    organization_id: uuid.UUID,
    name: str,
    keeping: uuid.UUID | None,
) -> None:
    """Refuză un nume deja folosit, cu un mesaj, nu cu 500 din bază.

    Constrângerea din bază există și ea — este ultima linie —, dar o violare de
    unicitate ajunsă la om ca eroare de server nu-i spune ce să schimbe.

    Comparația ignoră diferența de literă mare: „SRL cu TVA" și „srl cu tva" sunt
    două rânduri pe care nimeni nu le poate deosebi pe ecran.
    """
    for existing in service.list_templates(organization_id):
        if existing.name.casefold() == name.casefold() and existing.id != keeping:
            raise ValidationError(
                f"Există deja un șablon numit „{existing.name}”.",
                {"name": ["Alege alt nume."]},
            )


def _wanted_types(
    session: DbSession, organization_id: uuid.UUID, entries: list[ExpectationIn]
) -> dict[uuid.UUID, int]:
    """Codurile cerute, traduse în tipurile organizației.

    Un cod necunoscut oprește totul cu 404. Ignorat în tăcere, ar fi însemnat un
    șablon care pare salvat dar căruia îi lipsește un rând — iar lipsa s-ar fi
    văzut peste o lună, în raportul care nu cere ce trebuia.
    """
    known = _known_types(session, organization_id)
    wanted: dict[uuid.UUID, int] = {}
    for entry in entries:
        document_type = known.get(entry.document_type_code)
        if document_type is None:
            raise NotFoundError("Tip de document", entry.document_type_code)
        # Ultima valoare câștigă, ca la ruta clientului: același tip trimis de
        # două ori este o greșeală de interfață, nu un motiv de 500.
        wanted[document_type.id] = entry.expected_min_count
    return wanted


@router.get("/expectation-templates", response_model=list[ExpectationTemplateOut])
def list_expectation_templates(
    session: DbSession, user: PeriodReader
) -> list[ExpectationTemplateOut]:
    """Profilurile de client ale cabinetului.

    Citirea cere doar `documents:read`: cine vede checklistul unui client are
    voie să vadă și după ce model a fost construit.
    """
    views = ExpectationTemplateService(session).list_templates(user.organization_id)
    return [_to_template(view) for view in views]


@router.post(
    "/expectation-templates",
    response_model=ExpectationTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
def create_expectation_template(
    session: DbSession, user: PeriodManager, request: Request, payload: ExpectationTemplateIn
) -> ExpectationTemplateOut:
    """Un profil nou.

    Cere `periods:manage`, ca și așteptările unui client: a hotărî ce datorează
    lunar o categorie întreagă de clienți este cu atât mai mult o decizie
    contabilă.
    """
    service = ExpectationTemplateService(session)
    _check_unique_name(service, user.organization_id, payload.name, None)
    wanted = _wanted_types(session, user.organization_id, payload.expectations)

    template = service.create(user.organization_id, payload.name, wanted)
    _audit_template(session, user, request, "EXPECTATION_TEMPLATE_CREATED", template)
    return _to_template(template)


@router.post(
    "/expectation-templates/from-client/{client_id}",
    response_model=ExpectationTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
def template_from_client(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    client_id: uuid.UUID,
    payload: TemplateFromClientIn,
) -> ExpectationTemplateOut:
    """Salvează ce s-a configurat deja pe un client, ca profil.

    Este drumul pe care se face primul șablon: cineva potrivește un client cu
    mâna, vede că e bun, și îi dă un nume — în loc să reintroducă aceleași bife
    într-un formular gol, unde ar greși exact ce tocmai nimerise.
    """
    if ClientRepository(session).get(user.organization_id, client_id) is None:
        raise NotFoundError("Client", client_id)

    service = ExpectationTemplateService(session)
    _check_unique_name(service, user.organization_id, payload.name, None)
    wanted = {
        row.document_type_id: row.expected_min_count
        for row in session.scalars(
            select(ClientExpectation).where(
                ClientExpectation.organization_id == user.organization_id,
                ClientExpectation.client_id == client_id,
            )
        )
    }
    if not wanted:
        # Un șablon gol aplicat pe doisprezece clienți le-ar șterge așteptările
        # tuturor, iar lunile lor ar începe să pară complete.
        raise ValidationError(
            "Clientul nu are nicio așteptare configurată, deci nu are ce salva.",
            {"name": ["Configurează întâi ce se așteaptă de la client."]},
        )

    template = service.create(user.organization_id, payload.name, wanted)
    _audit_template(session, user, request, "EXPECTATION_TEMPLATE_CREATED", template)
    return _to_template(template)


@router.put("/expectation-templates/{template_id}", response_model=ExpectationTemplateOut)
def update_expectation_template(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    template_id: uuid.UUID,
    payload: ExpectationTemplateIn,
) -> ExpectationTemplateOut:
    """Schimbă profilul. **Clienții cărora li s-a aplicat rămân neatinși.**

    Șablonul nu este o legătură: ce s-a aplicat este de-acum al clientului. Dacă
    ar moșteni la distanță, o bifă scoasă azi ar reapărea pe doisprezece clienți
    fără ca cineva să le fi atins ecranul.
    """
    service = ExpectationTemplateService(session)
    _check_unique_name(service, user.organization_id, payload.name, template_id)
    wanted = _wanted_types(session, user.organization_id, payload.expectations)

    template = service.replace(user.organization_id, template_id, payload.name, wanted)
    if template is None:
        raise NotFoundError("Șablon", template_id)

    _audit_template(session, user, request, "EXPECTATION_TEMPLATE_UPDATED", template)
    return _to_template(template)


@router.delete("/expectation-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expectation_template(
    session: DbSession, user: PeriodManager, request: Request, template_id: uuid.UUID
) -> None:
    """Șterge profilul. Clienții configurați cu el rămân configurați."""
    service = ExpectationTemplateService(session)
    template = service.get(user.organization_id, template_id)
    if template is None or not service.delete(user.organization_id, template_id):
        raise NotFoundError("Șablon", template_id)

    AuditService(session).record(
        organization_id=user.organization_id,
        action="EXPECTATION_TEMPLATE_DELETED",
        entity_type="ExpectationTemplate",
        entity_id=str(template_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=template.name,
        ip=client_ip(request),
    )


class ApplyTemplateOut(ApiModel):
    """Câți clienți au primit lista. Numărul se arată, nu se presupune."""

    applied: int


@router.post("/expectation-templates/{template_id}/apply", response_model=ApplyTemplateOut)
def apply_expectation_template(
    session: DbSession,
    user: PeriodManager,
    request: Request,
    template_id: uuid.UUID,
    payload: ApplyTemplateIn,
) -> ApplyTemplateOut:
    """Scrie lista șablonului peste așteptările clienților aleși.

    **Înlocuiește, nu adaugă.** Un client căruia i se aplică „SRL neplătitor de
    TVA" rămâne cu exact acea listă; altfel, două profiluri aplicate pe rând ar
    lăsa o listă pe care n-a ales-o nimeni.

    **Un client necunoscut oprește totul**, înainte de orice scriere. Aplicată
    parțial, operația ar lăsa pe cineva cu jumătate din clienți configurați și
    fără să știe care jumătate.
    """
    service = ExpectationTemplateService(session)
    template = service.get(user.organization_id, template_id)
    if template is None:
        raise NotFoundError("Șablon", template_id)

    repository = ClientRepository(session)
    # Id-uri unice, în ordinea în care au venit: un client trimis de două ori nu
    # este o eroare, dar nici nu se numără de două ori în raportul de la sfârșit.
    client_ids = list(dict.fromkeys(payload.client_ids))
    for client_id in client_ids:
        if repository.get(user.organization_id, client_id) is None:
            raise NotFoundError("Client", client_id)

    applied = service.apply(user.organization_id, template_id, client_ids)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="EXPECTATION_TEMPLATE_APPLIED",
        entity_type="ExpectationTemplate",
        entity_id=str(template_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{template.name} · {applied} clienți",
        new_value={"clientIds": [str(row) for row in client_ids]},
        ip=client_ip(request),
    )
    return ApplyTemplateOut(applied=applied)
