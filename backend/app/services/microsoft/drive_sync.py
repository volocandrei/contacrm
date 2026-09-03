"""Aducerea documentelor din dosarele urmărite.

Asta este funcția pe care a cerut-o cabinetul: *„să îmi preia automat ce
documente trimit clienții, să nu mai stau eu să le descarc și să le numesc
manual"*. Amândouă jumătățile se rezolvă aici — descărcarea, prin turul de mai
jos; numele, pentru că documentul intră în fluxul obișnuit și iese din el arhivat
sub numele standardizat din §10.

**Dosarul dă clientul.** Contabilul are deja un dosar per client, iar maparea
aceea este mai sigură decât orice citire de CUI: un fișier apărut în dosarul lui
Alfa Conta SRL aparține lui Alfa Conta SRL, chiar dacă e o poză neclară fără text.
Extracția rămâne să spună *ce* este documentul; *al cui* este se știe deja.

**Un dosar nemapat nu ghicește.** Fișierele intră, dar rămân fără client și
așteaptă un om — exact ca înainte. Un dosar fără client atribuit nu este o
scuză pentru a inventa unul.

Trei proprietăți pe care se sprijină restul:

- **Idempotență.** Fiecare fișier lasă un `DocumentIntake` cu id-ul lui din
  Graph. Același fișier văzut de două ori — pentru că tokenul delta s-a pierdut,
  pentru că cineva a mutat dosarul — nu produce un al doilea document.
- **Un fișier eșuat nu oprește turul.** Un PDF corupt, un tip neacceptat, o
  descărcare picată: se notează și se trece mai departe. Restul dosarului nu are
  de suferit din cauza unui fișier.
- **Tokenul delta se salvează doar după ce fișierele au intrat.** Salvat înainte,
  o cădere la mijloc ar face ca fișierele nepreluate să nu mai fie văzute
  niciodată — cea mai urâtă formă de pierdere, pentru că e tăcută.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt
from app.core.logging import get_logger
from app.domain.enums import DocumentSource, IntakeStatus
from app.models.document import DocumentIntake
from app.models.microsoft import DriveFolder, MicrosoftConnection
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.microsoft.base import DriveAuthError, DriveClient, DriveError, DriveItem
from app.services.processing_queue import enqueue as enqueue_processing
from app.services.storage import StorageProvider

logger = get_logger(__name__)

#: Cât de lungă poate fi o eroare păstrată pe rând. Coloana are 512.
MAX_ERROR = 500


@dataclass(slots=True)
class FolderResult:
    """Ce s-a întâmplat cu un dosar într-un tur."""

    folder_id: uuid.UUID
    path: str
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    error: str | None = None
    #: Mai are pagini de citit. Turul următor continuă de unde a rămas.
    has_more: bool = False


@dataclass(slots=True)
class SyncResult:
    """Rezultatul unui tur complet."""

    folders: list[FolderResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(folder.ingested for folder in self.folders)

    @property
    def failed(self) -> int:
        return sum(folder.failed for folder in self.folders)

    @property
    def has_more(self) -> bool:
        return any(folder.has_more for folder in self.folders)


class DriveSyncService:
    """Un tur peste dosarele urmărite ale unei organizații."""

    def __init__(
        self,
        session: Session,
        storage: StorageProvider,
        client: DriveClient,
    ) -> None:
        self.session = session
        self.storage = storage
        self.client = client
        self.uploads = DocumentUploadService(session, storage)
        self.audit = AuditService(session)

    # ── Turul ───────────────────────────────────────────────────────────────

    def sync_organization(self, organization_id: uuid.UUID) -> SyncResult:
        """Sincronizează toate dosarele active. Nu aruncă: raportează."""
        result = SyncResult()

        connection = self.session.scalars(
            select(MicrosoftConnection).where(
                MicrosoftConnection.organization_id == organization_id,
                MicrosoftConnection.is_active.is_(True),
            )
        ).first()
        if connection is None:
            return result

        try:
            refresh_token = decrypt(connection.refresh_token)
        except TokenDecryptionError as exc:
            # Cheia s-a schimbat. Nu este o eroare de dosar, ci de instalare: se
            # notează pe conexiune, unde ecranul o arată o singură dată.
            connection.last_error = str(exc)[:MAX_ERROR]
            return result

        folders = self.session.scalars(
            select(DriveFolder).where(
                DriveFolder.connection_id == connection.id,
                DriveFolder.is_active.is_(True),
            )
        ).all()

        for folder in folders:
            result.folders.append(self._sync_folder(connection, folder, refresh_token))

        connection.last_sync_at = datetime.now(UTC)
        # Eroarea de autentificare este singura care aparține conexiunii, nu
        # dosarului: dacă apare, toate dosarele au aceeași problemă.
        connection.last_error = next(
            (f.error for f in result.folders if f.error and "reconect" in f.error.lower()), None
        )
        return result

    def _sync_folder(
        self, connection: MicrosoftConnection, folder: DriveFolder, refresh_token: str
    ) -> FolderResult:
        outcome = FolderResult(folder_id=folder.id, path=folder.path)

        try:
            page = self.client.delta(
                refresh_token,
                drive_id=folder.drive_id,
                item_id=folder.item_id,
                token=folder.delta_token,
                limit=settings.drive_sync_batch,
            )
        except DriveAuthError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            folder.last_error = outcome.error
            return outcome
        except DriveError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            folder.last_error = outcome.error
            logger.warning("drive_delta_failed", folder=folder.path, error=str(exc))
            return outcome

        for item in page.items:
            self._take(connection, folder, item, refresh_token, outcome)

        # Abia acum: un fișier nepreluat trebuie să reapară în turul următor.
        folder.delta_token = page.delta_token
        folder.last_synced_at = datetime.now(UTC)
        folder.last_error = None
        outcome.has_more = page.has_more
        return outcome

    # ── Un fișier ───────────────────────────────────────────────────────────

    def _take(
        self,
        connection: MicrosoftConnection,
        folder: DriveFolder,
        item: DriveItem,
        refresh_token: str,
        outcome: FolderResult,
    ) -> None:
        """Aduce un fișier. Orice eșec este al fișierului, nu al dosarului."""
        if item.is_folder or item.deleted or not item.id:
            outcome.skipped += 1
            return

        if self._already_taken(folder.organization_id, folder.item_id, item.id):
            outcome.skipped += 1
            return

        intake = DocumentIntake(
            organization_id=folder.organization_id,
            source=DocumentSource.ONEDRIVE,
            status=IntakeStatus.RECEIVED,
            # Perechea pe care se sprijină idempotența: dosarul și fișierul.
            external_message_id=folder.item_id[:255],
            external_attachment_id=item.id[:255],
            sender=connection.account_email[:320],
            subject=folder.path[:512],
            original_filename=item.name[:512],
            received_at=item.modified_at or datetime.now(UTC),
            raw_payload={"drivePath": item.path, "size": item.size},
        )
        self.session.add(intake)
        self.session.flush()

        try:
            stream = self.client.download(refresh_token, drive_id=folder.drive_id, item_id=item.id)
        except DriveError as exc:
            self._reject(intake, f"Descărcare eșuată: {exc}")
            outcome.failed += 1
            return

        try:
            upload = self.uploads.upload(
                organization_id=folder.organization_id,
                stream=stream,
                original_filename=item.name or "document",
                source=DocumentSource.ONEDRIVE,
                # Dosarul spune al cui este documentul. Când nu e mapat, rămâne
                # fără client și așteaptă un om.
                client_id=folder.client_id,
                intake=intake,
                received_at=item.modified_at,
            )
        except FileValidationError as exc:
            # Un `.docx` sau o notă text în dosarul clientului nu este o eroare a
            # sistemului: nu este un document contabil, și atât.
            self._reject(intake, exc.message)
            outcome.skipped += 1
            return

        intake.status = IntakeStatus.DUPLICATE if upload.is_duplicate else IntakeStatus.ACCEPTED
        intake.document_id = upload.document.id
        folder.files_ingested += 1
        outcome.ingested += 1

        self.audit.record(
            organization_id=folder.organization_id,
            action="DOCUMENT_INGESTED_FROM_DRIVE",
            entity_type="Document",
            entity_id=str(upload.document.id),
            # Fără utilizator: nu a apăsat nimeni nimic. Auditul trebuie să poată
            # spune și „sistemul a făcut asta", altfel ar părea că cineva a stat
            # noaptea să încarce fișiere.
            user_id=None,
            user_name="Sistem · OneDrive",
            detail=f"{folder.path} · {item.name}",
        )

        if not upload.is_duplicate:
            enqueue_processing(self.session, upload.document)

    def _already_taken(self, organization_id: uuid.UUID, folder_item: str, item_id: str) -> bool:
        """A mai intrat fișierul ăsta?

        Se întreabă înainte de descărcare, nu după: un fișier deja preluat nu are
        de ce să mai treacă prin rețea.
        """
        existing = self.session.scalars(
            select(DocumentIntake.id).where(
                DocumentIntake.organization_id == organization_id,
                DocumentIntake.source == DocumentSource.ONEDRIVE,
                DocumentIntake.external_message_id == folder_item[:255],
                DocumentIntake.external_attachment_id == item_id[:255],
            )
        ).first()
        return existing is not None

    def _reject(self, intake: DocumentIntake, reason: str) -> None:
        intake.status = IntakeStatus.REJECTED
        intake.rejection_reason = reason[:255]
        logger.info("drive_item_rejected", filename=intake.original_filename, reason=reason)


__all__ = ["DriveSyncService", "FolderResult", "SyncResult"]
