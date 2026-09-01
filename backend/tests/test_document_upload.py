"""Validarea fișierelor și fluxul de upload, până la rândul din bază.

Fișierele de test sunt sintetice și minimale: doar antetul necesar ca formatul să
fie recunoscut, plus umplutură. Niciun document contabil real (§70).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentErrorCode, DocumentSource, DocumentStatus, IntakeStatus
from app.models.document import Document, DocumentIntake, DocumentVersion
from app.models.organization import Organization
from app.services.document_upload import DocumentUploadService
from app.services.files import FileValidationError, ValidatingReader, sniff_mime_type
from app.services.storage import LocalStorageProvider, StorageError
from tests.conftest import requires_db

# ── Fișiere sintetice ────────────────────────────────────────────────────────

PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512
WEBP = b"RIFF" + (600).to_bytes(4, "little") + b"WEBP" + b"\x00" * 512
# Un executabil Windows, redenumit oricum ar fi.
EXE = b"MZ\x90\x00\x03" + b"\x00" * 512
ZIP = b"PK\x03\x04" + b"\x00" * 512
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


# ── Validare (fără bază de date) ─────────────────────────────────────────────


class TestSniffing:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (PDF, "application/pdf"),
            (JPEG, "image/jpeg"),
            (PNG, "image/png"),
            (WEBP, "image/webp"),
        ],
    )
    def test_recognises_accepted_formats(self, content: bytes, expected: str) -> None:
        assert sniff_mime_type(content) == expected

    @pytest.mark.parametrize(
        "content", [EXE, ZIP, SVG, b"text simplu", b""], ids=["exe", "zip", "svg", "text", "gol"]
    )
    def test_refuses_everything_else(self, content: bytes) -> None:
        assert sniff_mime_type(content) is None


class TestValidatingReader:
    def test_extension_in_the_name_does_not_matter(self) -> None:
        """Un executabil numit `factura.pdf` rămâne un executabil (§9)."""
        with pytest.raises(FileValidationError) as caught:
            ValidatingReader(io.BytesIO(EXE))
        assert caught.value.code is DocumentErrorCode.UNSUPPORTED_FORMAT

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(FileValidationError) as caught:
            ValidatingReader(io.BytesIO(b""))
        assert caught.value.code is DocumentErrorCode.INVALID_FILE

    def test_content_type_declared_by_the_client_is_irrelevant(self) -> None:
        """Nu îl citim deloc: tipul vine din conținut (§50)."""
        reader = ValidatingReader(io.BytesIO(PDF))
        assert reader.mime_type == "application/pdf"

    def test_hash_and_size_match_the_content(self) -> None:
        import hashlib

        reader = ValidatingReader(io.BytesIO(PDF))
        assert reader.read() == PDF
        result = reader.result
        assert result.size == len(PDF)
        assert result.sha256 == hashlib.sha256(PDF).hexdigest()

    def test_reading_in_small_chunks_gives_the_same_result(self) -> None:
        reader = ValidatingReader(io.BytesIO(PDF))
        collected = b""
        while chunk := reader.read(7):
            collected += chunk
        assert collected == PDF
        assert reader.result.size == len(PDF)

    def test_oversized_file_is_stopped_while_reading(self) -> None:
        """Nu după ce a ajuns pe disc — limita se aplică în timpul citirii (§9)."""
        big = PDF + b"x" * 5000
        reader = ValidatingReader(io.BytesIO(big), max_size=1024)
        with pytest.raises(FileValidationError) as caught:
            reader.read()
        assert caught.value.code is DocumentErrorCode.FILE_TOO_LARGE

    def test_result_is_unavailable_before_the_stream_is_finished(self) -> None:
        reader = ValidatingReader(io.BytesIO(PDF))
        reader.read(4)
        with pytest.raises(RuntimeError):
            _ = reader.result

    def test_a_mime_type_outside_the_allowlist_is_refused(self) -> None:
        with pytest.raises(FileValidationError):
            ValidatingReader(io.BytesIO(PNG), allowed_mime_types=frozenset({"application/pdf"}))


# ── Upload (cu bază de date) ─────────────────────────────────────────────────


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
def service(db: Session, storage: LocalStorageProvider) -> DocumentUploadService:
    return DocumentUploadService(db, storage)


@requires_db
class TestUpload:
    def test_creates_a_document_with_what_was_actually_stored(
        self, service: DocumentUploadService, org: Organization
    ) -> None:
        import hashlib

        result = service.upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF),
            original_filename="factura ianuarie.pdf",
        )
        document = result.document

        assert document.status is DocumentStatus.RECEIVED
        assert document.mime_type == "application/pdf"
        assert document.file_size == len(PDF)
        assert document.sha256_hash == hashlib.sha256(PDF).hexdigest()
        assert document.original_filename == "factura ianuarie.pdf"

    def test_storage_key_is_generated_not_taken_from_the_filename(
        self, service: DocumentUploadService, org: Organization
    ) -> None:
        """Numele expeditorului nu ajunge niciodată într-o cale (§8, §14)."""
        result = service.upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF),
            original_filename="../../etc/passwd",
        )
        key = result.document.storage_key

        assert ".." not in key
        assert "passwd" not in key
        assert key == f"organizations/{org.id}/documents/{result.document.id}/original/source.pdf"

    def test_the_file_is_readable_back_from_storage(
        self, service: DocumentUploadService, org: Organization, storage: LocalStorageProvider
    ) -> None:
        result = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
        )
        with storage.open(result.document.storage_key) as handle:
            assert handle.read() == PDF

    def test_records_the_original_as_version_one(
        self, service: DocumentUploadService, org: Organization, db: Session
    ) -> None:
        """Originalul nu se suprascrie niciodată (§16, R8)."""
        result = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
        )
        versions = db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == result.document.id)
        ).all()

        assert len(versions) == 1
        assert versions[0].version_number == 1
        assert versions[0].kind == "original"
        assert versions[0].storage_key == result.document.storage_key

    @pytest.mark.parametrize(
        ("content", "expected_mime"),
        [(PDF, "application/pdf"), (JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
    )
    def test_accepts_every_allowed_format(
        self,
        service: DocumentUploadService,
        org: Organization,
        content: bytes,
        expected_mime: str,
    ) -> None:
        result = service.upload(
            organization_id=org.id, stream=io.BytesIO(content), original_filename="x"
        )
        assert result.document.mime_type == expected_mime

    def test_a_rejected_file_leaves_no_document_and_no_object(
        self,
        service: DocumentUploadService,
        org: Organization,
        db: Session,
        storage: LocalStorageProvider,
    ) -> None:
        with pytest.raises(FileValidationError):
            service.upload(
                organization_id=org.id, stream=io.BytesIO(EXE), original_filename="virus.pdf"
            )

        assert db.scalars(select(Document)).all() == []
        assert not any(storage.root.rglob("*.pdf"))

    def test_an_oversized_file_leaves_nothing_behind(
        self,
        service: DocumentUploadService,
        org: Organization,
        db: Session,
        storage: LocalStorageProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Storage-ul curăță ce a scris parțial, iar rândul nu rămâne (§75)."""
        from app.core import config

        monkeypatch.setattr(config.settings, "max_upload_size_mb", 0)
        with pytest.raises(FileValidationError):
            service.upload(
                organization_id=org.id, stream=io.BytesIO(PDF), original_filename="mare.pdf"
            )

        db.rollback()
        assert not any(p.is_file() for p in storage.root.rglob("*"))


