"""Primirea unui document: de la octeți la rând în bază (§9, §75).

Ordinea operațiilor este partea care contează, pentru că storage-ul și baza de date
sunt două sisteme care nu împart o tranzacție:

1. se validează antetul — un format nesuportat nu ajunge niciodată pe disc;
2. se creează rândul `documents` (fără commit), ca să avem un id;
3. se scrie fișierul la o cheie derivată **din acel id**, nu din numele primit;
4. se completează rândul cu ce s-a scris efectiv — mărime, hash, tip;
5. se caută duplicat, sub o încuietoare pe conținut (altfel două încărcări
   simultane ale aceluiași fișier nu se văd una pe alta);
6. se înregistrează versiunea 1 și intrarea de audit.

Dacă pasul 3 eșuează, tranzacția se dă înapoi și nu rămâne niciun rând. Dacă pașii
de după eșuează, `cleanup` șterge fișierul deja scris — altfel storage-ul ar acumula
obiecte pe care nimic nu le mai referă. Cazul invers, „fișier lipsă dar rând
existent", nu poate apărea: rândul primește `storage_key` abia după scriere.

Serviciul **nu** pornește procesarea. Upload-ul răspunde repede, iar OCR-ul rulează
în worker (§38); legătura se face în M5.5.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.locks import lock_content
from app.core.logging import get_logger
from app.domain.enums import DocumentSource, DocumentStatus, IntakeStatus
from app.models.document import Document, DocumentIntake, DocumentVersion
from app.models.user import User
from app.services.duplicates import DuplicateDetectionService, DuplicateResult
from app.services.files import FileValidationError, ValidatingReader
from app.services.storage import StorageProvider, original_key
from app.services.storage.base import StorageError

logger = get_logger(__name__)


@dataclass(slots=True)
class UploadResult:
    document: Document
    duplicate: DuplicateResult | None

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate is not None


class DocumentUploadService:
    def __init__(self, session: Session, storage: StorageProvider) -> None:
        self.session = session
        self.storage = storage
        self.duplicates = DuplicateDetectionService(session)

    def upload(
        self,
        *,
        organization_id: uuid.UUID,
        stream: BinaryIO,
        original_filename: str,
        source: DocumentSource = DocumentSource.UPLOAD,
        uploaded_by: User | None = None,
        client_id: uuid.UUID | None = None,
        intake: DocumentIntake | None = None,
        received_at: datetime | None = None,
    ) -> UploadResult:
        """Primește un fișier și creează documentul corespunzător.

        Aruncă `FileValidationError` pentru fișiere respinse — apelantul îl traduce
        în răspunsul HTTP potrivit.
        """
        # 1. Antetul, înainte de orice scriere.
        reader = ValidatingReader(stream)
        now = received_at or datetime.now(UTC)

        # 2. Rândul, ca să avem un id pentru cheie. `flush`, nu `commit`.
        document = Document(
            organization_id=organization_id,
            client_id=client_id,
            intake_id=intake.id if intake else None,
            status=DocumentStatus.RECEIVED,
            source=source,
            # Numele primit se păstrează ca informație, dar nu ajunge într-o cale.
            original_filename=original_filename[:512],
            storage_key="",
            mime_type=reader.mime_type,
            file_size=1,
            sha256_hash="0" * 64,
            received_at=now,
        )
        self.session.add(document)
        self.session.flush()

        key = original_key(organization_id, document.id, mime_type=reader.mime_type)

        # 3. Scrierea. Un eșec aici lasă tranzacția să cadă, fără rânduri orfane.
        try:
            stored = self.storage.save(key, reader)
        except FileValidationError:
            # Fișier prea mare, descoperit la citire. Ce s-a scris parțial a fost
            # deja curățat de provider.
            self.session.expunge(document)
            raise
        except StorageError:
            self.session.expunge(document)
            logger.exception("upload_storage_failed", document_id=str(document.id))
            raise

        # 4. Ce s-a scris efectiv, nu ce am presupus.
        inspected = reader.result
        document.storage_key = stored.key
        document.file_size = stored.size
        document.sha256_hash = stored.sha256

        # Providerul și cititorul au hash-uit independent aceiași octeți. Dacă nu
        # coincid, ceva a modificat fluxul între ei și nu putem avea încredere în
        # niciunul dintre rezultate.
        if stored.sha256 != inspected.sha256:  # pragma: no cover — apărare în adâncime
            self._cleanup(key)
            raise StorageError("Hash inconsistent între cititor și storage.")

        try:
            # 5. Duplicat? Documentul se păstrează oricum (§11).
            #
            # Încuietoarea este pe **conținut**, nu pe tabel: două încărcări
            # simultane ale aceluiași fișier trebuie să se vadă una pe alta, iar
            # căutarea de mai jos nu poate vedea un rând necomis. Fără ea, ambele
            # intrau ca documente noi — verificat pe server, de trei ori din
            # patru. Fișiere diferite nu se așteaptă niciodată: cheia le separă.
            lock_content(self.session, organization_id, stored.sha256)
            duplicate = self.duplicates.find_duplicate(
                organization_id, sha256_hash=stored.sha256, exclude_id=document.id
            )
            if duplicate is not None:
                document.is_duplicate = True
                document.duplicate_of_id = duplicate.original_id
                document.status = DocumentStatus.DUPLICATE
                document.review_required = True
                document.validation_issues = ["Conținut identic cu un document deja primit."]

            # 6. Versiunea 1: originalul, care nu se suprascrie niciodată (§16, R8).
            self.session.add(
                DocumentVersion(
                    document_id=document.id,
                    version_number=1,
                    kind="original",
                    storage_key=stored.key,
                    sha256_hash=stored.sha256,
                    file_size=stored.size,
                    mime_type=inspected.mime_type,
                    uploaded_by=uploaded_by.id if uploaded_by else None,
                    reason="Fișier primit",
                )
            )

            if intake is not None:
                intake.document_id = document.id
                intake.status = (
                    IntakeStatus.DUPLICATE if duplicate is not None else IntakeStatus.ACCEPTED
                )

            self.session.flush()
        except Exception:
            # Fișierul e deja pe disc, dar rândurile nu vor exista. Îl ștergem, ca
            # storage-ul să nu acumuleze obiecte fără referință.
            self._cleanup(key)
            raise

        logger.info(
            "document_uploaded",
            document_id=str(document.id),
            size=stored.size,
            mime_type=inspected.mime_type,
            source=source.value,
            duplicate=duplicate is not None,
        )
        return UploadResult(document=document, duplicate=duplicate)

    def _cleanup(self, key: str) -> None:
        """Șterge un fișier scris pentru un document care nu va exista."""
        try:
            self.storage.delete(key)
        except StorageError:  # pragma: no cover — best effort
            logger.exception("upload_cleanup_failed", key=key)
