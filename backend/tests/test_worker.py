"""Workerul care execută coada (§38, §43).

Ce se verifică aici este exact ce nu se putea verifica înainte: că procesarea se
întâmplă **în afara cererii HTTP**, dintr-un proces care ia de unul singur din
coadă. Până la M6, singurul executant era un background task din procesul API, iar
o cădere între upload și extracție lăsa documentul tăcut în `RECEIVED`.

Coada este tabelul, nu un broker: `claim_next` folosește `FOR UPDATE SKIP LOCKED`,
deci două worker-e care se uită în același timp iau seturi disjuncte.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import worker
from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob, DocumentType
from app.models.organization import Organization
from app.services import processing_queue as queue
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

PDF = b"%PDF-1.7\n" + b"0" * 400 + b"\n%%EOF"


class _Stream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._data[self._at :] if size < 0 else self._data[self._at : self._at + size]
        self._at += len(chunk)
        return chunk


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


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
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def worker_sees_the_test_data(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Workerul își face propriile sesiuni; aici le legăm de conexiunea testului.

    Fără asta, `session_scope()` ar deschide o conexiune nouă, care nu vede nimic din
    ce a scris testul — tranzacția lui nu este comisă și nu trebuie să fie. Cu
    `join_transaction_mode="create_savepoint"`, commit-urile workerului devin
    savepoint-uri în tranzacția testului, deci se văd aici și dispar la final.
    """
    from sqlalchemy.orm import sessionmaker

    import app.core.db as core_db

    connection = db.get_bind()
    factory = sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(core_db, "SessionFactory", factory)


def make_document(
    db: Session, org: Organization, storage: LocalStorageProvider, *, client: Client | None = None
) -> Document:
    document_id = uuid.uuid4()
    key = f"organizations/{org.id}/documents/{document_id}/original/source.pdf"
    storage.save(key, _Stream(PDF))
    document = Document(
        id=document_id,
        organization_id=org.id,
        client_id=client.id if client else None,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=key,
        mime_type="application/pdf",
        file_size=len(PDF),
        sha256_hash=uuid.uuid4().hex * 2,
        received_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    return document


class TestClaiming:
    def test_an_empty_queue_claims_nothing(self, db: Session) -> None:
        assert worker.next_batch() == []

    def test_a_job_cannot_outlive_its_document(
        self, db: Session, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Garanția vine din schemă, nu din cod: `ON DELETE CASCADE`.

        De aceea workerul nu are o ramură „documentul a dispărut": nu s-ar putea
        declanșa, iar cod defensiv pe care nimeni nu îl poate atinge este cod care
        putrezește.
        """
        document = make_document(db, org, storage)
        queue.enqueue(db, document)

        db.delete(document)
        db.flush()

        remaining = db.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.document_id == document.id)
        ).all()
        assert remaining == []

    def test_selecting_does_not_yet_claim(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        """Jobul rămâne `PENDING` până chiar înainte de muncă.

        Dacă ar fi marcat `RUNNING` aici, un worker care moare între selecție și
        extracție l-ar lăsa blocat până la pragul de vechime. Lăsat `PENDING`, este
        reluat imediat.
        """
        document = make_document(db, org, storage)
        job = queue.enqueue(db, document)

        found = worker.next_batch()
        assert [item[1] for item in found] == [document.id]

        db.refresh(job)
        assert job.status == queue.PENDING


class TestRunning:
    def test_the_worker_processes_what_the_queue_holds(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        """Procesarea se întâmplă în afara cererii HTTP — asta este tot rostul."""
        document = make_document(db, org, storage, client=client_row)
        queue.enqueue(db, document)

        assert worker.run_once(storage) == 1

        db.refresh(document)
        assert document.status is not DocumentStatus.RECEIVED
        assert document.processing_attempts == 1

    def test_a_second_pass_finds_nothing_left(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        document = make_document(db, org, storage, client=client_row)
        queue.enqueue(db, document)

        assert worker.run_once(storage) == 1
        assert worker.run_once(storage) == 0

    def test_the_batch_is_bounded(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        """Un tur nu are voie să înghită toată coada: workerul trebuie să apuce să
        verifice dacă a fost oprit."""
        for _ in range(5):
            queue.enqueue(db, make_document(db, org, storage, client=client_row))

        assert worker.run_once(storage, limit=2) == 2
        assert worker.run_once(storage, limit=2) == 2
        assert worker.run_once(storage, limit=2) == 1


class TestStopping:
    def test_the_first_signal_asks_the_second_insists(self) -> None:
        stopper = worker.Stopper()
        assert not stopper.requested

        stopper._handle(2, None)
        assert stopper.requested, "primul semnal cere oprirea ordonată"

        with pytest.raises(SystemExit):
            stopper._handle(2, None)

    def test_the_idle_sleep_wakes_up_when_asked_to_stop(self) -> None:
        """Un `SIGTERM` nu are voie să aștepte până expiră somnul."""
        import threading

        stopper = worker.Stopper()
        started = datetime.now(UTC)

        threading.Timer(0.1, lambda: setattr(stopper, "requested", True)).start()
        worker._sleep_interruptibly(5.0, stopper)

        assert datetime.now(UTC) - started < timedelta(seconds=2)
