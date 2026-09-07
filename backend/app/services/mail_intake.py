"""Un atașament de email devine document — regulile, într-un singur loc.

**De ce există fișierul acesta.** Preluarea din email a fost scrisă întâi pentru
Microsoft Graph (M10), iar regulile ei sunt reguli de business, nu detalii de
protocol: care atașament este document și care este logo-ul din semnătură, cum se
află clientul din adresa expeditorului, ce se întâmplă cu o adresă care aparține
la două firme, cum se recunoaște un atașament preluat deja.

Din clipa în care aceleași documente pot veni și dintr-o cutie IMAP obișnuită —
Gmail, Yahoo, cutia de la găzduire — cele două drumuri trebuie să decidă
**identic**. Copiate, ar fi început să se despartă la prima corectură: un prag
schimbat într-un loc, iar aceeași factură ar fi intrat pe un drum și ar fi fost
respinsă pe celălalt, fără ca cineva să poată spune de ce.

**Ce nu decide fișierul ăsta:** de unde vin mesajele și cum se autentifică. Acelea
sunt cu adevărat diferite între Graph și IMAP, și rămân fiecare la locul lui.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.enums import DocumentSource, IntakeStatus
from app.models.client import Client, Contact
from app.models.document import DocumentIntake
from app.services.audit import AuditService
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError
from app.services.processing_queue import enqueue as enqueue_processing
from app.services.storage import StorageProvider

logger = get_logger(__name__)

#: Sub atâția octeți, un atașament este aproape sigur un logo de semnătură. Cea
#: mai mică factură PDF reală trece binișor de pragul ăsta.
MIN_ATTACHMENT_BYTES = 8 * 1024

#: Cât din mesajul unei erori se păstrează. Coloana are 255.
MAX_ERROR = 500


class MailFetchError(Exception):
    """Atașamentul nu a putut fi adus de la sursă.

    Fiecare protocol are excepțiile lui — `DriveError` la Graph, `IMAP4.error` la
    IMAP. Aici intră traduse, ca partea comună să nu cunoască niciunul.
    """


class IngestKind(StrEnum):
    """Ce s-a întâmplat cu un atașament. Contoarele apelantului se fac din el."""

    INGESTED = "INGESTED"
    #: Documentul există deja, cu același conținut. Nu este o eroare.
    DUPLICATE = "DUPLICATE"
    #: Nu era un document — sau fusese deja preluat.
    SKIPPED = "SKIPPED"
    #: Sursa nu a dat fișierul. Rândul de intake rămâne, ca urmă.
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    kind: IngestKind
    document_id: uuid.UUID | None = None

    @property
    def counts_as_ingested(self) -> bool:
        return self.kind in (IngestKind.INGESTED, IngestKind.DUPLICATE)


@dataclass(frozen=True, slots=True)
class Attachment:
    """Un atașament, redus la ce contează pentru decizia de intake."""

    #: Identificator stabil în cadrul mesajului. Împreună cu id-ul mesajului
    #: formează cheia pe care se sprijină idempotența.
    id: str
    name: str
    size: int
    #: Logo-ul din semnătura expeditorului este tot un atașament. Nu e document.
    is_inline: bool = False


def is_document(attachment: Attachment) -> bool:
    """Un logo de semnătură nu este un document contabil.

    Fără pragul ăsta, fiecare email ar produce trei „documente" pe care cineva ar
    trebui să le respingă manual — iar după a doua zi nu le-ar mai respinge
    nimeni, ci ar închide ecranul.
    """
    if attachment.is_inline or not attachment.id:
        return False
    return attachment.size >= MIN_ATTACHMENT_BYTES


class MailIntakeService:
    """Partea comună a preluării din email, oricare ar fi cutia poștală."""

    def __init__(self, session: Session, storage: StorageProvider) -> None:
        self.session = session
        self.uploads = DocumentUploadService(session, storage)
        self.audit = AuditService(session)

    def sender_map(self, organization_id: uuid.UUID) -> dict[str, uuid.UUID]:
        """Adresele de contact ale clienților, normalizate.

        Aceeași adresă la doi clienți este o ambiguitate reală — un contabil care
        este contact la două firme, de exemplu. Acolo nu ghicim: adresa se scoate
        din hartă și mesajul rămâne neatribuit, ca un om să decidă.
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

    def client_for(self, senders: dict[str, uuid.UUID], sender: str) -> uuid.UUID | None:
        """Clientul, după adresa expeditorului.

        **Normalizarea se face aici, nu în client.** Dacă providerul întoarce
        adresa cu majuscule — sau dacă mâine se schimbă providerul — regula rămâne
        aceeași. Un client de protocol nu are voie să fie singurul loc în care se
        respectă o regulă de potrivire.
        """
        return senders.get(sender.strip().lower())

    def already_taken(
        self, organization_id: uuid.UUID, message_id: str, attachment_id: str
    ) -> bool:
        """A mai intrat atașamentul ăsta? Cheia este mesajul plus atașamentul."""
        existing = self.session.scalars(
            select(DocumentIntake.id).where(
                DocumentIntake.organization_id == organization_id,
                DocumentIntake.source == DocumentSource.EMAIL,
                DocumentIntake.external_message_id == message_id[:255],
                DocumentIntake.external_attachment_id == attachment_id[:255],
            )
        ).first()
        return existing is not None

    def ingest(
        self,
        *,
        organization_id: uuid.UUID,
        message_id: str,
        attachment: Attachment,
        sender: str,
        recipient: str,
        subject: str,
        received_at: datetime | None,
        client_id: uuid.UUID | None,
        raw_payload: dict[str, Any],
        open_stream: Callable[[], BinaryIO],
        actor_name: str,
    ) -> IngestOutcome:
        """Aduce atașamentul și îl face document.

        **Rândul de intake se scrie înainte de descărcare.** Dacă sursa refuză
        fișierul, rămâne o urmă respinsă, cu motivul — altfel un atașament care
        n-a putut fi adus ar dispărea fără să afle nimeni că a existat.
        """
        if self.already_taken(organization_id, message_id, attachment.id):
            return IngestOutcome(IngestKind.SKIPPED)

        intake = DocumentIntake(
            organization_id=organization_id,
            source=DocumentSource.EMAIL,
            status=IntakeStatus.RECEIVED,
            # Perechea pe care se sprijină idempotența: mesajul și atașamentul.
            external_message_id=message_id[:255],
            external_attachment_id=attachment.id[:255],
            sender=sender[:320],
            recipient=recipient[:320],
            subject=subject[:512],
            original_filename=attachment.name[:512],
            received_at=received_at or datetime.now(UTC),
            raw_payload=raw_payload,
        )
        self.session.add(intake)
        self.session.flush()

        try:
            stream = open_stream()
        except MailFetchError as exc:
            self.reject(intake, f"Descărcare eșuată: {exc}")
            return IngestOutcome(IngestKind.FAILED)

        try:
            upload = self.uploads.upload(
                organization_id=organization_id,
                stream=stream,
                original_filename=attachment.name or "atasament",
                source=DocumentSource.EMAIL,
                # Expeditorul dă clientul. Necunoscut înseamnă neatribuit, nu ghicit.
                client_id=client_id,
                intake=intake,
                received_at=received_at,
            )
        except FileValidationError as exc:
            # Un `.docx` sau o semnătură scăpată de filtru: nu este un document
            # contabil, și atât. Nu este o eroare a sistemului.
            self.reject(intake, exc.message)
            return IngestOutcome(IngestKind.SKIPPED)

        intake.status = IntakeStatus.DUPLICATE if upload.is_duplicate else IntakeStatus.ACCEPTED
        intake.document_id = upload.document.id

        self.audit.record(
            organization_id=organization_id,
            action="DOCUMENT_INGESTED_FROM_EMAIL",
            entity_type="Document",
            entity_id=str(upload.document.id),
            user_id=None,
            user_name=actor_name,
            detail=f"{sender} · {attachment.name}",
        )

        if not upload.is_duplicate:
            enqueue_processing(self.session, upload.document)

        return IngestOutcome(
            IngestKind.DUPLICATE if upload.is_duplicate else IngestKind.INGESTED,
            document_id=upload.document.id,
        )

    def reject(self, intake: DocumentIntake, reason: str) -> None:
        intake.status = IntakeStatus.REJECTED
        intake.rejection_reason = reason[:255]
        logger.info("mail_attachment_rejected", filename=intake.original_filename, reason=reason)


__all__ = [
    "MAX_ERROR",
    "MIN_ATTACHMENT_BYTES",
    "Attachment",
    "IngestKind",
    "IngestOutcome",
    "MailFetchError",
    "MailIntakeService",
    "is_document",
]
