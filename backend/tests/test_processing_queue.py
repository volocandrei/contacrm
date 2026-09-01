"""Coada de procesare ca outbox, și recuperarea cererilor abandonate (§38, §43).

Defectul pe care îl previn testele astea a fost găsit la M5.5 rulând serverul, nu
în teste: procesarea era programată în memorie, deci un proces care cădea între
„am salvat documentul" și „am pornit taskul" lăsa documentul tăcut în `RECEIVED`,
cu zero încercări și fără nicio urmă.

Aici verificăm cele două jumătăți ale soluției: cererea se scrie în aceeași
tranzacție cu documentul, iar ce a rămas pe drum se poate relua.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob, DocumentType
from app.models.organization import Organization
from app.services import processing_queue as queue
from app.services.document_processing import DocumentProcessingService
from app.services.extraction.mock import MockDocumentExtractionProvider
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db


def make_document(
    db: Session, org: Organization, storage: LocalStorageProvider, *, client: Client | None = None
) -> Document:
    document_id = uuid.uuid4()
    key = f"organizations/{org.id}/documents/{document_id}/original/source.pdf"
    storage.save(key, _stream(b"%PDF-1.7\n" + b"0" * 400 + b"\n%%EOF"))
    document = Document(
        id=document_id,
        organization_id=org.id,
        client_id=client.id if client else None,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=key,
        mime_type="application/pdf",
        file_size=417,
        sha256_hash="a" * 64,
        received_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    return document


class _Stream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._data[self._at :] if size < 0 else self._data[self._at : self._at + size]
        self._at += len(chunk)
        return chunk


def _stream(data: bytes) -> _Stream:
    return _Stream(data)


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def types(db: Session, org: Organization) -> dict[str, DocumentType]:
    from app.domain.document_types import DEFAULT_DOCUMENT_TYPES

    created: dict[str, DocumentType] = {}
    for index, spec in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = DocumentType(
            organization_id=org.id,
            code=spec.code,
            label=spec.label,
            required_fields=list(spec.required_fields),
            sort_order=index,
        )
        db.add(row)
        created[spec.code] = row
    db.flush()
    return created


def service(db: Session, storage: LocalStorageProvider) -> DocumentProcessingService:
    return DocumentProcessingService(db, storage, MockDocumentExtractionProvider())


# ── Outbox ───────────────────────────────────────────────────────────────────


class TestEnqueue:
    def test_the_request_is_written_as_a_pending_job(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)

        assert job.status == queue.PENDING
        assert job.attempt == 1
        assert job.started_at is None
        assert job.idempotency_key == f"{document.id}:1"

    def test_a_second_request_does_not_create_a_second_job(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Două apăsări pe „Reprocesează" nu înseamnă două procesări."""
        document = make_document(db, org, storage)
        first = queue.enqueue(db, document)
        second = queue.enqueue(db, document)

        assert second.id == first.id
        jobs = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).all()
        assert len(jobs) == 1

    def test_a_stale_running_job_is_revived_by_a_new_request(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Butonul de reprocesare deblochează și documentele înțepenite."""
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)
        job.status = queue.RUNNING
        job.started_at = datetime.now(UTC) - timedelta(hours=2)
        db.flush()

        revived = queue.enqueue(db, document, stale_after=timedelta(minutes=15))
        assert revived.id == job.id
        assert revived.status == queue.PENDING
        # Nu este o încercare nouă, este aceeași care nu s-a terminat.
        assert revived.attempt == 1

    def test_a_fresh_running_job_is_left_alone(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)
        job.status = queue.RUNNING
        job.started_at = datetime.now(UTC)
        db.flush()

        same = queue.enqueue(db, document, stale_after=timedelta(minutes=15))
        assert same.status == queue.RUNNING

    def test_a_finished_job_does_not_block_a_new_request(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        first = queue.enqueue(db, document)
        queue.finish(first, queue.SUCCEEDED)
        document.processing_attempts = 1
        db.flush()

        second = queue.enqueue(db, document)
        assert second.id != first.id
        assert second.attempt == 2


class TestClaim:
    def test_claiming_moves_the_job_into_running(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)

        claimed = queue.claim(db, job.idempotency_key, provider="mock")
        assert claimed is not None
        assert claimed.status == queue.RUNNING
        assert claimed.started_at is not None
        assert claimed.provider == "mock"

    def test_a_job_can_be_claimed_only_once(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Doi executanți care pornesc pe aceeași cerere: doar unul lucrează."""
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)

        assert queue.claim(db, job.idempotency_key) is not None
        assert queue.claim(db, job.idempotency_key) is None

    def test_an_unknown_key_claims_nothing(self, db: Session) -> None:
        assert queue.claim(db, "inexistent") is None


