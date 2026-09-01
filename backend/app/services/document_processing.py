"""Pipeline-ul de procesare a unui document (§19, §38-§43, §52-§55).

`process(document_id)` este singura intrare. Semnătura este deliberat aceea a unui
task de worker: astăzi o cheamă un background task din același proces, mâine o
cheamă Celery, fără să se schimbe nimic aici.

Ordinea, și de ce contează:

1. **blocarea rândului** — două worker-e care iau același document nu trebuie să-l
   proceseze de două ori (§43);
2. **verificarea stării** — dacă documentul nu mai poate intra în procesare, ne
   oprim fără să facem nimic. Asta face reluarea aceleiași cereri inofensivă (§39);
3. **jobul** — se înregistrează *înainte* de lucru, ca un eșec să lase o urmă;
4. **extracția** — providerul primește doar fișierul; nu are acces la baza de date;
5. **aplicarea** — valorile propuse se scriu doar peste câmpurile pe care un om nu
   le-a corectat deja. O corecție manuală nu se pierde la reprocesare;
6. **validarea și decizia de verificare** — pe praguri din configurare (§23).

Nimic din conținutul documentului nu ajunge în loguri (§52).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.document_state import can_transition
from app.domain.enums import DocumentErrorCode, DocumentStatus, FieldSource
from app.models.document import Document, DocumentProcessingJob
from app.repositories.document import DocumentRepository
from app.services.audit import AuditService
from app.services.document_fields import SPEC_BY_NAME, DocumentFieldWriter, FieldUpdate
from app.services.document_validation import DocumentValidationService, ValidationLevel
from app.services.extraction.base import (
    DocumentExtractionProvider,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)
from app.services.storage import ObjectNotFoundError, StorageProvider

logger = get_logger(__name__)

JOB_TYPE = "EXTRACTION"


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    """Ce s-a întâmplat, pentru apelant și pentru teste."""

    document_id: uuid.UUID
    status: DocumentStatus
    skipped: bool = False
    reason: str | None = None
    error_code: DocumentErrorCode | None = None


class DocumentProcessingService:
    def __init__(
        self,
        session: Session,
        storage: StorageProvider,
        extractor: DocumentExtractionProvider,
        *,
        validator: DocumentValidationService | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.extractor = extractor
        self.documents = DocumentRepository(session)
        self.fields = DocumentFieldWriter(session)
        self.audit = AuditService(session)
        self.validator = validator or DocumentValidationService()

    # ── Intrarea ────────────────────────────────────────────────────────────

    def process(
        self,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        idempotency_key: str | None = None,
        triggered_by: uuid.UUID | None = None,
    ) -> ProcessingOutcome:
        document = self.documents.get_for_update(organization_id, document_id)
        if document is None:
            return ProcessingOutcome(
                document_id=document_id,
                status=DocumentStatus.ERROR,
                skipped=True,
                reason="Document inexistent.",
            )

        # Reluarea unei cereri deja tratate nu trebuie să producă nimic (§39).
        key = idempotency_key or f"{document_id}:{document.processing_attempts + 1}"
        if self._already_handled(key):
            logger.info("processing_skipped", document_id=str(document_id), reason="idempotent")
            return ProcessingOutcome(
                document_id=document_id,
                status=document.status,
                skipped=True,
                reason="Cerere deja tratată.",
            )

        if not can_transition(document.status, DocumentStatus.PROCESSING).allowed:
            logger.info(
                "processing_skipped",
                document_id=str(document_id),
                reason="state",
                status=document.status.value,
            )
            return ProcessingOutcome(
                document_id=document_id,
                status=document.status,
                skipped=True,
                reason=f"Documentul nu poate intra în procesare din {document.status.value}.",
            )

        document.processing_attempts += 1
        job = DocumentProcessingJob(
            document_id=document.id,
            job_type=JOB_TYPE,
            status="RUNNING",
            attempt=document.processing_attempts,
            idempotency_key=key,
            provider=self.extractor.name,
            started_at=datetime.now(UTC),
        )
        self.session.add(job)
        document.status = DocumentStatus.PROCESSING
        document.error_code = None
        document.error_detail = None
        self.session.flush()

        try:
            result = self._extract(document)
        except ExtractionError as exc:
            return self._fail(document, job, DocumentErrorCode.OCR_FAILED, str(exc))
        except ObjectNotFoundError:
            return self._fail(
                document, job, DocumentErrorCode.STORAGE_FAILED, "Fișierul lipsește din storage."
            )

        self._apply(document, result)
        return self._decide(document, job, result)

    # ── Pași ────────────────────────────────────────────────────────────────

    def _already_handled(self, key: str) -> bool:
        return (
            self.session.scalars(
                select(DocumentProcessingJob).where(DocumentProcessingJob.idempotency_key == key)
            ).first()
            is not None
        )

    def _extract(self, document: Document) -> ExtractionResult:
        with self.storage.open(document.storage_key) as handle:
            return self.extractor.extract(
                ExtractionInput(
                    stream=handle,
                    mime_type=document.mime_type,
                    original_filename=document.original_filename,
                    sha256=document.sha256_hash,
                )
            )

    def _apply(self, document: Document, result: ExtractionResult) -> None:
        """Scrie valorile propuse, fără să calce peste corecțiile umane.

        Un câmp marcat `MANUAL` a fost corectat de cineva care a văzut documentul.
        Extracția nu are dreptul să-l suprascrie, nici la reprocesare (§32).
        """
        metadata: dict[str, Any] = dict(document.field_metadata or {})
        types = {t.code: t for t in self.documents.list_types(document.organization_id)}

        protected = {
            name
            for name, entry in metadata.items()
            if entry.get("source") == FieldSource.MANUAL.value
        }

        updates: list[FieldUpdate] = []
        proposed: dict[str, Any] = {}

        if result.document_type_code and "documentType" not in protected:
            updates.append(FieldUpdate(field="documentType", value=result.document_type_code))
            proposed["documentType"] = {
                "source": FieldSource.AI.value,
                "confidence": result.classification_confidence,
            }

        for name, extracted in result.fields.items():
            if name in protected or name not in SPEC_BY_NAME:
                continue
            if not extracted.is_present:
                continue
            updates.append(FieldUpdate(field=name, value=extracted.value))
            proposed[name] = {
                "source": extracted.source.value,
                "confidence": extracted.confidence,
            }

        # Scrierea trece prin același writer ca și corecțiile umane, deci conversiile
        # și validările de format sunt aceleași.
        self.fields.apply(document, updates, changed_by=None, document_types=types)

        # `apply` a marcat totul ca MANUAL; proveniența reală este cea propusă de
        # provider, iar câmpurile protejate rămân neatinse.
        metadata = dict(document.field_metadata or {})
        for name, entry in proposed.items():
            metadata[name] = entry
        document.field_metadata = metadata

        document.ocr_provider = result.provider
        document.ocr_confidence = result.ocr_confidence
        document.ocr_text = result.ocr_text
        document.ai_provider = result.provider
        document.ai_model = result.model
        document.ai_prompt_version = result.prompt_version
        document.ai_classification_confidence = result.classification_confidence
        document.ai_extraction_confidence = result.extraction_confidence
        document.extraction_duration_ms = result.duration_ms

    def _decide(
        self, document: Document, job: DocumentProcessingJob, result: ExtractionResult
    ) -> ProcessingOutcome:
        outcome = self.validator.validate(document)
        document.validation_issues = outcome.issues

        if document.client_id is None:
            # Fără client, documentul nu poate avansa: cineva trebuie să-l atribuie.
            document.status = DocumentStatus.UNMATCHED
            document.review_required = True
        elif self.validator.needs_review(document, outcome):
            document.status = DocumentStatus.REVIEW_REQUIRED
            document.review_required = True
        else:
            document.status = DocumentStatus.APPROVED
            document.review_required = False
            document.approved_at = datetime.now(UTC)

        job.status = "SUCCEEDED"
        job.finished_at = datetime.now(UTC)
        job.duration_ms = result.duration_ms

        self.audit.record(
            organization_id=document.organization_id,
            action="DOCUMENT_PROCESSED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=None,
            user_name="sistem",
            detail=f"{result.provider} · {document.status.value}",
            new_value={
                "status": document.status.value,
                "confidence": document.ai_extraction_confidence,
                "validation": outcome.level.value,
            },
        )
        self.session.flush()

        logger.info(
            "document_processed",
            document_id=str(document.id),
            job_id=str(job.id),
            attempt=job.attempt,
            provider=result.provider,
            duration_ms=result.duration_ms,
            status=document.status.value,
            validation=outcome.level.value,
            # Nici textul OCR, nici valorile extrase nu ajung în log (§52).
        )
        return ProcessingOutcome(document_id=document.id, status=document.status)

    def _fail(
        self,
        document: Document,
        job: DocumentProcessingJob,
        code: DocumentErrorCode,
        detail: str,
    ) -> ProcessingOutcome:
        document.status = DocumentStatus.ERROR
        document.error_code = code
        document.error_detail = detail[:512]
        document.review_required = True
        document.validation_issues = [detail]

        job.status = "FAILED"
        job.error_code = code.value
        job.error_detail = detail[:512]
        job.finished_at = datetime.now(UTC)

        self.audit.record(
            organization_id=document.organization_id,
            action="DOCUMENT_PROCESSING_FAILED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=None,
            user_name="sistem",
            detail=code.value,
        )
        self.session.flush()
        logger.warning(
            "document_processing_failed",
            document_id=str(document.id),
            job_id=str(job.id),
            attempt=job.attempt,
            error_code=code.value,
        )
        return ProcessingOutcome(
            document_id=document.id, status=DocumentStatus.ERROR, error_code=code
        )

    # ── Reprocesare (§54) ───────────────────────────────────────────────────

    def can_reprocess(self, document: Document) -> tuple[bool, str | None]:
        if document.processing_attempts >= settings.max_processing_attempts:
            return False, (
                f"Documentul a fost procesat de {document.processing_attempts} ori; "
                "limita configurată a fost atinsă."
            )
        if not can_transition(
            document.status, DocumentStatus.PROCESSING, explicit_reprocess=True
        ).allowed:
            return False, f"Nu se poate reprocesa din starea {document.status.value}."
        return True, None


__all__ = [
    "JOB_TYPE",
    "DocumentProcessingService",
    "ProcessingOutcome",
    "ValidationLevel",
]
