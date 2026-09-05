"""Pipeline-ul de procesare a unui document (§19, §38-§43, §52-§55).

`process(document_id)` este singura intrare. Semnătura este deliberat aceea a unui
task de worker: o cheamă `app/worker.py` din propriul proces, un background task
din procesul API, sau ruta de cron — fără să se schimbe nimic aici. Dacă vreodată
apare un broker, tot aici ajunge.

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
from app.domain.document_actions import reprocess_check
from app.domain.document_state import can_transition
from app.domain.enums import DocumentErrorCode, DocumentStatus, FieldSource
from app.domain.periods import ReferencePeriodStrategy, derive_reference_month
from app.models.document import (
    Document,
    DocumentIntake,
    DocumentProcessingJob,
    DocumentType,
)
from app.repositories.document import DocumentRepository
from app.services import processing_queue as queue
from app.services.audit import AuditService
from app.services.client_aliases import ClientAliasService
from app.services.client_matching import TYPE_BY_ROLE, ClientMatcher, MatchRole
from app.services.document_archive import DocumentArchiveService
from app.services.document_fields import SPEC_BY_NAME, DocumentFieldWriter, FieldUpdate
from app.services.document_validation import DocumentValidationService, ValidationLevel
from app.services.extraction.base import (
    DocumentExtractionProvider,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)
from app.services.period_service import PeriodService
from app.services.storage import ObjectNotFoundError, StorageProvider

logger = get_logger(__name__)


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
        key = idempotency_key or queue.idempotency_key(
            document_id, document.processing_attempts + 1
        )
        job = self._claim(document, key)
        if job is None:
            logger.info("processing_skipped", document_id=str(document_id), reason="idempotent")
            return ProcessingOutcome(
                document_id=document_id,
                status=document.status,
                skipped=True,
                reason="Cerere deja tratată.",
            )

        if not can_transition(document.status, DocumentStatus.PROCESSING).allowed:
            # Documentul a mers între timp în altă parte. Jobul se închide ca
            # `SKIPPED`, nu rămâne `RUNNING`: altfel recuperarea l-ar relua la
            # nesfârșit, pentru ceva ce nu mai are ce face.
            reason = f"Documentul nu poate intra în procesare din {document.status.value}."
            queue.finish(job, queue.SKIPPED, error_detail=reason)
            self.session.flush()
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
                reason=reason,
            )

        document.processing_attempts = job.attempt
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
        # Înaintea perioadei: `_assign_period` atinge luna clientului, iar un client
        # găsit după aceea ar lăsa perioada fără rând.
        self._match_client(document, result)
        self._assign_period(document)
        return self._decide(document, job, result)

    # ── Pași ────────────────────────────────────────────────────────────────

    def _claim(self, document: Document, key: str) -> DocumentProcessingJob | None:
        """Ia jobul din outbox, sau îl creează dacă cererea vine direct.

        Ruta HTTP înregistrează cererea ca `PENDING` în aceeași tranzacție cu
        documentul (`processing_queue.enqueue`), deci aici o revendicăm. Un apel
        direct — CLI, test, worker care reia manual — nu a trecut pe acolo, iar
        atunci cererea *este* acest apel: creăm jobul pe loc.

        `None` înseamnă „altcineva a luat-o deja"."""
        claimed = queue.claim(self.session, key, provider=self.extractor.name)
        if claimed is not None:
            return claimed

        existing = self.session.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.idempotency_key == key)
        ).first()
        if existing is not None:
            return None

        job = DocumentProcessingJob(
            document_id=document.id,
            job_type=queue.JOB_TYPE,
            status=queue.RUNNING,
            attempt=document.processing_attempts + 1,
            idempotency_key=key,
            provider=self.extractor.name,
            started_at=datetime.now(UTC),
        )
        self.session.add(job)
        self.session.flush()
        return job

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
                "source": result.classification_source.value,
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

    def _match_client(self, document: Document, result: ExtractionResult) -> None:
        """Găsește clientul după codul fiscal de pe document (§8).

        Se citesc valorile **de pe document**, nu cele propuse de extracție: dacă
        un om a corectat deja codul fiscal, corectura lui decide. `_apply` a scris
        deja tot, inclusiv câmpurile protejate pe care nu le-a atins.

        Un client atribuit nu se rescrie niciodată, nici la reprocesare. Cine a
        pus documentul acolo — om sau sistem — a decis deja.
        """
        if document.client_id is not None:
            self._resolve_document_type(document, result)
            return

        match = ClientMatcher(self.session, document.organization_id).by_tax_ids(
            supplier_tax_id=document.supplier_tax_id,
            customer_tax_id=document.customer_tax_id,
        )
        if match is None:
            # Codurile fiscale nu au spus nimic — un extras de cont nu are CUI,
            # iar OCR-ul citește uneori greșit. Rămâne ce a învățat sistemul de la
            # oameni: de la ce adresă vin documentele cărui client.
            self._match_by_alias(document)
            return

        document.client_id = match.client_id
        self._resolve_document_type(document, result, role=match.role)

        # Urma spune **de ce**, nu doar că s-a întâmplat: fără codul care a produs
        # potrivirea, un operator care nu e de acord nu are ce verifica.
        self.audit.record(
            organization_id=document.organization_id,
            action="DOCUMENT_CLIENT_MATCHED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=None,
            user_name="sistem",
            detail=f"{match.client_name} · CUI {match.tax_id} · {match.role.value}",
            new_value={"clientId": str(match.client_id), "role": match.role.value},
        )
        logger.info(
            "document_client_matched",
            document_id=str(document.id),
            client_id=str(match.client_id),
            role=match.role.value,
        )

    def _match_by_alias(self, document: Document) -> None:
        """Clientul învățat pentru expeditorul documentului.

        **Nu stabilește tipul documentului.** Rolul — furnizor sau cumpărător —
        vine din codul fiscal care a produs potrivirea; un alias spune doar al cui
        este documentul, nu în ce calitate. Documentul merge la verificare cu
        clientul completat și tipul necompletat, ceea ce este adevărat.
        """
        aliases = ClientAliasService(self.session)
        match = aliases.match(document.organization_id, self._sender_of(document))
        if match is None:
            return

        document.client_id = match.client_id
        aliases.count_match(document.organization_id, match.sender)

        # Urma spune **de ce**: fără adresa care a produs potrivirea, un operator
        # care nu e de acord nu are ce verifica și nu știe ce alias să șteargă.
        self.audit.record(
            organization_id=document.organization_id,
            action="DOCUMENT_CLIENT_MATCHED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=None,
            user_name="sistem",
            detail=f"{match.client_name} · expeditor {match.sender}",
            new_value={"clientId": str(match.client_id), "sender": match.sender},
        )
        logger.info(
            "document_client_matched_by_alias",
            document_id=str(document.id),
            client_id=str(match.client_id),
        )

    def _sender_of(self, document: Document) -> str | None:
        intake = self.session.scalars(
            select(DocumentIntake).where(
                DocumentIntake.organization_id == document.organization_id,
                DocumentIntake.document_id == document.id,
            )
        ).first()
        return intake.sender if intake else None

    def _resolve_document_type(
        self,
        document: Document,
        result: ExtractionResult,
        *,
        role: MatchRole | None = None,
    ) -> None:
        """Alege între coduri pe care extracția nu le putea separa.

        Textul spune „factură" fără să spună a cui este. Rolul în care apare
        clientul o spune: furnizor înseamnă ieșire, cumpărător înseamnă intrare.

        Fără rol — client atribuit mai devreme, de un om sau de altă cale — nu se
        alege nimic. A ghici direcția ar pune documentul în registrul greșit, ceea
        ce este mai rău decât a-l lăsa neclasificat.
        """
        if not result.document_type_candidates or document.document_type_id is not None:
            return
        if role is None:
            return

        code = TYPE_BY_ROLE.get(role)
        if code is None or code not in result.document_type_candidates:
            return

        document_type = self.session.scalars(
            select(DocumentType).where(
                DocumentType.organization_id == document.organization_id,
                DocumentType.code == code,
                DocumentType.is_active.is_(True),
            )
        ).first()
        if document_type is None:
            return

        document.document_type_id = document_type.id
        document.document_type = document_type
        metadata = dict(document.field_metadata or {})
        # Nu a citit-o nimeni de pe document și nu a propus-o un model: a rezultat
        # dintr-o regulă aplicată peste ce știe sistemul despre proprii clienți.
        metadata["documentType"] = {"source": FieldSource.DERIVED.value, "confidence": None}
        document.field_metadata = metadata

    def _assign_period(self, document: Document) -> None:
        """Pune documentul în luna contabilă care i se cuvine (ADR-008).

        Doar dacă nu are deja una: o valoare pusă de un om nu se rescrie, nici la
        reprocesare. Dacă nu se poate deriva — documentul nu are dată — câmpul rămâne
        gol și motivul ajunge în validare. Nu inventăm o lună.
        """
        if document.reference_month:
            return

        derived = derive_reference_month(
            document_date=document.document_date,
            received_at=document.received_at,
            strategy=ReferencePeriodStrategy(settings.reference_period_strategy),
        )
        if derived is None:
            return

        document.reference_month = derived
        metadata = dict(document.field_metadata or {})
        # Proveniența spune adevărul: valoarea vine de la sistem, pe o regulă, nu de
        # la extracție și nici de la un om.
        metadata["referenceMonth"] = {"source": FieldSource.DERIVED.value, "confidence": None}
        document.field_metadata = metadata

        # Luna abia derivată trebuie și „atinsă": altfel perioada apare în rapoarte
        # dar nu are rând, iar momentul completării nu se prinde niciodată.
        if document.client_id is not None:
            PeriodService(self.session).touch(document.organization_id, document.client_id, derived)

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
            # Aprobarea automată arhivează pe loc, ca și cea făcută de un om: altfel
            # documentul ar rămâne aprobat și negăsibil în arhivă.
            document.status = DocumentStatus.APPROVED
            document.review_required = False
            document.approved_at = datetime.now(UTC)
            DocumentArchiveService(self.session, self.storage).archive(document)

        queue.finish(job, queue.SUCCEEDED, duration_ms=result.duration_ms)

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

        queue.finish(job, queue.FAILED, error_code=code.value, error_detail=detail)

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
        """Predicatul trăiește în domeniu: aceeași regulă alimentează și lista de
        acțiuni trimisă interfeței, ca butonul să nu promită ce ruta refuză."""
        return reprocess_check(
            document.status,
            document.processing_attempts,
            max_attempts=settings.max_processing_attempts,
        )


__all__ = [
    "DocumentProcessingService",
    "ProcessingOutcome",
    "ValidationLevel",
]