@requires_db
class TestDuplicateDetection:
    def test_identical_content_is_marked_duplicate(
        self, service: DocumentUploadService, org: Organization
    ) -> None:
        first = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
        )
        second = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="cu-alt-nume.pdf"
        )

        assert second.is_duplicate
        assert second.document.status is DocumentStatus.DUPLICATE
        assert second.document.duplicate_of_id == first.document.id
        assert second.document.review_required is True

    def test_the_duplicate_file_is_kept_not_deleted(
        self, service: DocumentUploadService, org: Organization, storage: LocalStorageProvider
    ) -> None:
        """Decizia «chiar e același document?» aparține unui om (§11)."""
        service.upload(organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf")
        second = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="b.pdf"
        )
        assert storage.exists(second.document.storage_key)

    def test_a_different_name_does_not_make_a_different_document(
        self, service: DocumentUploadService, org: Organization
    ) -> None:
        first = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="factura.pdf"
        )
        second = service.upload(
            organization_id=org.id, stream=io.BytesIO(PDF), original_filename="cu totul altceva.pdf"
        )
        assert first.document.sha256_hash == second.document.sha256_hash

    def test_different_content_is_not_a_duplicate(
        self, service: DocumentUploadService, org: Organization
    ) -> None:
        service.upload(organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf")
        other = service.upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF + b"diferit"),
            original_filename="b.pdf",
        )
        assert not other.is_duplicate
        assert other.document.status is DocumentStatus.RECEIVED

    def test_duplicates_do_not_cross_organizations(
        self, service: DocumentUploadService, org: Organization, db: Session
    ) -> None:
        """Două cabinete pot avea, legitim, exact același document."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()

        service.upload(organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf")
        elsewhere = service.upload(
            organization_id=other.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
        )
        assert not elsewhere.is_duplicate


@requires_db
class TestIntakeLink:
    def test_an_intake_is_linked_and_marked_accepted(
        self, service: DocumentUploadService, org: Organization, db: Session
    ) -> None:
        intake = DocumentIntake(
            organization_id=org.id,
            source=DocumentSource.EMAIL,
            original_filename="atasament.pdf",
            received_at=datetime.now(UTC),
            external_message_id="msg-1",
            external_attachment_id="att-1",
            sender="client@exemplu.test",
        )
        db.add(intake)
        db.flush()

        result = service.upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF),
            original_filename="atasament.pdf",
            source=DocumentSource.EMAIL,
            intake=intake,
        )

        assert result.document.intake_id == intake.id
        assert intake.document_id == result.document.id
        assert intake.status is IntakeStatus.ACCEPTED

    def test_a_duplicate_marks_the_intake_as_duplicate(
        self, service: DocumentUploadService, org: Organization, db: Session
    ) -> None:
        service.upload(organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf")

        intake = DocumentIntake(
            organization_id=org.id,
            source=DocumentSource.EMAIL,
            original_filename="a.pdf",
            received_at=datetime.now(UTC),
        )
        db.add(intake)
        db.flush()

        service.upload(
            organization_id=org.id,
            stream=io.BytesIO(PDF),
            original_filename="a.pdf",
            source=DocumentSource.EMAIL,
            intake=intake,
        )
        assert intake.status is IntakeStatus.DUPLICATE


@requires_db
class TestCompensation:
    def test_a_failure_after_writing_removes_the_stored_object(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB eșuează după ce fișierul a fost scris: storage-ul nu rămâne cu gunoi (§75)."""
        service = DocumentUploadService(db, storage)

        from app.services import document_upload

        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("commit picat")

        monkeypatch.setattr(document_upload.DuplicateDetectionService, "find_duplicate", explode)

        with pytest.raises(RuntimeError, match="commit picat"):
            service.upload(
                organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
            )

        db.rollback()
        assert not any(p.is_file() for p in storage.root.rglob("*"))

    def test_a_storage_failure_leaves_no_document(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service = DocumentUploadService(db, storage)
        monkeypatch.setattr(
            storage, "save", lambda *_a, **_k: (_ for _ in ()).throw(StorageError("disc plin"))
        )

        with pytest.raises(StorageError):
            service.upload(
                organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf"
            )

        db.rollback()
        assert db.scalars(select(Document)).all() == []


@requires_db
def test_upload_is_isolated_per_organization(
    service: DocumentUploadService, org: Organization, db: Session
) -> None:
    other = Organization(name="Alt Cabinet SRL")
    db.add(other)
    db.flush()

    mine = service.upload(organization_id=org.id, stream=io.BytesIO(PDF), original_filename="a.pdf")
    theirs = service.upload(
        organization_id=other.id, stream=io.BytesIO(JPEG), original_filename="b.jpg"
    )

    assert mine.document.organization_id == org.id
    assert theirs.document.organization_id == other.id
    # Cheile nu se pot confunda între organizații.
    assert str(org.id) in mine.document.storage_key
    assert str(other.id) in theirs.document.storage_key
    assert uuid.UUID(mine.document.storage_key.split("/")[1]) == org.id
