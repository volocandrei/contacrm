"""Conectarea OneDrive/SharePoint și maparea dosarelor pe clienți (M9).

Fluxul de consimțământ, în trei pași, toți inițiați din interfață:

1. `POST /integrations/onedrive/authorize` întoarce adresa Microsoft și un
   `state` semnat. Browserul se duce acolo.
2. Microsoft întoarce browserul la interfață cu un `code`.
3. Interfața trimite codul la `POST /integrations/onedrive/connect`, cu sesiunea
   ei obișnuită.

**De ce nu primim redirectul direct în API.** Microsoft ar trimite browserul la o
rută a noastră, iar aceea ar trebui să răspundă cu un redirect HTML — singurul
loc din tot backendul care nu ar vorbi JSON. Trecând prin interfață, cererea care
schimbă codul este un `fetch` obișnuit, cu cookie-ul de sesiune la locul lui.

**`state` este semnat, nu doar aleatoriu.** Fără asta, cineva ar putea trimite un
administrator pe un link de consimțământ pregătit dinainte și i-ar conecta
cabinetului **propriul** OneDrive — de unde ar citi apoi tot ce intră. Semnătura
leagă consimțământul de organizația și utilizatorul care l-au pornit.

Nimic din ce iese pe aici nu conține tokenul (§73): nici întreg, nici trunchiat.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Query, Request, status
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DbSession, StorageDep, client_ip, require_permission
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, encryption_available
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import TokenError, decode_state, encode_state
from app.domain.permissions import Permission
from app.models.client import Client
from app.models.microsoft import DriveFolder, MailFolder, MicrosoftConnection
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.microsoft import DriveError, DriveSyncService
from app.services.microsoft.deps import DriveClientDep
from app.services.microsoft.graph import authorize_url
from app.services.microsoft.mail_sync import MailSyncService

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations", tags=["admin"])

SettingsAdmin = Annotated[User, require_permission(Permission.ADMIN_SETTINGS)]

#: Cât timp este valabil un consimțământ pornit. Destul cât să te autentifici la
#: Microsoft, prea puțin cât să fie refolosit de altcineva peste o zi.
STATE_TTL: Final = timedelta(minutes=15)

PROVIDER: Final = "microsoft"


# ── Forme de răspuns ─────────────────────────────────────────────────────────


class DriveFolderOut(ApiModel):
    id: uuid.UUID
    #: Identificatorii Microsoft ies pentru că interfața trebuie să poată spune
    #: „dosarul ăsta e deja urmărit" când administratorul răsfoiește. Nu sunt
    #: secrete: fără token nu deschid nimic.
    drive_id: str
    item_id: str
    path: str
    client_id: uuid.UUID | None
    client_name: str | None
    last_synced_at: datetime | None
    last_error: str | None
    files_ingested: int
    is_active: bool


class DriveStatusOut(ApiModel):
    """Tot ce are nevoie ecranul, într-o singură cerere."""

    #: `False` când lipsesc `MS_CLIENT_ID`/`MS_CLIENT_SECRET`. Ecranul spune ce
    #: lipsește, în loc să ofere un buton care eșuează.
    configured: bool
    #: `False` când lipsește `DRIVE_TOKEN_KEY`. Fără ea nu stocăm tokenul în clar.
    encryption_ready: bool
    connected: bool
    account_email: str | None
    account_name: str | None
    connected_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    folders: list[DriveFolderOut]
    #: Dosarele de email urmărite. Lista e separată de cea de dosare pentru că
    #: sunt lucruri diferite: acolo dosarul dă clientul, aici îl dă expeditorul.
    mail_folders: list[MailFolderOut]


class MailFolderOut(ApiModel):
    id: uuid.UUID
    folder_id: str
    display_name: str
    last_synced_at: datetime | None
    last_error: str | None
    files_ingested: int
    is_active: bool


class MailBrowseItemOut(ApiModel):
    folder_id: str
    display_name: str
    total_items: int
    #: Este deja urmărit? Ca administratorul să nu îl adauge de două ori.
    is_tracked: bool


class TrackMailFolderIn(ApiModel):
    folder_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)


class UpdateMailFolderIn(ApiModel):
    is_active: bool


class BrowseItemOut(ApiModel):
    drive_id: str
    item_id: str
    name: str
    path: str
    #: Este deja urmărit? Ca administratorul să nu îl adauge de două ori.
    is_tracked: bool


class AuthorizeOut(ApiModel):
    authorize_url: str


class ConnectIn(ApiModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=4096)


class TrackFolderIn(ApiModel):
    drive_id: str = Field(min_length=1, max_length=255)
    item_id: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    client_id: uuid.UUID | None = None


class UpdateFolderIn(ApiModel):
    client_id: uuid.UUID | None = None
    is_active: bool | None = None


class SyncResultOut(ApiModel):
    ingested: int
    failed: int
    #: Mai sunt fișiere de adus. La prima conectare a unui dosar cu istoric, turul
    #: se oprește la lotul configurat și continuă la următorul.
    has_more: bool
    folders: list[str]


# ── Ajutoare ─────────────────────────────────────────────────────────────────


def _connection(session: DbSession, organization_id: uuid.UUID) -> MicrosoftConnection | None:
    return session.scalars(
        select(MicrosoftConnection).where(
            MicrosoftConnection.organization_id == organization_id,
            MicrosoftConnection.is_active.is_(True),
        )
    ).first()


def _folders(session: DbSession, connection: MicrosoftConnection) -> list[DriveFolderOut]:
    rows = session.execute(
        select(DriveFolder, Client.name)
        .outerjoin(Client, Client.id == DriveFolder.client_id)
        .where(DriveFolder.connection_id == connection.id)
        .order_by(DriveFolder.path)
    ).all()

    return [
        DriveFolderOut(
            id=folder.id,
            drive_id=folder.drive_id,
            item_id=folder.item_id,
            path=folder.path,
            client_id=folder.client_id,
            client_name=client_name,
            last_synced_at=folder.last_synced_at,
            last_error=folder.last_error,
            files_ingested=folder.files_ingested,
            is_active=folder.is_active,
        )
        for folder, client_name in rows
    ]


def _mail_folders(session: DbSession, connection: MicrosoftConnection) -> list[MailFolderOut]:
    rows = session.scalars(
        select(MailFolder)
        .where(MailFolder.connection_id == connection.id)
        .order_by(MailFolder.display_name)
    ).all()
    return [
        MailFolderOut(
            id=folder.id,
            folder_id=folder.folder_id,
            display_name=folder.display_name,
            last_synced_at=folder.last_synced_at,
            last_error=folder.last_error,
            files_ingested=folder.files_ingested,
            is_active=folder.is_active,
        )
        for folder in rows
    ]


def _require_connection(session: DbSession, organization_id: uuid.UUID) -> MicrosoftConnection:
    connection = _connection(session, organization_id)
    if connection is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Niciun cont Microsoft conectat.",
            status_code=status.HTTP_409_CONFLICT,
        )
    return connection


def _as_app_error(exc: DriveError) -> AppError:
    """Erorile providerului ies ca mesaje, nu ca 500.

    Un token expirat sau un consimțământ retras nu sunt defecte ale aplicației:
    sunt stări pe care administratorul le poate rezolva, dacă i se spune care.
    """
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        str(exc),
        status_code=status.HTTP_502_BAD_GATEWAY
        if exc.retryable
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


# ── Rute ─────────────────────────────────────────────────────────────────────


@router.get("/onedrive", response_model=DriveStatusOut)
def drive_status(session: DbSession, user: SettingsAdmin) -> DriveStatusOut:
    """Starea integrării. Un singur apel, ca ecranul să nu compună din trei."""
    connection = _connection(session, user.organization_id)

    return DriveStatusOut(
        configured=bool(settings.ms_client_id and settings.ms_client_secret),
        encryption_ready=encryption_available(),
        connected=connection is not None,
        account_email=connection.account_email if connection else None,
        account_name=connection.account_name if connection else None,
        connected_at=connection.connected_at if connection else None,
        last_sync_at=connection.last_sync_at if connection else None,
        last_error=connection.last_error if connection else None,
        folders=_folders(session, connection) if connection else [],
        mail_folders=_mail_folders(session, connection) if connection else [],
    )


@router.post("/onedrive/authorize", response_model=AuthorizeOut)
def start_authorization(user: SettingsAdmin) -> AuthorizeOut:
    if not settings.ms_client_id or not settings.ms_client_secret:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Integrarea Microsoft nu este configurată: lipsesc MS_CLIENT_ID și MS_CLIENT_SECRET.",
            status_code=status.HTTP_409_CONFLICT,
        )
    if not encryption_available():
        # Mai bine refuzăm acum decât să primim un token pe care nu îl putem păstra
        # în siguranță și să-l scriem în clar „doar de data asta".
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Lipsește DRIVE_TOKEN_KEY: fără ea, tokenul de acces nu poate fi stocat criptat.",
            status_code=status.HTTP_409_CONFLICT,
        )

    state = encode_state(
        {"organizationId": str(user.organization_id), "userId": str(user.id)},
        expires_in=STATE_TTL,
    )
    return AuthorizeOut(
        authorize_url=authorize_url(
            client_id=settings.ms_client_id,
            tenant=settings.ms_tenant_id,
            redirect_uri=settings.ms_redirect_uri,
            state=state,
        )
    )


@router.post("/onedrive/connect", response_model=DriveStatusOut)
def connect(
    session: DbSession,
    user: SettingsAdmin,
    request: Request,
    drive: DriveClientDep,
    payload: ConnectIn,
) -> DriveStatusOut:
    try:
        claims = decode_state(payload.state)
    except TokenError as exc:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Consimțământul a expirat sau nu este valid. Pornește din nou conectarea.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc

    # Legătura dintre cine a pornit și cine termină. Fără ea, un link pregătit de
    # altcineva ar conecta OneDrive-ul lui la cabinetul nostru.
    if claims.get("organizationId") != str(user.organization_id):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Consimțământul aparține altei organizații.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    try:
        tokens = drive.exchange_code(payload.code, settings.ms_redirect_uri)
        account = drive.account(tokens.refresh_token)
    except DriveError as exc:
        raise _as_app_error(exc) from exc

    existing = _connection(session, user.organization_id)
    if existing is not None:
        # Reconectarea păstrează dosarele: administratorul nu trebuie să le mapeze
        # din nou pentru că i-a expirat un token.
        existing.refresh_token = encrypt(tokens.refresh_token)
        existing.account_email = account.email[:320]
        existing.account_name = account.display_name
        existing.scopes = " ".join(tokens.scopes)
        existing.connected_by = user.id
        existing.connected_at = datetime.now(UTC)
        existing.last_error = None
        connection = existing
    else:
        connection = MicrosoftConnection(
            organization_id=user.organization_id,
            provider=PROVIDER,
            account_email=account.email[:320],
            account_name=account.display_name,
            refresh_token=encrypt(tokens.refresh_token),
            scopes=" ".join(tokens.scopes),
            connected_by=user.id,
            connected_at=datetime.now(UTC),
        )
        session.add(connection)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="DRIVE_CONNECTED",
        entity_type="MicrosoftConnection",
        entity_id=str(connection.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=account.email,
        ip=client_ip(request),
    )
    return drive_status(session, user)


@router.delete("/onedrive", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(session: DbSession, user: SettingsAdmin, request: Request) -> None:
    """Rupe legătura și **șterge tokenul**.

    Dosarele urmărite dispar odată cu ea (cascadă), dar documentele deja intrate
    rămân: sunt probe contabile, nu o copie a unui dosar din OneDrive (R8).
    """
    connection = _require_connection(session, user.organization_id)
    email = connection.account_email

    session.delete(connection)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="DRIVE_DISCONNECTED",
        entity_type="MicrosoftConnection",
        entity_id=str(connection.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=email,
        ip=client_ip(request),
    )


@router.get("/onedrive/browse", response_model=list[BrowseItemOut])
def browse(
    session: DbSession,
    user: SettingsAdmin,
    drive: DriveClientDep,
    # `alias="parentId"`: contractul este camelCase în ambele direcții, dar un
    # parametru de query **nu** trece prin `ApiModel`, deci nu primește aliasul de
    # la sine. Fără el, FastAPI caută `parent_id`, nu găsește nimic și răspunde
    # tăcut cu rădăcina — răsfoirea părea că merge, dar nu cobora niciodată.
    parent_id: Annotated[str | None, Query(alias="parentId")] = None,
) -> list[BrowseItemOut]:
    """Subdosarele unui dosar, ca administratorul să aleagă ce urmărim."""
    connection = _require_connection(session, user.organization_id)

    try:
        items = drive.list_folders(decrypt(connection.refresh_token), parent_id=parent_id)
    except DriveError as exc:
        raise _as_app_error(exc) from exc

    tracked = {
        (folder.drive_id, folder.item_id)
        for folder in session.scalars(
            select(DriveFolder).where(DriveFolder.connection_id == connection.id)
        )
    }
    return [
        BrowseItemOut(
            drive_id=item.drive_id,
            item_id=item.id,
            name=item.name,
            path=item.path,
            is_tracked=(item.drive_id, item.id) in tracked,
        )
        for item in items
    ]


@router.post(
    "/onedrive/folders", response_model=DriveFolderOut, status_code=status.HTTP_201_CREATED
)
def track_folder(
    session: DbSession, user: SettingsAdmin, request: Request, payload: TrackFolderIn
) -> DriveFolderOut:
    connection = _require_connection(session, user.organization_id)

    duplicate = session.scalars(
        select(DriveFolder).where(
            DriveFolder.organization_id == user.organization_id,
            DriveFolder.drive_id == payload.drive_id,
            DriveFolder.item_id == payload.item_id,
        )
    ).first()
    if duplicate is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "Dosarul este deja urmărit.",
            status_code=status.HTTP_409_CONFLICT,
        )

    if payload.client_id is not None:
        _assert_client_exists(session, user.organization_id, payload.client_id)

    folder = DriveFolder(
        organization_id=user.organization_id,
        connection_id=connection.id,
        client_id=payload.client_id,
        drive_id=payload.drive_id,
        item_id=payload.item_id,
        path=payload.path[:1024],
    )
    session.add(folder)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="DRIVE_FOLDER_TRACKED",
        entity_type="DriveFolder",
        entity_id=str(folder.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=folder.path,
        ip=client_ip(request),
    )
    return _one(session, folder)


@router.patch("/onedrive/folders/{folder_id}", response_model=DriveFolderOut)
def update_folder(
    session: DbSession,
    user: SettingsAdmin,
    request: Request,
    folder_id: uuid.UUID,
    payload: UpdateFolderIn,
) -> DriveFolderOut:
    folder = _folder(session, user.organization_id, folder_id)

    if payload.client_id is not None:
        _assert_client_exists(session, user.organization_id, payload.client_id)
    # `client_id` se poate și șterge, deci nu se poate distinge „nu am trimis" de
    # „am trimis null" doar din valoare: câmpul se aplică oricum, iar `null`
    # înseamnă „dezleagă".
    folder.client_id = payload.client_id
    if payload.is_active is not None:
        folder.is_active = payload.is_active

    AuditService(session).record(
        organization_id=user.organization_id,
        action="DRIVE_FOLDER_UPDATED",
        entity_type="DriveFolder",
        entity_id=str(folder.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=folder.path,
        ip=client_ip(request),
    )
    return _one(session, folder)


@router.delete("/onedrive/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def untrack_folder(
    session: DbSession, user: SettingsAdmin, request: Request, folder_id: uuid.UUID
) -> None:
    folder = _folder(session, user.organization_id, folder_id)
    path = folder.path

    session.delete(folder)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="DRIVE_FOLDER_UNTRACKED",
        entity_type="DriveFolder",
        entity_id=str(folder_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=path,
        ip=client_ip(request),
    )


@router.post("/onedrive/sync", response_model=SyncResultOut)
def sync_now(
    session: DbSession, user: SettingsAdmin, storage: StorageDep, drive: DriveClientDep
) -> SyncResultOut:
    """Un tur cerut de om. Automatul rulează oricum, prin `/internal/run-queue`."""
    _require_connection(session, user.organization_id)

    drive_result = DriveSyncService(session, storage, drive).sync_organization(user.organization_id)
    mail_result = MailSyncService(session, storage, drive).sync_organization(user.organization_id)
    return SyncResultOut(
        ingested=drive_result.ingested + mail_result.ingested,
        failed=drive_result.failed + mail_result.failed,
        has_more=drive_result.has_more or mail_result.has_more,
        folders=[folder.path for folder in drive_result.folders]
        + [folder.display_name for folder in mail_result.folders],
    )


@router.get("/onedrive/mail-folders", response_model=list[MailBrowseItemOut])
def browse_mail(
    session: DbSession, user: SettingsAdmin, drive: DriveClientDep
) -> list[MailBrowseItemOut]:
    """Dosarele din cutia poștală, ca administratorul să aleagă ce citim.

    Cele mai multe cabinete au o regulă care mută mesajele clienților într-un
    dosar anume; acela este cel de urmărit, nu Inbox-ul întreg.
    """
    connection = _require_connection(session, user.organization_id)

    try:
        folders = drive.list_mail_folders(decrypt(connection.refresh_token))
    except DriveError as exc:
        raise _as_app_error(exc) from exc

    tracked = {
        row.folder_id
        for row in session.scalars(
            select(MailFolder).where(MailFolder.connection_id == connection.id)
        )
    }
    return [
        MailBrowseItemOut(
            folder_id=folder.id,
            display_name=folder.display_name,
            total_items=folder.total_items,
            is_tracked=folder.id in tracked,
        )
        for folder in folders
    ]


@router.post(
    "/onedrive/mail-folders", response_model=MailFolderOut, status_code=status.HTTP_201_CREATED
)
def track_mail_folder(
    session: DbSession, user: SettingsAdmin, request: Request, payload: TrackMailFolderIn
) -> MailFolderOut:
    connection = _require_connection(session, user.organization_id)

    duplicate = session.scalars(
        select(MailFolder).where(
            MailFolder.organization_id == user.organization_id,
            MailFolder.folder_id == payload.folder_id,
        )
    ).first()
    if duplicate is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            "Dosarul de email este deja urmărit.",
            status_code=status.HTTP_409_CONFLICT,
        )

    folder = MailFolder(
        organization_id=user.organization_id,
        connection_id=connection.id,
        folder_id=payload.folder_id,
        display_name=payload.display_name[:255],
    )
    session.add(folder)
    session.flush()

    AuditService(session).record(
        organization_id=user.organization_id,
        action="MAIL_FOLDER_TRACKED",
        entity_type="MailFolder",
        entity_id=str(folder.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=folder.display_name,
        ip=client_ip(request),
    )
    return _one_mail(folder)


@router.patch("/onedrive/mail-folders/{folder_id}", response_model=MailFolderOut)
def update_mail_folder(
    session: DbSession,
    user: SettingsAdmin,
    request: Request,
    folder_id: uuid.UUID,
    payload: UpdateMailFolderIn,
) -> MailFolderOut:
    folder = _mail_folder(session, user.organization_id, folder_id)
    folder.is_active = payload.is_active

    AuditService(session).record(
        organization_id=user.organization_id,
        action="MAIL_FOLDER_UPDATED",
        entity_type="MailFolder",
        entity_id=str(folder.id),
        user_id=user.id,
        user_name=user.full_name,
        detail=folder.display_name,
        ip=client_ip(request),
    )
    return _one_mail(folder)


@router.delete("/onedrive/mail-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def untrack_mail_folder(
    session: DbSession, user: SettingsAdmin, request: Request, folder_id: uuid.UUID
) -> None:
    folder = _mail_folder(session, user.organization_id, folder_id)
    name = folder.display_name

    session.delete(folder)
    AuditService(session).record(
        organization_id=user.organization_id,
        action="MAIL_FOLDER_UNTRACKED",
        entity_type="MailFolder",
        entity_id=str(folder_id),
        user_id=user.id,
        user_name=user.full_name,
        detail=name,
        ip=client_ip(request),
    )


# ── Ajutoare de acces ────────────────────────────────────────────────────────


def _folder(session: DbSession, organization_id: uuid.UUID, folder_id: uuid.UUID) -> DriveFolder:
    folder = session.scalars(
        select(DriveFolder).where(
            DriveFolder.id == folder_id,
            # Granița organizației, în interogare, nu după (R10, §72).
            DriveFolder.organization_id == organization_id,
        )
    ).first()
    if folder is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Dosarul nu există.", status_code=status.HTTP_404_NOT_FOUND
        )
    return folder


def _assert_client_exists(
    session: DbSession, organization_id: uuid.UUID, client_id: uuid.UUID
) -> None:
    exists = session.scalars(
        select(Client.id).where(
            Client.id == client_id,
            Client.organization_id == organization_id,
            Client.deleted_at.is_(None),
        )
    ).first()
    if exists is None:
        raise AppError(
            ErrorCode.NOT_FOUND, "Clientul nu există.", status_code=status.HTTP_404_NOT_FOUND
        )


def _one(session: DbSession, folder: DriveFolder) -> DriveFolderOut:
    client_name = (
        session.scalars(select(Client.name).where(Client.id == folder.client_id)).first()
        if folder.client_id
        else None
    )
    return DriveFolderOut(
        id=folder.id,
        drive_id=folder.drive_id,
        item_id=folder.item_id,
        path=folder.path,
        client_id=folder.client_id,
        client_name=client_name,
        last_synced_at=folder.last_synced_at,
        last_error=folder.last_error,
        files_ingested=folder.files_ingested,
        is_active=folder.is_active,
    )


def _mail_folder(
    session: DbSession, organization_id: uuid.UUID, folder_id: uuid.UUID
) -> MailFolder:
    folder = session.scalars(
        select(MailFolder).where(
            MailFolder.id == folder_id,
            # Granița organizației, în interogare, nu după (R10, §72).
            MailFolder.organization_id == organization_id,
        )
    ).first()
    if folder is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Dosarul de email nu există.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return folder


def _one_mail(folder: MailFolder) -> MailFolderOut:
    return MailFolderOut(
        id=folder.id,
        folder_id=folder.folder_id,
        display_name=folder.display_name,
        last_synced_at=folder.last_synced_at,
        last_error=folder.last_error,
        files_ingested=folder.files_ingested,
        is_active=folder.is_active,
    )


__all__ = ["router"]
