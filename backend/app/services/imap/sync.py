"""Un tur peste cutiile IMAP ale unui cabinet.

Aceleași reguli ca la cutia Microsoft, fiindcă sunt **aceleași reguli**: ce este
document și ce este logo de semnătură, cum se află clientul din adresa
expeditorului, ce se întâmplă cu un atașament preluat deja. Toate stau în
`app/services/mail_intake.py` și se cheamă de aici; ce rămâne în fișierul acesta
ține strict de IMAP — de unde se citește și de unde se reia.

**Ce ține minte între tururi.** UID-ul ultimului mesaj citit, plus `UIDVALIDITY`
al dosarului. Al doilea este cel care salvează preluarea când serverul reatribuie
numerele: fără el, un dosar restaurat din backup ar fi părut că nu mai are mesaje
noi la nesfârșit.

*NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE.*
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt
from app.core.logging import get_logger
from app.models.imap import ImapMailbox
from app.services.imap.base import (
    ImapAttachment,
    ImapClient,
    ImapCredentials,
    ImapError,
    ImapMessage,
)
from app.services.mail_intake import (
    MAX_ERROR,
    Attachment,
    IngestKind,
    MailIntakeService,
    is_document,
)
from app.services.storage import StorageProvider

logger = get_logger(__name__)


@dataclass(slots=True)
class ImapMailboxResult:
    """Ce a produs o cutie într-un tur."""

    mailbox_id: uuid.UUID
    username: str
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    error: str | None = None
    has_more: bool = False


@dataclass(slots=True)
class ImapSyncResult:
    mailboxes: list[ImapMailboxResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(item.ingested for item in self.mailboxes)


class ImapSyncService:
    def __init__(self, session: Session, storage: StorageProvider, client: ImapClient) -> None:
        self.session = session
        self.client = client
        self.intake = MailIntakeService(session, storage)

    def sync_organization(self, organization_id: uuid.UUID) -> ImapSyncResult:
        result = ImapSyncResult()
        mailboxes = self.session.scalars(
            select(ImapMailbox).where(
                ImapMailbox.organization_id == organization_id,
                ImapMailbox.is_active.is_(True),
            )
        ).all()
        if not mailboxes:
            return result

        # Harta expeditor → client se citește **o dată** pe tur, nu per mesaj: o
        # cutie cu o sută de mesaje ar fi însemnat o sută de interogări identice.
        senders = self.intake.sender_map(organization_id)
        for mailbox in mailboxes:
            result.mailboxes.append(self.sync_mailbox(mailbox, senders))
        return result

    def sync_mailbox(
        self, mailbox: ImapMailbox, senders: dict[str, uuid.UUID] | None = None
    ) -> ImapMailboxResult:
        outcome = ImapMailboxResult(mailbox_id=mailbox.id, username=mailbox.username)
        if senders is None:
            senders = self.intake.sender_map(mailbox.organization_id)

        try:
            credentials = self._credentials(mailbox)
        except TokenDecryptionError as exc:
            outcome.error = str(exc)[:MAX_ERROR]
            mailbox.last_error = outcome.error[:255]
            return outcome

        try:
            page = self.client.fetch(
                credentials,
                folder=mailbox.folder,
                since_uid=mailbox.last_uid,
                limit=settings.imap_sync_batch,
                # Validitatea de la turul trecut. Clientul o compară cu cea de
                # acum și reia dosarul de la început dacă s-a schimbat.
                uid_validity=mailbox.uid_validity,
            )
        except ImapError as exc:
            # Se scrie pe rând, ca să se vadă pe ecran. O parolă schimbată
            # oprește preluarea, iar fără urma asta documentele pur și simplu nu
            # mai vin și nimeni nu află de ce.
            outcome.error = str(exc)[:MAX_ERROR]
            mailbox.last_error = outcome.error[:255]
            logger.warning("imap_fetch_failed", mailbox=str(credentials), error=str(exc))
            return outcome

        for message in page.messages:
            self._take_message(mailbox, message, senders, outcome)

        # Abia acum: un atașament nepreluat trebuie să reapară în turul următor.
        if page.last_uid:
            mailbox.last_uid = page.last_uid
        if page.uid_validity is not None:
            mailbox.uid_validity = page.uid_validity
        mailbox.last_synced_at = datetime.now(UTC)
        mailbox.last_error = None
        outcome.has_more = page.has_more
        return outcome

    # ── Un mesaj ────────────────────────────────────────────────────────────

    def _take_message(
        self,
        mailbox: ImapMailbox,
        message: ImapMessage,
        senders: dict[str, uuid.UUID],
        outcome: ImapMailboxResult,
    ) -> None:
        if not message.attachments:
            outcome.skipped += 1
            return

        client_id = self.intake.client_for(senders, message.sender)
        for attachment in message.attachments:
            self._take_attachment(mailbox, message, attachment, client_id, outcome)

    def _take_attachment(
        self,
        mailbox: ImapMailbox,
        message: ImapMessage,
        attachment: ImapAttachment,
        client_id: uuid.UUID | None,
        outcome: ImapMailboxResult,
    ) -> None:
        common = Attachment(
            # Poziția în mesaj: IMAP nu dă identificatori de atașament, iar ea
            # este singurul lucru stabil la o recitire a aceluiași mesaj.
            id=str(attachment.index),
            name=attachment.name,
            size=attachment.size,
            is_inline=attachment.is_inline,
        )
        if not is_document(common):
            outcome.skipped += 1
            return

        def open_stream() -> BinaryIO:
            # Octeții sunt deja aici: IMAP livrează mesajul întreg, deci nu mai
            # există o a doua cerere care să poată eșua.
            return io.BytesIO(attachment.content)

        result = self.intake.ingest(
            organization_id=mailbox.organization_id,
            message_id=message.message_id,
            attachment=common,
            sender=message.sender,
            recipient=mailbox.username,
            subject=message.subject,
            received_at=message.received_at,
            client_id=client_id,
            raw_payload={"folder": mailbox.folder, "uid": message.uid, "size": attachment.size},
            open_stream=open_stream,
            actor_name="Sistem · Email",
        )

        if result.kind is IngestKind.FAILED:
            outcome.failed += 1
        elif result.kind is IngestKind.SKIPPED:
            outcome.skipped += 1
        else:
            mailbox.files_ingested += 1
            outcome.ingested += 1

    # ── Ajutoare ────────────────────────────────────────────────────────────

    @staticmethod
    def _credentials(mailbox: ImapMailbox) -> ImapCredentials:
        return ImapCredentials(
            host=mailbox.host,
            port=mailbox.port,
            username=mailbox.username,
            password=decrypt(mailbox.password),
            use_ssl=mailbox.use_ssl,
        )


__all__ = ["ImapMailboxResult", "ImapSyncResult", "ImapSyncService"]
