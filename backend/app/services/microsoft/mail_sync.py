"""Atașamentele din email devin documente (M10).

Este cealaltă jumătate a lui *„ce documente trimit domnii clienți"*: unii le pun
în dosarul lor din OneDrive, ceilalți le trimit pe email. Amândouă drumurile duc
acum în același loc.

**Cine dă clientul, aici, este expeditorul.** La drive, dosarul îl spune —
contabilul l-a mapat o dată. Într-o cutie poștală intră toți clienții deodată,
deci maparea trebuie făcută pe mesaj: adresa expeditorului se caută printre
contactele clienților (`contacts.email`), care există în CRM de la M4. Un client
care scrie de la adresa lui obișnuită este recunoscut fără să facă nimeni nimic.

**Ce nu se presupune.** O adresă necunoscută nu oprește nimic: atașamentul intră
și rămâne neatribuit, ca orice document fără client. Mai bine să ajungă la un om
decât să nu intre deloc — atunci nimeni nu ar ști că a venit.

**Ce nu este un document.** Logo-ul din semnătura expeditorului este tot un
atașament, la fel ca imaginea de fundal a unui newsletter. Se sar cele marcate
`inline` și cele sub un prag de dimensiune: altfel fiecare email ar produce trei
„documente" pe care cineva ar trebui să le respingă manual.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt
from app.core.logging import get_logger
from app.domain.enums import DocumentSource, IntakeStatus
from app.models.client import Client, Contact
from app.models.document import DocumentIntake
from app.models.microsoft import MailFolder, MicrosoftConnection
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.microsoft.base import (
    DriveAuthError,
    DriveClient,
    DriveError,
    MailAttachment,
    MailMessage,
)
from app.services.processing_queue import enqueue as enqueue_processing
from app.services.storage import StorageProvider

logger = get_logger(__name__)

MAX_ERROR = 500

#: Sub atâția octeți, un atașament este aproape sigur un logo de semnătură. Cea
#: mai mică factură PDF reală trece binișor de pragul ăsta.
MIN_ATTACHMENT_BYTES = 8 * 1024


@dataclass(slots=True)
class MailFolderResult:
    folder_id: uuid.UUID
    display_name: str
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    error: str | None = None
    has_more: bool = False


@dataclass(slots=True)
class MailSyncResult:
    folders: list[MailFolderResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(folder.ingested for folder in self.folders)

    @property
    def failed(self) -> int:
        return sum(folder.failed for folder in self.folders)

    @property
    def has_more(self) -> bool:
        return any(folder.has_more for folder in self.folders)


class MailSyncService:
    """Un tur peste dosarele de email urmărite ale unei organizații."""

    def __init__(self, session: Session, storage: StorageProvider, client: DriveClient) -> None:
        self.session = session
        self.storage = storage
        self.client = client
        self.uploads = DocumentUploadService(session, storage)
        self.audit = AuditService(session)

    # ── Turul ───────────────────────────────────────────────────────────────

    def sync_organization(self, organization_id: uuid.UUID) -> MailSyncResult:
        result = MailSyncResult()

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
            connection.last_error = str(exc)[:MAX_ERROR]
            return result

        folders = self.session.scalars(
            select(MailFolder).where(
                MailFolder.connection_id == connection.id,
                MailFolder.is_active.is_(True),
            )
        ).all()

        # Harta expeditor → client se citește **o dată** pe tur, nu per mesaj: un
        # dosar cu o sută de mesaje ar fi însemnat o sută de interogări identice.
        senders = self._sender_map(organization_id)

        for folder in folders:
            result.folders.append(self._sync_folder(connection, folder, refresh_token, senders))

        connection.last_sync_at = datetime.now(UTC)
        return result

    def _sender_map(self, organization_id: uuid.UUID) -> dict[str, uuid.UUID]:
        """Adresele de contact ale clienților, normalizate.

        Aceeași adresă la doi clienți este o ambiguitate reală — un contabil care
        e contact la două firme, de exemplu. Acolo nu ghicim: adresa se scoate din
        hartă și mesajul rămâne neatribuit, ca un om să decidă.
        """
        rows = self.session.execute(
            select(func.lower(Contact.email), Contact.client_id)
            .join(Client, Client.id == Contact.client_id)
            .where(
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
                Contact.email.is_not(None),
                Contact.is_active.is_(True),
                # Un contact șters nu mai identifică pe nimeni.
                Contact.deleted_at.is_(None),
            )
        ).all()

        mapping: dict[str, uuid.UUID] = {}
        ambiguous: set[str] = set()
        for email, client_id in rows:
            if email is None:
                continue
            existing = mapping.get(email)
            if existing is not None and existing != client_id:
                ambiguous.add(email)
            mapping[email] = client_id

        for email in ambiguous:
            mapping.pop(email, None)
            logger.info("mail_sender_ambiguous", sender=email)
        return mapping

    def _sync_folder(
        self,
        connection: MicrosoftConnection,
        folder: MailFolder,
        refresh_token: str,
        senders: dict[str, uuid.UUID],
    ) -> MailFolderResult:
        outcome = MailFolderResult(folder_id=folder.id, display_name=folder.display_name)

        try:
            page = self.client.mail_delta(
                refresh_token,
                folder_id=folder.folder_id,
                token=folder.delta_token,
                limit=settings.mail_sync_batch,
            )
        except DriveAuthError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            folder.last_error = outcome.error
            return outcome
        except DriveError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            folder.last_error = outcome.error
            logger.warning("mail_delta_failed", folder=folder.display_name, error=str(exc))
            return outcome

        for message in page.messages:
            self._take_message(connection, folder, message, refresh_token, senders, outcome)

        # Abia acum: un atașament nepreluat trebuie să reapară în turul următor.
        folder.delta_token = page.delta_token
        folder.last_synced_at = datetime.now(UTC)
        folder.last_error = None
        outcome.has_more = page.has_more
        return outcome

    # ── Un mesaj ────────────────────────────────────────────────────────────

    def _take_message(
        self,
        connection: MicrosoftConnection,
        folder: MailFolder,
        message: MailMessage,
        refresh_token: str,
        senders: dict[str, uuid.UUID],
        outcome: MailFolderResult,
    ) -> None:
        if message.deleted or not message.attachments:
            outcome.skipped += 1
            return

        # Normalizarea se face **aici**, nu în client: dacă providerul întoarce
        # adresa cu majuscule — sau dacă mâine se schimbă clientul — regula
        # rămâne aceeași. Un client nu are voie să fie singurul loc în care se
        # respectă o regulă de potrivire.
        client_id = senders.get(message.sender.strip().lower())

        for attachment in message.attachments:
            if not self._is_document(attachment):
                outcome.skipped += 1
                continue
            self._take_attachment(
                connection, folder, message, attachment, client_id, refresh_token, outcome
            )

    @staticmethod
    def _is_document(attachment: MailAttachment) -> bool:
        """Un logo de semnătură nu este un document contabil."""
        if attachment.is_inline or not attachment.id:
            return False
        return attachment.size >= MIN_ATTACHMENT_BYTES

    def _take_attachment(
        self,
        connection: MicrosoftConnection,
        folder: MailFolder,
        message: MailMessage,
        attachment: MailAttachment,
        client_id: uuid.UUID | None,
        refresh_token: str,
        outcome: MailFolderResult,
    ) -> None:
        if self._already_taken(folder.organization_id, message.id, attachment.id):
            outcome.skipped += 1
            return

        intake = DocumentIntake(
            organization_id=folder.organization_id,
            source=DocumentSource.EMAIL,
            status=IntakeStatus.RECEIVED,
            # Perechea pe care se sprijină idempotența: mesajul și atașamentul.
            external_message_id=message.id[:255],
            external_attachment_id=attachment.id[:255],
            sender=message.sender[:320],
            recipient=connection.account_email[:320],
            subject=message.subject[:512],
            original_filename=attachment.name[:512],
            received_at=message.received_at or datetime.now(UTC),
            raw_payload={"folder": folder.display_name, "size": attachment.size},
        )
        self.session.add(intake)
        self.session.flush()

        try:
            stream = self.client.download_attachment(
                refresh_token, message_id=message.id, attachment_id=attachment.id
            )
        except DriveError as exc:
            self._reject(intake, f"Descărcare eșuată: {exc}")
            outcome.failed += 1
            return

        try:
            upload = self.uploads.upload(
                organization_id=folder.organization_id,
                stream=stream,
                original_filename=attachment.name or "atasament",
                source=DocumentSource.EMAIL,
                # Expeditorul dă clientul. Necunoscut înseamnă neatribuit, nu ghicit.
                client_id=client_id,
                intake=intake,
                received_at=message.received_at,
            )
        except FileValidationError as exc:
            # Un `.docx` sau o semnătură scăpată de filtru: nu este un document
            # contabil, și atât. Nu este o eroare a sistemului.
            self._reject(intake, exc.message)
            outcome.skipped += 1
            return

        intake.status = IntakeStatus.DUPLICATE if upload.is_duplicate else IntakeStatus.ACCEPTED
        intake.document_id = upload.document.id
        folder.files_ingested += 1
        outcome.ingested += 1

        self.audit.record(
            organization_id=folder.organization_id,
            action="DOCUMENT_INGESTED_FROM_EMAIL",
            entity_type="Document",
            entity_id=str(upload.document.id),
            user_id=None,
            user_name="Sistem · Email",
            detail=f"{message.sender} · {attachment.name}",
        )

        if not upload.is_duplicate:
            enqueue_processing(self.session, upload.document)

    def _already_taken(self, organization_id: uuid.UUID, message_id: str, item_id: str) -> bool:
        existing = self.session.scalars(
            select(DocumentIntake.id).where(
                DocumentIntake.organization_id == organization_id,
                DocumentIntake.source == DocumentSource.EMAIL,
                DocumentIntake.external_message_id == message_id[:255],
                DocumentIntake.external_attachment_id == item_id[:255],
            )
        ).first()
        return existing is not None

    def _reject(self, intake: DocumentIntake, reason: str) -> None:
        intake.status = IntakeStatus.REJECTED
        intake.rejection_reason = reason[:255]
        logger.info("mail_attachment_rejected", filename=intake.original_filename, reason=reason)


__all__ = ["MIN_ATTACHMENT_BYTES", "MailFolderResult", "MailSyncResult", "MailSyncService"]
