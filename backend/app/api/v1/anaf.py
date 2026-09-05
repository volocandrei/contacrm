"""Conectarea SPV-ului ANAF și împuternicirile clienților (M11).

Fluxul de autorizare este același în trei pași ca la Microsoft, și tot din același
motiv — ca browserul să nu fie trimis niciodată la o rută a API-ului, care ar
trebui atunci să răspundă cu HTML în loc de JSON:

1. `POST /integrations/anaf/authorize` întoarce adresa ANAF și un `state` semnat.
2. ANAF întoarce browserul la interfață cu un `code`.
3. Interfața trimite codul la `POST /integrations/anaf/connect`.

**Diferența față de Microsoft este pasul zero:** browserul trebuie să prezinte
certificatul digital calificat înrolat în SPV. Nu se poate face de pe server, nu
se poate automatiza, și nu are rost să pretindem altceva — ecranul spune limpede
că pasul se face de la calculatorul cu tokenul USB în port.

**Împuternicirile sunt partea care chiar contează.** Certificatul singur nu
deschide nimic: pentru fiecare client, ANAF cere o împuternicire depusă în SPV.
Un rând în `anaf_mandates` este afirmația cabinetului că împuternicirea aceea
există. Dacă nu există, ANAF refuză interogarea, iar refuzul apare pe rândul
clientului, cu ce are de făcut.

Nimic din ce iese pe aici nu conține tokenul (§73): nici întreg, nici trunchiat.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Request, status
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DbSession, StorageDep, client_ip, require_permission
from app.api.route import CommittingRoute
from app.core.config import settings
from app.core.crypto import encrypt, encryption_available
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import TokenError, decode_state, encode_state
from app.domain.permissions import Permission
from app.models.anaf import AnafConnection, AnafMandate
from app.models.client import Client
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.anaf.base import AnafError
from app.services.anaf.client import authorize_url
from app.services.anaf.deps import AnafClientDep
from app.services.anaf.sync import AnafSyncService
from app.services.audit import AuditService
from app.services.client_matching import normalize_tax_id

logger = get_logger(__name__)

router = APIRouter(route_class=CommittingRoute, prefix="/integrations", tags=["admin"])

SettingsAdmin = Annotated[User, require_permission(Permission.ADMIN_SETTINGS)]

#: Cât timp este valabilă o autorizare pornită. Mai lung decât la Microsoft:
#: prezentarea certificatului cere uneori instalarea driverului tokenului.
STATE_TTL: Final = timedelta(minutes=30)


# ── Forme de răspuns ─────────────────────────────────────────────────────────


class AnafMandateOut(ApiModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    #: CUI-ul interogat, în forma normalizată pe care o cere API-ul ANAF.
    tax_id: str
    #: Până când am citit lista de mesaje. `null` = împuternicire nouă.
    synced_through: datetime | None
    last_synced_at: datetime | None
    #: Cel mai des: „clientul nu a depus împuternicirea". Se arată ca atare.
    last_error: str | None
    invoices_ingested: int
    is_active: bool


class AnafStatusOut(ApiModel):
    """Tot ce are nevoie ecranul, într-o singură cerere."""

    #: `False` când lipsesc `ANAF_CLIENT_ID`/`ANAF_CLIENT_SECRET`.
    configured: bool
    #: `False` când lipsește `DRIVE_TOKEN_KEY`. Fără ea nu stocăm tokenul.
    encryption_ready: bool
    connected: bool
    environment: str
    certificate_holder: str | None
    connected_at: datetime | None
    #: Când expiră autorizarea. ANAF o dă pe un an, iar reînnoirea cere din nou
    #: certificatul — deci se anunță din timp, nu se descoperă prin tăcere.
    expires_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    mandates: list[AnafMandateOut]


class AuthorizeOut(ApiModel):
    authorize_url: str


class ConnectIn(ApiModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=4096)
    #: Eticheta certificatului, scrisă de administrator („Certificat Ion Popescu").
    #: Se afișează ca să se știe cu al cui certificat merge preluarea; nu
    #: participă la nicio decizie și nu se compară cu nimic.
    certificate_holder: str | None = Field(default=None, max_length=255)


class AddMandateIn(ApiModel):
    client_id: uuid.UUID
    #: Implicit se ia CUI-ul clientului. Se trimite explicit doar când clientul
    #: are în CRM altceva decât CUI-ul din SPV — un sediu secundar, de pildă.
    tax_id: str | None = Field(default=None, max_length=32)


class UpdateMandateIn(ApiModel):
    is_active: bool


class AnafSyncResultOut(ApiModel):
    ingested: int
    failed: int
    #: Mai sunt facturi de adus. La prima împuternicire cu istoric, turul se
    #: oprește la lotul configurat și continuă la următorul.
    has_more: bool
    mandates: list[str]


# ── Ajutoare ─────────────────────────────────────────────────────────────────


def _connection(session: DbSession, organization_id: uuid.UUID) -> AnafConnection | None:
    return session.scalars(
        select(AnafConnection).where(
            AnafConnection.organization_id == organization_id,
            AnafConnection.is_active.is_(True),
        )
    ).first()


def _require_connection(session: DbSession, organization_id: uuid.UUID) -> AnafConnection:
    connection = _connection(session, organization_id)
    if connection is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "SPV-ul ANAF nu este conectat.",
            status_code=status.HTTP_409_CONFLICT,
        )
    return connection


def _mandates(session: DbSession, connection: AnafConnection) -> list[AnafMandateOut]:
    rows = session.execute(
        select(AnafMandate, Client.name)
        .join(Client, Client.id == AnafMandate.client_id)
        .where(AnafMandate.connection_id == connection.id)
        .order_by(Client.name)
    ).all()
    return [_one(mandate, client_name) for mandate, client_name in rows]


def _one(mandate: AnafMandate, client_name: str) -> AnafMandateOut:
    return AnafMandateOut(
        id=mandate.id,
        client_id=mandate.client_id,
        client_name=client_name,
        tax_id=mandate.tax_id,
        synced_through=mandate.synced_through,
        last_synced_at=mandate.last_synced_at,
        last_error=mandate.last_error,
        invoices_ingested=mandate.invoices_ingested,
        is_active=mandate.is_active,
    )


def _as_app_error(exc: AnafError) -> AppError:
    """Erorile ANAF ies ca mesaje, nu ca 500.

    Un certificat expirat sau o împuternicire lipsă nu sunt defecte ale
    aplicației: sunt stări pe care cabinetul le poate rezolva, dacă i se spune
    care sunt.
    """
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        str(exc),
        status_code=status.HTTP_502_BAD_GATEWAY
        if exc.retryable
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _client_of(session: DbSession, organization_id: uuid.UUID, client_id: uuid.UUID) -> Client:
    """Clientul, verificat că este al organizației care cere (§72)."""
    found = session.scalars(
        select(Client).where(Client.id == client_id, Client.organization_id == organization_id)
    ).first()
    if found is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Clientul nu există.", status_code=status.HTTP_404_NOT_FOUND
        )
    return found


def _mandate_of(
    session: DbSession, organization_id: uuid.UUID, mandate_id: uuid.UUID
) -> AnafMandate:
    found = session.scalars(
        select(AnafMandate).where(
            AnafMandate.id == mandate_id, AnafMandate.organization_id == organization_id
        )
    ).first()
    if found is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Împuternicirea nu există.", status_code=status.HTTP_404_NOT_FOUND
        )
    return found


# ── Rute ─────────────────────────────────────────────────────────────────────


@router.get("/anaf", response_model=AnafStatusOut)
def anaf_status(session: DbSession, user: SettingsAdmin) -> AnafStatusOut:
    """Starea integrării. Un singur apel, ca ecranul să nu compună din trei."""
    connection = _connection(session, user.organization_id)

    return AnafStatusOut(
        configured=bool(settings.anaf_client_id and settings.anaf_client_secret),
        encryption_ready=encryption_available(),
        connected=connection is not None,
        environment=connection.environment if connection else settings.anaf_environment,
        certificate_holder=connection.certificate_holder if connection else None,
        connected_at=connection.connected_at if connection else None,
        expires_at=connection.expires_at if connection else None,
        last_sync_at=connection.last_sync_at if connection else None,
        last_error=connection.last_error if connection else None,
        mandates=_mandates(session, connection) if connection else [],
    )


@router.post("/anaf/authorize", response_model=AuthorizeOut)
def start_authorization(user: SettingsAdmin) -> AuthorizeOut:
    if not settings.anaf_client_id or not settings.anaf_client_secret:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Integrarea ANAF nu este configurată: lipsesc ANAF_CLIENT_ID și ANAF_CLIENT_SECRET.",
            status_code=status.HTTP_409_CONFLICT,
        )
    if not encryption_available():
        # Mai bine refuzăm acum decât să primim un token pe care nu îl putem
        # păstra în siguranță și să-l scriem în clar „doar de data asta".
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Lipsește DRIVE_TOKEN_KEY: fără ea, tokenul ANAF nu poate fi stocat criptat.",
            status_code=status.HTTP_409_CONFLICT,
        )

    state = encode_state(
        {"organizationId": str(user.organization_id), "userId": str(user.id)},
        expires_in=STATE_TTL,
    )
    return AuthorizeOut(
        authorize_url=authorize_url(
            client_id=settings.anaf_client_id,
            redirect_uri=settings.anaf_redirect_uri,
            state=state,
        )
    )


@router.post("/anaf/connect", response_model=AnafStatusOut)
def connect(
    session: DbSession,
    user: SettingsAdmin,
    request: Request,
    anaf: AnafClientDep,
    payload: ConnectIn,
) -> AnafStatusOut:
    try:
        claims = decode_state(payload.state)
    except TokenError as exc:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Autorizarea a expirat sau nu este validă. Pornește din nou conectarea.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc

    # Legătura dintre cine a pornit și cine termină. Fără ea, un link pregătit de
    # altcineva ar lega certificatul lui de cabinetul nostru.
    if claims.get("organizationId") != str(user.organization_id):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Autorizarea aparține altei organizații.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    try:
        tokens = anaf.exchange_code(payload.code, settings.anaf_redirect_uri)
    except AnafError as exc:
        raise _as_app_error(exc) from exc

    now = datetime.now(UTC)
    expires_at = (
        now + timedelta(seconds=tokens.refresh_expires_in) if tokens.refresh_expires_in else None
    )
    holder = (payload.certificate_holder or "").strip()[:255] or None

    existing = _connection(session, user.organization_id)
    if existing is not None:
        # Reautorizarea păstrează împuternicirile: cabinetul nu are de ce să le
        # adauge din nou pentru că i-a expirat un token după un an.
        existing.refresh_token = encrypt(tokens.refresh_token)
        existing.environment = settings.anaf_environment
        existing.certificate_holder = holder or existing.certificate_holder
        existing.expires_at = expires_at
        existing.connected_by = user.id
        existing.connected_at = now
        existing.last_error = None
        connection = existing
    else:
        connection = AnafConnection(
            organization_id=user.organization_id,
            environment=settings.anaf_environment,
            refresh_token=encrypt(tokens.refresh_token),
            certificate_holder=holder,
            expires_at=expires_at,
            connected_by=user.id,
            connected_at=now,
        )
        session.add(connection)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="ANAF_CONNECTED",
        entity_type="AnafConnection",
        entity_id=str(connection.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=holder or settings.anaf_environment,
        ip=client_ip(request),
    )
    return anaf_status(session, user)


@router.delete("/anaf", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(session: DbSession, user: SettingsAdmin, request: Request) -> None:
    """Rupe legătura și **șterge tokenul**.

    Împuternicirile dispar odată cu ea (cascadă) — sunt afirmații despre un
    certificat care nu mai este conectat. Facturile deja intrate rămân: sunt
    probe contabile, nu o copie a ceva ce stă la ANAF (R8).
    """
    connection = _require_connection(session, user.organization_id)
    holder = connection.certificate_holder

    session.delete(connection)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="ANAF_DISCONNECTED",
        entity_type="AnafConnection",
        entity_id=str(connection.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=holder,
        ip=client_ip(request),
    )


@router.post("/anaf/mandates", response_model=AnafMandateOut, status_code=status.HTTP_201_CREATED)
def add_mandate(
    session: DbSession, user: SettingsAdmin, request: Request, payload: AddMandateIn
) -> AnafMandateOut:
    """Înregistrează împuternicirea unui client.

    Rândul nu *creează* dreptul — acela se depune în SPV, de client. Aici spunem
    doar pentru ce CUI să întrebăm. Dacă împuternicirea nu există la ANAF, prima
    sincronizare o va spune, pe rândul clientului.
    """
    connection = _require_connection(session, user.organization_id)
    client = _client_of(session, user.organization_id, payload.client_id)

    tax_id = normalize_tax_id(payload.tax_id or client.tax_id)
    if not tax_id:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"{client.name} nu are CUI. Completează-l în fișa clientului sau trimite-l aici.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    duplicate = session.scalars(
        select(AnafMandate).where(
            AnafMandate.organization_id == user.organization_id,
            (AnafMandate.tax_id == tax_id) | (AnafMandate.client_id == client.id),
        )
    ).first()
    if duplicate is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "Există deja o împuternicire pentru clientul sau CUI-ul acesta.",
            status_code=status.HTTP_409_CONFLICT,
        )

    mandate = AnafMandate(
        organization_id=user.organization_id,
        connection_id=connection.id,
        client_id=client.id,
        tax_id=tax_id,
    )
    session.add(mandate)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="ANAF_MANDATE_ADDED",
        entity_type="AnafMandate",
        entity_id=str(mandate.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{client.name} · CUI {tax_id}",
        ip=client_ip(request),
    )
    return _one(mandate, client.name)


@router.patch("/anaf/mandates/{mandate_id}", response_model=AnafMandateOut)
def update_mandate(
    session: DbSession,
    user: SettingsAdmin,
    request: Request,
    mandate_id: uuid.UUID,
    payload: UpdateMandateIn,
) -> AnafMandateOut:
    mandate = _mandate_of(session, user.organization_id, mandate_id)
    client = _client_of(session, user.organization_id, mandate.client_id)
    mandate.is_active = payload.is_active
    if payload.is_active:
        # O împuternicire reactivată pleacă fără eroarea de dinainte: altfel ar
        # arăta „lipsește împuternicirea" până la primul tur reușit.
        mandate.last_error = None
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="ANAF_MANDATE_UPDATED",
        entity_type="AnafMandate",
        entity_id=str(mandate.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"{client.name} · {'activă' if payload.is_active else 'oprită'}",
        ip=client_ip(request),
    )
    return _one(mandate, client.name)


@router.delete("/anaf/mandates/{mandate_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_mandate(
    session: DbSession, user: SettingsAdmin, request: Request, mandate_id: uuid.UUID
) -> None:
    """Șterge împuternicirea. Facturile deja preluate rămân (R8)."""
    mandate = _mandate_of(session, user.organization_id, mandate_id)
    tax_id = mandate.tax_id

    session.delete(mandate)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="ANAF_MANDATE_REMOVED",
        entity_type="AnafMandate",
        entity_id=str(mandate.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=f"CUI {tax_id}",
        ip=client_ip(request),
    )


@router.post("/anaf/sync", response_model=AnafSyncResultOut)
def sync_now(
    session: DbSession, user: SettingsAdmin, storage: StorageDep, anaf: AnafClientDep
) -> AnafSyncResultOut:
    """Un tur cerut de om. Același cod ca turul automat, altă poartă."""
    _require_connection(session, user.organization_id)
    result = AnafSyncService(session, storage, anaf).sync_organization(user.organization_id)
    return AnafSyncResultOut(
        ingested=result.ingested,
        failed=result.failed,
        has_more=result.has_more,
        mandates=[mandate.tax_id for mandate in result.mandates],
    )
