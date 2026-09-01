"""Pipeline-ul de procesare: extracție, validare, decizie, idempotență.

Providerul mock este determinist pe conținutul fișierului, deci aceleași octeți dau
mereu același rezultat — testele nu depind de noroc.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentErrorCode, DocumentStatus, FieldSource
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob, DocumentType
from app.models.organization import Organization
from app.services.document_processing import DocumentProcessingService
from app.services.document_upload import DocumentUploadService
from app.services.document_validation import DocumentValidationService, ValidationLevel
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)
from app.services.extraction.mock import MockDocumentExtractionProvider
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"


# ── Providerul mock (fără bază de date) ──────────────────────────────────────


def _input(content: bytes = PDF) -> ExtractionInput:
    return ExtractionInput(
        stream=io.BytesIO(content),
        mime_type="application/pdf",
        original_filename="a.pdf",
        sha256=hashlib.sha256(content).hexdigest(),
    )


class TestMockProvider:
    def test_is_deterministic_for_the_same_content(self) -> None:
        """O reprocesare nu trebuie să schimbe valorile de la sine."""
        provider = MockDocumentExtractionProvider()
        first = provider.extract(_input())
        second = provider.extract(_input())

        assert first.document_type_code == second.document_type_code
        assert {k: v.value for k, v in first.fields.items()} == {
            k: v.value for k, v in second.fields.items()
        }

    def test_different_content_gives_different_values(self) -> None:
        provider = MockDocumentExtractionProvider()
        a = provider.extract(_input(PDF))
        b = provider.extract(_input(PDF + b"altceva"))
        assert a.fields["documentNumber"].value != b.fields["documentNumber"].value

    def test_amounts_are_internally_consistent(self) -> None:
        """subtotal + TVA = total, ca datele sintetice să treacă propria validare."""
        result = MockDocumentExtractionProvider().extract(_input())
        subtotal = Decimal(result.fields["subtotal"].value or "0")
        vat = Decimal(result.fields["vatAmount"].value or "0")
        total = Decimal(result.fields["totalAmount"].value or "0")
        assert subtotal + vat == total

    def test_every_field_carries_its_own_confidence(self) -> None:
        """Un total cu 95% și o dată cu 40% nu au ce căuta sub același număr (§21)."""
        result = MockDocumentExtractionProvider().extract(_input())
        present = [f for f in result.fields.values() if f.is_present]
        assert all(f.confidence is not None for f in present)
        assert all(0 <= f.confidence <= 1 for f in present if f.confidence is not None)

    def test_does_not_invent_fields_a_receipt_does_not_have(self) -> None:
        """Bonurile fiscale nu au serie; providerul nu completează gol."""
        provider = MockDocumentExtractionProvider()
        for suffix in range(40):
            result = provider.extract(_input(PDF + str(suffix).encode()))
            if result.document_type_code in {"BON_FISCAL", "EXTRAS_CONT", "CHITANTA"}:
                assert not result.fields["series"].is_present
                return
        pytest.skip("Setul sintetic nu a produs un bon fiscal în 40 de încercări.")

    def test_aggregate_confidence_ignores_empty_fields(self) -> None:
        """Absența unei serii nu înseamnă că extracția a mers prost."""
        result = ExtractionResult(
            provider="test",
            duration_ms=1,
            fields={
                "a": ExtractedValue(value="x", confidence=0.9),
                "b": ExtractedValue(value=None, confidence=None, source=FieldSource.EMPTY),
            },
        )
        assert result.extraction_confidence == 0.9

    def test_an_unreadable_document_raises(self) -> None:
        provider = MockDocumentExtractionProvider()
        failures = 0
        for suffix in range(200):
            try:
                provider.extract(_input(PDF + str(suffix).encode()))
            except ExtractionError:
                failures += 1
        assert failures > 0, "Fluxul de eroare nu este exersat de setul sintetic."


# ── Validare (fără bază de date pentru praguri) ──────────────────────────────


class TestValidationThresholds:
    def _document(self, **kwargs: object) -> Document:
        document = Document(
            organization_id=uuid.uuid4(),
            status=DocumentStatus.PROCESSING,
            source="UPLOAD",
            original_filename="a.pdf",
            storage_key="k",
            mime_type="application/pdf",
            file_size=1,
            sha256_hash="a" * 64,
            received_at=datetime.now(UTC),
            **kwargs,  # type: ignore[arg-type]
        )
        # Fara tip nu se poate valida nimic, iar testele de aici masoara altceva.
        document.document_type = DocumentType(
            organization_id=document.organization_id,
            code="ALTE_DOCUMENTE",
            label="Alte documente",
            required_fields=[],
        )
        return document

    def test_amount_mismatch_is_a_warning(self) -> None:
        """Aritmetică pură: nu presupune nicio cotă și nu calculează TVA."""
        document = self._document(
            subtotal=Decimal("100.00"),
            vat_amount=Decimal("19.00"),
            total_amount=Decimal("200.00"),
            client_id=uuid.uuid4(),
        )
        outcome = DocumentValidationService().validate(document)
        assert outcome.level is ValidationLevel.WARNING
        assert any("nu se potrivesc" in issue for issue in outcome.issues)

    def test_matching_amounts_pass(self) -> None:
        document = self._document(
            subtotal=Decimal("100.00"),
            vat_amount=Decimal("19.00"),
            total_amount=Decimal("119.00"),
            client_id=uuid.uuid4(),
        )
        assert not any(
            "nu se potrivesc" in issue
            for issue in DocumentValidationService().validate(document).issues
        )

    def test_missing_client_is_flagged(self) -> None:
        outcome = DocumentValidationService().validate(self._document())
        assert any("Clientul" in issue for issue in outcome.issues)

    def test_thresholds_come_from_configuration(self) -> None:
        """Nu sunt hardcodate, și cu atât mai puțin în frontend (§23)."""
        document = self._document(client_id=uuid.uuid4(), ai_extraction_confidence=0.80)

        strict = DocumentValidationService(auto_threshold=0.95, review_threshold=0.85)
        lenient = DocumentValidationService(auto_threshold=0.50, review_threshold=0.30)

        assert strict.validate(document).level is ValidationLevel.WARNING
        assert lenient.validate(document).level is ValidationLevel.VALID


# ── Pipeline (cu bază de date) ───────────────────────────────────────────────

pytestmark = requires_db


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def types(db: Session, org: Organization) -> dict[str, DocumentType]:
    created: dict[str, DocumentType] = {}
    for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = DocumentType(
            organization_id=org.id,
            code=seed.code,
            label=seed.label,
            sort_order=index,
            required_fields=list(seed.required_fields),
        )
        db.add(row)
        created[seed.code] = row
    db.flush()
    return created


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL")
    db.add(row)
    db.flush()
    return row


def upload(
    db: Session,
    storage: LocalStorageProvider,
    org: Organization,
    *,
    content: bytes = PDF,
    client: Client | None = None,
) -> Document:
    return (
        DocumentUploadService(db, storage)
        .upload(
            organization_id=org.id,
            stream=io.BytesIO(content),
            original_filename="factura.pdf",
            client_id=client.id if client else None,
        )
        .document
    )


def service(
    db: Session, storage: LocalStorageProvider, **kwargs: object
) -> DocumentProcessingService:
    return DocumentProcessingService(
        db,
        storage,
        MockDocumentExtractionProvider(**kwargs),  # type: ignore[arg-type]
    )


class TestPipeline:
    def test_a_received_document_reaches_review(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """Bucla din §79: după procesare, documentul așteaptă un om."""
        document = upload(db, storage, org, client=client_row)
        assert document.status is DocumentStatus.RECEIVED

        outcome = service(db, storage).process(org.id, document.id)

        assert outcome.status is DocumentStatus.REVIEW_REQUIRED
        assert document.review_required is True
        assert document.ai_extraction_confidence is not None
        assert document.document_type is not None
        assert document.ocr_text is not None

    def test_a_document_without_a_client_becomes_unmatched(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
    ) -> None:
        document = upload(db, storage, org)
        outcome = service(db, storage).process(org.id, document.id)

        assert outcome.status is DocumentStatus.UNMATCHED
        assert any("Clientul" in issue for issue in document.validation_issues)

    def test_extracted_fields_carry_ai_provenance(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """Ce a propus modelul nu trebuie să pară introdus de om (§32)."""
        document = upload(db, storage, org, client=client_row)
        service(db, storage).process(org.id, document.id)

        metadata = document.field_metadata
        assert metadata["supplierName"]["source"] == FieldSource.AI.value
        assert metadata["supplierName"]["confidence"] is not None
        assert metadata["documentType"]["source"] == FieldSource.AI.value

    def test_records_a_job_with_provider_and_duration(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = upload(db, storage, org, client=client_row)
        service(db, storage).process(org.id, document.id)

        job = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).one()
        assert job.status == "SUCCEEDED"
        assert job.attempt == 1
        assert job.provider == "mock"
        assert job.duration_ms is not None
        assert job.finished_at is not None

    def test_processing_is_audited_without_document_content(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = upload(db, storage, org, client=client_row)
        service(db, storage).process(org.id, document.id)

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "DOCUMENT_PROCESSED")).one()
        assert entry.user_name == "sistem"
        assert document.ocr_text is not None
        assert document.ocr_text[:20] not in (entry.detail or "")


class TestIdempotency:
    def test_the_same_request_twice_does_nothing_the_second_time(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """Workerul care primește aceeași livrare de două ori (§39)."""
        document = upload(db, storage, org, client=client_row)
        key = f"delivery-{uuid.uuid4()}"

        first = service(db, storage).process(org.id, document.id, idempotency_key=key)
        second = service(db, storage).process(org.id, document.id, idempotency_key=key)

        assert not first.skipped
        assert second.skipped
        assert document.processing_attempts == 1
        jobs = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).all()
        assert len(jobs) == 1

    def test_an_already_processed_document_is_not_reprocessed_silently(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = upload(db, storage, org, client=client_row)
        service(db, storage).process(org.id, document.id)
        document.status = DocumentStatus.ARCHIVED
        document.archived_at = datetime.now(UTC)
        document.stored_filename = "x.pdf"
        db.flush()

        outcome = service(db, storage).process(org.id, document.id)
        assert outcome.skipped
        assert document.status is DocumentStatus.ARCHIVED


class TestManualCorrectionsSurvive:
    def test_reprocessing_does_not_overwrite_a_human_correction(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """Cineva a văzut documentul și a corectat; modelul nu are dreptul să revină peste."""
        document = upload(db, storage, org, client=client_row)
        service(db, storage).process(org.id, document.id)

        document.supplier_name = "Furnizor Corectat Manual SRL"
        document.field_metadata = {
            **document.field_metadata,
            "supplierName": {"source": FieldSource.MANUAL.value, "confidence": None},
        }
        document.status = DocumentStatus.REVIEW_REQUIRED
        db.flush()

        service(db, storage).process(org.id, document.id)

        assert document.supplier_name == "Furnizor Corectat Manual SRL"
        assert document.field_metadata["supplierName"]["source"] == FieldSource.MANUAL.value


class TestFailures:
    def test_an_extraction_error_leaves_a_structured_code(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nu un traceback într-un câmp, ci un cod pe care îl poți filtra (§53)."""
        document = upload(db, storage, org, client=client_row)

        def explode(_self: object, _source: ExtractionInput) -> ExtractionResult:
            raise ExtractionError("OCR eșuat: imagine neclară.")

        monkeypatch.setattr(MockDocumentExtractionProvider, "extract", explode)
        outcome = service(db, storage).process(org.id, document.id)

        assert outcome.status is DocumentStatus.ERROR
        assert document.error_code is DocumentErrorCode.OCR_FAILED
        assert "traceback" not in (document.error_detail or "").lower()

        job = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).one()
        assert job.status == "FAILED"
        assert job.error_code == "OCR_FAILED"

    def test_a_missing_file_is_reported_as_a_storage_failure(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = upload(db, storage, org, client=client_row)
        storage.delete(document.storage_key)

        outcome = service(db, storage).process(org.id, document.id)
        assert outcome.status is DocumentStatus.ERROR
        assert document.error_code is DocumentErrorCode.STORAGE_FAILED

    def test_an_error_can_be_retried(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = upload(db, storage, org, client=client_row)

        def explode(_self: object, _source: ExtractionInput) -> ExtractionResult:
            raise ExtractionError("temporar")

        monkeypatch.setattr(MockDocumentExtractionProvider, "extract", explode)
        service(db, storage).process(org.id, document.id)
        assert document.status is DocumentStatus.ERROR

        monkeypatch.undo()
        outcome = service(db, storage).process(org.id, document.id)
        assert outcome.status in {DocumentStatus.REVIEW_REQUIRED, DocumentStatus.UNMATCHED}
        assert document.processing_attempts == 2


class TestReprocessLimits:
    def test_refuses_beyond_the_configured_attempts(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = upload(db, storage, org, client=client_row)
        document.processing_attempts = 99
        db.flush()

        allowed, reason = service(db, storage).can_reprocess(document)
        assert not allowed
        assert reason is not None and "limita" in reason

    def test_an_archived_document_needs_an_explicit_request(
        self,
        db: Session,
        storage: LocalStorageProvider,
        org: Organization,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """`can_reprocess` cere explicit; procesarea obișnuită nu atinge arhiva."""
        document = upload(db, storage, org, client=client_row)
        document.status = DocumentStatus.ARCHIVED
        document.archived_at = datetime.now(UTC)
        document.stored_filename = "x.pdf"
        db.flush()

        allowed, _ = service(db, storage).can_reprocess(document)
        assert allowed
        assert service(db, storage).process(org.id, document.id).skipped


def test_auto_approval_stays_off_by_default(
    db: Session,
    storage: LocalStorageProvider,
    org: Organization,
    types: dict[str, DocumentType],
    client_row: Client,
) -> None:
    """Aprobarea unei probe contabile fără om este o decizie de business (§23)."""
    from app.core.config import settings

    assert settings.auto_approve_enabled is False

    document = upload(db, storage, org, client=client_row)
    # Chiar și cu încredere maximă, documentul așteaptă un om.
    outcome = DocumentProcessingService(
        db, storage, MockDocumentExtractionProvider(base_confidence=1.0)
    ).process(org.id, document.id)

    assert outcome.status is DocumentStatus.REVIEW_REQUIRED
