"""Ruta prin care un planificator extern face treaba workerului (§38, §43).

Ce se verifică aici este în primul rând ce **nu** are voie să se întâmple: un
endpoint care execută muncă nu are voie să fie atins de nimeni fără secret, și nu
are voie să existe deloc cât timp secretul nu este configurat.

Restul — că un tur chiar procesează ce e în coadă — este deja acoperit în
`test_worker.py`; aici ne interesează doar că ruta cheamă exact acel drum, nu unul
paralel.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core import config as core_config
from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.services import processing_queue as queue
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

SECRET = "un-secret-de-cron-suficient-de-lung"

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
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def cron_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_config.settings, "cron_secret", SECRET)


@pytest.fixture
def cron_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_config.settings, "cron_secret", "")


@pytest.fixture
def cron_api(api: TestClient, storage: LocalStorageProvider) -> Iterator[TestClient]:
    api.app.dependency_overrides[get_storage] = lambda: storage  # type: ignore[attr-defined]
    yield api


@pytest.fixture
def worker_sees_the_test_data(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Turul de coada isi face propriile sesiuni; aici le legam de cea a testului.

    Fara asta, `session_scope()` ar deschide o conexiune noua, care nu vede nimic
    din ce a scris testul — tranzactia lui nu este comisa si nu trebuie sa fie.
    """
    from sqlalchemy.orm import sessionmaker

    import app.core.db as core_db

    factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(core_db, "SessionFactory", factory)


@pytest.mark.usefixtures("cron_enabled")
class TestAuthorization:
    """Fără secret potrivit, ruta se poartă ca și cum nu ar exista."""

    def test_without_a_header_it_does_not_exist(self, client: TestClient) -> None:
        response = client.get("/api/v1/internal/run-queue")
        assert response.status_code == 404

    def test_a_wrong_secret_does_not_exist_either(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/internal/run-queue", headers={"Authorization": "Bearer altceva"}
        )
        assert response.status_code == 404

    def test_an_empty_bearer_is_not_a_match(self, client: TestClient) -> None:
        """Un secret gol nu se potrivește cu un secret gol: comparația e pe valoare."""
        response = client.get("/api/v1/internal/run-queue", headers={"Authorization": "Bearer "})
        assert response.status_code == 404

    def test_the_route_is_absent_from_the_public_schema(self, client: TestClient) -> None:
        """Nu apare în OpenAPI: nu este parte din contractul cu frontend-ul (§73)."""
        paths = client.get("/openapi.json").json()["paths"]
        assert not [path for path in paths if "internal" in path]


class TestDisabledByDefault:
    def test_without_a_configured_secret_nothing_opens_it(
        self, client: TestClient, cron_disabled: None
    ) -> None:
        """Implicit oprită. Un endpoint care execută muncă nu pornește deschis."""
        for header in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer x"}):
            response = client.get("/api/v1/internal/run-queue", headers=header)
            assert response.status_code == 404


@requires_db
@pytest.mark.usefixtures("cron_enabled")
class TestRunning:
    @pytest.fixture
    def organization(self, db: Session) -> Organization:
        row = Organization(name="Cabinet Demo SRL")
        db.add(row)
        db.flush()
        return row

    @pytest.fixture
    def client_row(self, db: Session, organization: Organization) -> Client:
        row = Client(organization_id=organization.id, name="Alfa Conta SRL")
        db.add(row)
        db.flush()
        return row

    @pytest.fixture
    def types(self, db: Session, organization: Organization) -> None:
        from app.domain.document_types import DEFAULT_DOCUMENT_TYPES

        for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
            db.add(
                DocumentType(
                    organization_id=organization.id,
                    code=seed.code,
                    label=seed.label,
                    sort_order=index,
                    required_fields=list(seed.required_fields),
                )
            )
        db.flush()

    def make_document(
        self,
        db: Session,
        organization: Organization,
        storage: LocalStorageProvider,
        client_row: Client,
    ) -> Document:
        document_id = uuid.uuid4()
        key = f"organizations/{organization.id}/documents/{document_id}/original/source.pdf"
        storage.save(key, _Stream(PDF))
        document = Document(
            id=document_id,
            organization_id=organization.id,
            client_id=client_row.id,
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

    def test_an_empty_queue_is_not_an_error(self, cron_api: TestClient) -> None:
        response = cron_api.get(
            "/api/v1/internal/run-queue", headers={"Authorization": f"Bearer {SECRET}"}
        )
        assert response.status_code == 200
        assert response.json() == {"requeued": 0, "executed": 0}

    def test_a_beat_processes_what_the_queue_holds(
        self,
        cron_api: TestClient,
        db: Session,
        organization: Organization,
        client_row: Client,
        types: None,
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        document = self.make_document(db, organization, storage, client_row)
        queue.enqueue(db, document)

        response = cron_api.get(
            "/api/v1/internal/run-queue", headers={"Authorization": f"Bearer {SECRET}"}
        )

        assert response.status_code == 200
        assert response.json()["executed"] == 1

        db.refresh(document)
        assert document.status is not DocumentStatus.RECEIVED

    def test_a_second_beat_finds_nothing_left(
        self,
        cron_api: TestClient,
        db: Session,
        organization: Organization,
        client_row: Client,
        types: None,
        storage: LocalStorageProvider,
        worker_sees_the_test_data: None,
    ) -> None:
        """Două bătăi suprapuse nu se calcă: revendicarea din coadă este atomică."""
        document = self.make_document(db, organization, storage, client_row)
        queue.enqueue(db, document)

        first = cron_api.get(
            "/api/v1/internal/run-queue", headers={"Authorization": f"Bearer {SECRET}"}
        )
        second = cron_api.get(
            "/api/v1/internal/run-queue", headers={"Authorization": f"Bearer {SECRET}"}
        )

        assert first.json()["executed"] == 1
        assert second.json()["executed"] == 0