class TestProcessingUsesTheOutbox:
    def test_processing_claims_the_enqueued_job_instead_of_creating_one(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        document = make_document(db, org, storage, client=client_row)
        job = queue.enqueue(db, document)

        service(db, storage).process(org.id, document.id, idempotency_key=job.idempotency_key)

        jobs = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).all()
        assert len(jobs) == 1
        assert jobs[0].status == queue.SUCCEEDED
        assert document.processing_attempts == 1

    def test_a_direct_call_without_an_outbox_row_still_works(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """CLI, test, worker care reia manual: cererea *este* apelul."""
        document = make_document(db, org, storage, client=client_row)
        outcome = service(db, storage).process(org.id, document.id)

        assert not outcome.skipped
        assert document.processing_attempts == 1

    def test_a_job_for_a_document_that_moved_on_is_closed_as_skipped(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        types: dict[str, DocumentType],
        client_row: Client,
    ) -> None:
        """Altfel recuperarea ar relua la nesfârșit ceva ce nu mai are ce face."""
        document = make_document(db, org, storage, client=client_row)
        job = queue.enqueue(db, document)
        # Din `APPROVED` procesarea nu este o tranziție permisă (§40).
        document.status = DocumentStatus.APPROVED
        db.flush()

        outcome = service(db, storage).process(
            org.id, document.id, idempotency_key=job.idempotency_key
        )

        assert outcome.skipped
        assert job.status == queue.SKIPPED
        assert job.finished_at is not None


# ── Recuperare ───────────────────────────────────────────────────────────────


class TestAbandonedJobs:
    def test_a_pending_job_counts_as_abandoned_whatever_its_age(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Nu a pornit niciodată: nimeni nu lucrează la el, oricât de recent ar fi."""
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)

        found = queue.abandoned(db, running_older_than=timedelta(minutes=15))
        assert [j.id for j in found] == [job.id]

    def test_a_running_job_is_abandoned_only_past_the_threshold(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)
        job.status = queue.RUNNING
        job.started_at = datetime.now(UTC)
        db.flush()

        assert queue.abandoned(db, running_older_than=timedelta(minutes=15)) == []

        job.started_at = datetime.now(UTC) - timedelta(hours=1)
        db.flush()
        assert [j.id for j in queue.abandoned(db, running_older_than=timedelta(minutes=15))] == [
            job.id
        ]

    def test_finished_jobs_are_never_abandoned(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)
        for status in (queue.SUCCEEDED, queue.FAILED, queue.SKIPPED):
            job.status = status
            db.flush()
            assert queue.abandoned(db, running_older_than=timedelta(0)) == []

    def test_resetting_returns_the_job_to_the_queue_without_spending_an_attempt(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)
        job.status = queue.RUNNING
        job.started_at = datetime.now(UTC) - timedelta(hours=1)
        job.error_detail = "a murit procesul"
        db.flush()

        queue.reset(db, job)

        assert job.status == queue.PENDING
        assert job.started_at is None
        assert job.error_detail is None
        # Un proces care cade repetat nu are voie să consume limita de reprocesări.
        assert job.attempt == 1
