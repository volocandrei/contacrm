"""Arhivarea unui document aprobat (§10, §11, §16).

Aprobarea și arhivarea sunt un singur act: un document aprobat care nu a ajuns în
arhivă nu este nicăieri. Aici se întâmplă partea a doua.

Trei lucruri se întâmplă, în ordine:

1. **Originalul nu se atinge.** Copia standardizată primește o cheie nouă; fișierul
   primit rămâne exact așa cum a venit (§16). O probă contabilă nu se rescrie.
2. **Numele se generează**, prin exact aceleași reguli ca în frontend
   (`app/domain/filenames.py`, port al lui `frontend/src/lib/filename.ts`). Numele
   trimis de expeditor participă doar cu extensia, și doar după verificare.
3. **Coliziunile se rezolvă cu un sufix**, iar unicitatea este garantată de un index
   parțial în baza de date — nu doar de căutarea dinaintea scrierii.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.domain.document_state import assert_transition
from app.domain.enums import DocumentErrorCode, DocumentStatus
from app.domain.filenames import FilenameInput, build_archive_path, build_document_filename
from app.models.client import Client
from app.models.document import Document, DocumentVersion
from app.services.storage import ObjectNotFoundError, StorageProvider
from app.services.storage.keys import archive_key

logger = get_logger(__name__)

# Câte nume alternative încercăm înainte să renunțăm. Zece documente identice ale
# aceluiași client, în aceeași lună, cu aceeași serie și același număr, înseamnă că
# altceva este greșit — nu numele.
MAX_COLLISION_ATTEMPTS = 10


class ArchiveError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.PROCESSING_ERROR, message)


class DocumentArchiveService:
    def __init__(self, session: Session, storage: StorageProvider) -> None:
        self.session = session
        self.storage = storage

    # ── Numele și locul ─────────────────────────────────────────────────────

    def client_name(self, document: Document) -> str | None:
        """Numele clientului, pentru nume de fișier și cale.

        Se citește la arhivare, nu se ține pe document: dacă firma își schimbă
        numele, arhiva deja scrisă rămâne cum a fost — ceea ce este corect pentru o
        probă contabilă — dar documentele noi îl folosesc pe cel curent.
        """
        if document.client_id is None:
            return None
        client = self.session.get(Client, document.client_id)
        return client.name if client else None

    def filename_input(
        self,
        document: Document,
        *,
        client_name: str | None,
        collision_suffix: int | None = None,
    ) -> FilenameInput:
        return FilenameInput(
            original_filename=document.original_filename,
            document_date=document.document_date,
            document_type_label=document.document_type.label if document.document_type else None,
            client_name=client_name,
            series=document.series,
            document_number=document.document_number,
            mime_type=document.mime_type,
            collision_suffix=collision_suffix,
        )

    def _taken_names(self, document: Document, archive_path: str) -> set[str]:
        """Numele deja folosite în același dosar de arhivă."""
        rows = self.session.scalars(
            select(Document.stored_filename).where(
                Document.organization_id == document.organization_id,
                Document.archive_path == archive_path,
                Document.stored_filename.is_not(None),
                Document.deleted_at.is_(None),
                Document.id != document.id,
            )
        ).all()
        return {name for name in rows if name is not None}

    def choose_name(self, document: Document, archive_path: str, client_name: str | None) -> str:
        """Primul nume liber din dosar.

        Fără sufix pentru primul; de la al doilea încolo `_2`, `_3`, … — exact ca
        în backendul simulat, care este contractul.
        """
        taken = self._taken_names(document, archive_path)

        candidate = build_document_filename(self.filename_input(document, client_name=client_name))
        suffix = 2
        while candidate in taken and suffix < MAX_COLLISION_ATTEMPTS + 2:
            candidate = build_document_filename(
                self.filename_input(document, client_name=client_name, collision_suffix=suffix)
            )
            suffix += 1

        if candidate in taken:
            raise ArchiveError(
                "Prea multe documente cu același nume în același dosar de arhivă. "
                "Verifică dacă nu sunt de fapt duplicate."
            )
        return candidate

    # ── Arhivarea ───────────────────────────────────────────────────────────

    def archive(self, document: Document, *, actor_id: uuid.UUID | None = None) -> Document:
        """Duce documentul aprobat în arhivă.

        Se apelează imediat după `approve`, în aceeași tranzacție: dacă scrierea în
        stocare eșuează, aprobarea se dă înapoi odată cu ea. Un document nu are voie
        să rămână `APPROVED` cu arhiva goală.
        """
        assert_transition(document.status, DocumentStatus.ARCHIVED)

        client_name = self.client_name(document)
        archive_path = build_archive_path(document.reference_month, client_name)
        stored_filename = self.choose_name(document, archive_path, client_name)

        version_number = self._next_version(document.id)
        key = archive_key(
            document.organization_id,
            document.id,
            mime_type=document.mime_type,
            version=version_number,
        )

        try:
            self.storage.copy(document.storage_key, key)
        except ObjectNotFoundError as exc:
            # Rândul spune că există un fișier, stocarea spune că nu. Nu arhivăm
            # o promisiune goală.
            document.error_code = DocumentErrorCode.ARCHIVE_FAILED
            logger.error("archive_source_missing", document_id=str(document.id))
            raise ArchiveError("Fișierul documentului nu mai există în stocare.") from exc

        document.archive_key = key
        document.archive_path = archive_path
        document.stored_filename = stored_filename
        document.archived_at = datetime.now(UTC)
        document.status = DocumentStatus.ARCHIVED
        document.error_code = None

        self.session.add(
            DocumentVersion(
                document_id=document.id,
                version_number=version_number,
                kind="archive",
                storage_key=key,
                sha256_hash=document.sha256_hash,
                file_size=document.file_size,
                mime_type=document.mime_type,
                uploaded_by=actor_id,
                reason="Arhivare după aprobare",
            )
        )
        self.session.flush()

        logger.info(
            "document_archived",
            document_id=str(document.id),
            stored_filename=stored_filename,
            archive_path=archive_path,
        )
        return document

    def _next_version(self, document_id: uuid.UUID) -> int:
        existing = self.session.scalars(
            select(DocumentVersion.version_number).where(DocumentVersion.document_id == document_id)
        ).all()
        return max(existing, default=0) + 1


__all__ = ["ArchiveError", "DocumentArchiveService"]
