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
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt
from app.core.logging import get_logger
from app.models.microsoft import MailFolder, MicrosoftConnection
from app.services.mail_intake import (
    MAX_ERROR,
    MIN_ATTACHMENT_BYTES,
    Attachment,
    IngestKind,
    MailFetchError,
    MailIntakeService,
    is_document,
)
from app.services.microsoft.base import (
    DriveAuthError,
    DriveClient,
    DriveError,
    MailAttachment,
    MailMessage,
)
from app.services.storage import StorageProvider

logger = get_logger(__name__)

# `MAX_ERROR` și `MIN_ATTACHMENT_BYTES` vin din `mail_intake`: sunt reguli
# comune tuturor cutiilor poștale, nu ale lui Graph. Reexportate mai jos, ca
# importurile existente să nu se rupă.


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
        self.intake = MailIntakeService(session, storage)

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
        senders = self.intake.sender_map(organization_id)

        for folder in folders:
            result.folders.append(self._sync_folder(connection, folder, refresh_token, senders))

        connection.last_sync_at = datetime.now(UTC)
        return result

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
        client_id = self.intake.client_for(senders, message.sender)

        for attachment in message.attachments:
            if not is_document(
                Attachment(
                    id=attachment.id,
                    name=attachment.name,
                    size=attachment.size,
                    is_inline=attachment.is_inline,
                )
            ):
                outcome.skipped += 1
                continue
            self._take_attachment(
                connection, folder, message, attachment, client_id, refresh_token, outcome
            )

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
        """Aduce un atașament. Regulile sunt ale tuturor cutiilor, nu ale lui Graph.

        Aici rămâne doar ce ține de Graph: cum se descarcă fișierul și ce se
        numără pe dosar. Restul — pragul de mărime, cheia de idempotență, ce se
        întâmplă cu un fișier refuzat — stă în `mail_intake`, ca o cutie IMAP să
        decidă identic.
        """

        def open_stream() -> BinaryIO:
            try:
                return self.client.download_attachment(
                    refresh_token, message_id=message.id, attachment_id=attachment.id
                )
            except DriveError as exc:
                raise MailFetchError(str(exc)) from exc

        result = self.intake.ingest(
            organization_id=folder.organization_id,
            message_id=message.id,
            attachment=Attachment(
                id=attachment.id,
                name=attachment.name,
                size=attachment.size,
                is_inline=attachment.is_inline,
            ),
            sender=message.sender,
            recipient=connection.account_email,
            subject=message.subject,
            received_at=message.received_at,
            client_id=client_id,
            raw_payload={"folder": folder.display_name, "size": attachment.size},
            open_stream=open_stream,
            actor_name="Sistem · Email",
        )

        if result.kind is IngestKind.FAILED:
            outcome.failed += 1
        elif result.kind is IngestKind.SKIPPED:
            outcome.skipped += 1
        else:
            folder.files_ingested += 1
            outcome.ingested += 1


__all__ = ["MIN_ATTACHMENT_BYTES", "MailFolderResult", "MailSyncResult", "MailSyncService"]
