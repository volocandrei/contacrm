"""Când stocarea nu răspunde: nicio reușită falsă (§12, §13).

**Regula, într-o propoziție:** dacă fișierul nu a ajuns pe disc, nimic din baza de
date nu are voie să spună că a ajuns.

Este cea mai scumpă categorie de defect dintr-o aplicație de documente contabile,
fiindcă eșecul **nu se vede la momentul lui**. Un document marcat `ARCHIVED` fără
copie în arhivă arată identic cu unul arhivat corect: apare pe ecran, intră în
raport, se numără la închiderea lunii. Lipsa se descoperă abia când cineva îl
caută — de obicei la un control, la luni distanță, când nu mai există de unde
să fie refăcut.

**Ce se simulează aici:** disc plin, drept de scriere refuzat, fișier dispărut
între rândul din bază și stocare. Nu se simulează defectarea discului în sine —
aceea o prinde `check-storage` din runbook, care compară baza cu stocarea.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.models.document import Document
from app.models.organization import Organization
from app.models.user import User
from app.services.document_archive import ArchiveError, DocumentArchiveService
from app.services.document_upload import DocumentUploadService
from app.services.storage import LocalStorageProvider, StorageError
from tests.conftest import requires_db

pytestmark = requires_db

pytest_plugins = ("tests.test_documents_api",)

PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"


class FullDisk(LocalStorageProvider):
    """O stocare pe care scrisul eșuează, ca un disc plin sau fără drepturi.

    Se moștenește providerul adevărat, nu se scrie unul de la zero: citirea,
    ștergerea și calculul cheilor rămân cele reale, iar testul măsoară exact ce
    vrea — ce se întâmplă **când scrisul cade**.
    """

    def __init__(self, root: Path, *, message: str = "No space left on device") -> None:
        super().__init__(root)
        self.message = message
        self.writes_attempted = 0

    def save(self, key: str, stream: object) -> object:  # type: ignore[override]
        self.writes_attempted += 1
        raise StorageError(self.message)

    def copy(self, source: str, destination: str) -> object:  # type: ignore[override]
        self.writes_attempted += 1
        raise StorageError(self.message)


@pytest.fixture
def full_disk(tmp_path: Path) -> FullDisk:
    return FullDisk(tmp_path / "storage")


@pytest.fixture
def working_storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage-ok")


class TestUploadWhenTheDiskIsFull:
    def test_no_document_row_survives_a_failed_write(
        self, db: Session, org: Organization, admin: User, full_disk: FullDisk
    ) -> None:
        """Un rând fără fișier este un document care nu se va putea deschide niciodată."""
        service = DocumentUploadService(db, full_disk)
        before = db.query(Document).count()

        with pytest.raises(StorageError):
            service.upload(
                organization_id=org.id,
                stream=io.BytesIO(PDF),
                original_filename="factura.pdf",
                uploaded_by=admin,
            )

        db.rollback()
        assert full_disk.writes_attempted == 1, "testul nu a atins deloc scrierea"
        assert db.query(Document).count() == before

    def test_the_failure_is_loud(
        self, db: Session, org: Organization, admin: User, full_disk: FullDisk
    ) -> None:
        """Se ridică o eroare, nu se întoarce un rezultat pe jumătate.

        Contra-proba pentru testul de mai sus: dacă `upload` ar înghiți excepția
        și ar întoarce ceva, prima verificare ar trece — nu s-ar scrie niciun
        rând — dar apelantul ar crede că a reușit.
        """
        service = DocumentUploadService(db, full_disk)

        with pytest.raises(StorageError, match="No space left"):
            service.upload(
                organization_id=org.id,
                stream=io.BytesIO(PDF),
                original_filename="factura.pdf",
                uploaded_by=admin,
            )


class TestArchivingWhenTheDiskIsFull:
    def _received(
        self, db: Session, org: Organization, admin: User, storage: LocalStorageProvider
    ) -> Document:
        """Un document urcat cu adevărat, gata de arhivat."""
        result = DocumentUploadService(db, storage).upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF + uuid.uuid4().bytes),
            original_filename="factura.pdf",
            uploaded_by=admin,
        )
        document = result.document
        document.status = DocumentStatus.APPROVED
        document.reference_month = "2026-08"
        db.flush()
        return document

    def test_a_document_is_not_marked_archived_when_the_copy_fails(
        self,
        db: Session,
        org: Organization,
        admin: User,
        working_storage: LocalStorageProvider,
        tmp_path: Path,
    ) -> None:
        """**Testul pentru care există fișierul acesta.**

        Un document `ARCHIVED` fără copie în arhivă arată identic cu unul arhivat
        corect: apare pe ecran, intră în raport, se numără la închiderea lunii.
        Lipsa se descoperă la un control, luni mai târziu.
        """
        document = self._received(db, org, admin, working_storage)
        broken = FullDisk(tmp_path / "storage")

        with pytest.raises((ArchiveError, StorageError)):
            DocumentArchiveService(db, broken).archive(document)

        assert document.status is not DocumentStatus.ARCHIVED
        assert document.archive_key is None
        assert document.archived_at is None

    def test_a_missing_source_file_does_not_archive_a_promise(
        self,
        db: Session,
        org: Organization,
        admin: User,
        working_storage: LocalStorageProvider,
    ) -> None:
        """Rândul spune că există un fișier, stocarea spune că nu.

        Se întâmplă după o restaurare în care baza și fișierele sunt din momente
        diferite — cazul pe care `check-storage` îl prinde în runbook. Aici se
        verifică ce face aplicația dacă totuși ajunge acolo.
        """
        document = self._received(db, org, admin, working_storage)
        working_storage.delete(document.storage_key)

        with pytest.raises(ArchiveError, match="nu mai există"):
            DocumentArchiveService(db, working_storage).archive(document)

        assert document.status is not DocumentStatus.ARCHIVED
        assert document.error_code is not None, "eșecul trebuie să lase un motiv scris"

    def test_the_happy_path_still_archives(
        self,
        db: Session,
        org: Organization,
        admin: User,
        working_storage: LocalStorageProvider,
    ) -> None:
        """Contra-proba: fără ea, o arhivare complet ruptă ar trece testele de sus."""
        document = self._received(db, org, admin, working_storage)

        DocumentArchiveService(db, working_storage).archive(document)

        assert document.status is DocumentStatus.ARCHIVED
        assert document.archive_key is not None
        with working_storage.open(document.archive_key) as handle:
            assert handle.read().startswith(b"%PDF")
