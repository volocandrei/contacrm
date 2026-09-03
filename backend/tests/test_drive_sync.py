"""Aducerea documentelor din dosarele urmărite (M9).

Ce apără testele de aici este exact ce a cerut cabinetul și exact ce poate merge
prost la o integrare care rulează nesupravegheată, noaptea:

- documentele **intră singure** și ajung la clientul potrivit, pentru că dosarul
  îl spune;
- **nu intră de două ori**, oricâte tururi ar rula;
- un fișier stricat **nu oprește** restul dosarului;
- când Microsoft cade, nu se pierde nimic: turul următor reia de unde a rămas.

Toate fișierele sunt sintetice (§70). Microsoft nu este chemat niciodată —
`FakeDriveClient` ține locul lui prin protocolul din `app/services/drive/base.py`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt
from app.domain.enums import DocumentSource, DocumentStatus, IntakeStatus
from app.models.client import Client
from app.models.document import Document, DocumentIntake, DocumentProcessingJob
from app.models.microsoft import DriveFolder, MicrosoftConnection
from app.models.organization import Organization
from app.services.microsoft.base import DeltaPage
from app.services.microsoft.drive_sync import DriveSyncService
from app.services.storage.local import LocalStorageProvider
from tests.conftest import requires_db
from tests.drive_fake import (
    JPEG,
    NOT_A_DOCUMENT,
    PDF,
    VALID_REFRESH,
    FakeDriveClient,
    file_item,
)

pytestmark = requires_db

FOLDER_ITEM = "folder-alfa"


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO10000101")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def drive() -> FakeDriveClient:
    return FakeDriveClient()


@pytest.fixture
def connection(db: Session, org: Organization) -> MicrosoftConnection:
    from datetime import UTC, datetime

    row = MicrosoftConnection(
        organization_id=org.id,
        provider="microsoft",
        account_email="contabil@cabinet.test",
        refresh_token=encrypt(VALID_REFRESH),
        connected_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def folder(db: Session, org: Organization, connection: MicrosoftConnection, client_row: Client):
    row = DriveFolder(
        organization_id=org.id,
        connection_id=connection.id,
        client_id=client_row.id,
        drive_id="drive-1",
        item_id=FOLDER_ITEM,
        path="/Clienti/Alfa Conta SRL",
    )
    db.add(row)
    db.flush()
    return row


def sync(db: Session, storage: LocalStorageProvider, drive: FakeDriveClient, org: Organization):
    return DriveSyncService(db, storage, drive).sync_organization(org.id)


def documents(db: Session, org: Organization) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.organization_id == org.id)
            .order_by(Document.original_filename)
        )
    )


# ── Ce a cerut cabinetul ─────────────────────────────────────────────────────


class TestDocumentsArriveOnTheirOwn:
    def test_files_from_the_folder_become_documents(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        drive.put_files(
            FOLDER_ITEM,
            [file_item("f1", "12.08 scan.pdf"), file_item("f2", "13.08 scan.pdf")],
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 2
        assert [d.original_filename for d in documents(db, org)] == [
            "12.08 scan.pdf",
            "13.08 scan.pdf",
        ]

    def test_the_folder_says_whose_documents_they_are(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Piesa care rezolvă cererea: nu mai trebuie identificat clientul.

        Mai sigur decât citirea unui CUI: merge și pentru o poză neclară, fără
        text de citit.
        """
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])
        sync(db, storage, drive, org)

        assert documents(db, org)[0].client_id == client_row.id

    def test_an_unmapped_folder_does_not_invent_a_client(
        self, db, org, storage, drive, folder
    ) -> None:
        """Un dosar fără client atribuit nu este o scuză să ghicim unul."""
        folder.client_id = None
        db.flush()
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])

        sync(db, storage, drive, org)

        assert documents(db, org)[0].client_id is None

    def test_the_documents_are_queued_for_processing(self, db, org, storage, drive, folder) -> None:
        """Altfel ar rămâne în `RECEIVED` până le găsește cineva."""
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])
        sync(db, storage, drive, org)

        jobs = db.scalar(select(func.count()).select_from(DocumentProcessingJob))
        assert jobs == 1

    def test_the_name_from_onedrive_is_kept_as_information_only(
        self, db, org, storage, drive, folder
    ) -> None:
        """Numele pus de client rămâne vizibil, dar nu ajunge într-o cale (R3, R7).

        Numele standardizat (§10) se compune abia la arhivare — adică exact munca
        pe care contabilul o făcea manual.
        """
        drive.put_files(FOLDER_ITEM, [file_item("f1", "../../etc/passwd.pdf")])
        sync(db, storage, drive, org)

        document = documents(db, org)[0]
        assert document.original_filename == "../../etc/passwd.pdf"
        assert ".." not in document.storage_key
        assert document.stored_filename is None


# ── Idempotență ──────────────────────────────────────────────────────────────


class TestNothingArrivesTwice:
    def test_a_second_pass_brings_nothing_new(self, db, org, storage, drive, folder) -> None:
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])
        sync(db, storage, drive, org)

        second = sync(db, storage, drive, org)

        assert second.ingested == 0
        assert len(documents(db, org)) == 1

    def test_the_same_file_seen_again_is_not_downloaded(
        self, db, org, storage, drive, folder
    ) -> None:
        """Se întreabă înainte de descărcare: un fișier deja luat nu trece prin rețea."""
        item = file_item("f1", "factura.pdf")
        drive.put_files(FOLDER_ITEM, [item])
        sync(db, storage, drive, org)

        # Tokenul delta s-a pierdut (dosar mutat, reconectare) și Graph îl dă iar.
        drive.put_page(FOLDER_ITEM, DeltaPage(items=(item,), delta_token="delta-2"))
        sync(db, storage, drive, org)

        assert drive.downloaded == ["f1"]

    def test_each_file_leaves_a_trace_of_where_it_came_from(
        self, db, org, storage, drive, folder
    ) -> None:
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])
        sync(db, storage, drive, org)

        intake = db.scalars(select(DocumentIntake)).one()
        assert intake.source is DocumentSource.ONEDRIVE
        assert intake.status is IntakeStatus.ACCEPTED
        assert intake.external_message_id == FOLDER_ITEM
        assert intake.external_attachment_id == "f1"
        assert intake.sender == "contabil@cabinet.test"

    def test_identical_content_is_recognised_as_a_duplicate(
        self, db, org, storage, drive, folder
    ) -> None:
        """Același document, pus de client în două locuri, nu intră de două ori."""
        drive.put_files(
            FOLDER_ITEM,
            [file_item("f1", "factura.pdf"), file_item("f2", "copie factura.pdf")],
        )

        sync(db, storage, drive, org)

        statuses = {d.original_filename: d.status for d in documents(db, org)}
        assert statuses["copie factura.pdf"] is DocumentStatus.DUPLICATE


# ── Ce se întâmplă când ceva merge prost ─────────────────────────────────────


class TestOneBadFileDoesNotStopTheRest:
    def test_a_file_that_is_not_a_document_is_skipped_with_a_reason(
        self, db, org, storage, drive, folder
    ) -> None:
        """Un `.txt` în dosarul clientului nu este o eroare a sistemului."""
        good = file_item("f1", "factura.pdf")
        bad = file_item("f2", "notite.txt")
        drive.put_files(FOLDER_ITEM, [bad, good])
        drive.put_file(bad, NOT_A_DOCUMENT)

        result = sync(db, storage, drive, org)

        assert result.ingested == 1
        rejected = db.scalars(
            select(DocumentIntake).where(DocumentIntake.status == IntakeStatus.REJECTED)
        ).one()
        assert rejected.original_filename == "notite.txt"
        assert rejected.rejection_reason

    def test_a_failed_download_does_not_lose_the_rest(
        self, db, org, storage, drive, folder
    ) -> None:
        missing = file_item("lipsa", "disparut.pdf")
        good = file_item("f1", "factura.pdf")
        # `missing` nu primește conținut: descărcarea lui va eșua.
        drive.put_page(FOLDER_ITEM, DeltaPage(items=(missing, good), delta_token="delta-1"))
        drive.put_file(good)

        result = sync(db, storage, drive, org)

        assert result.ingested == 1
        assert result.failed == 1
        assert [d.original_filename for d in documents(db, org)] == ["factura.pdf"]

    def test_subfolders_are_not_mistaken_for_documents(
        self, db, org, storage, drive, folder
    ) -> None:
        from tests.drive_fake import folder_item

        drive.put_page(
            FOLDER_ITEM,
            DeltaPage(items=(folder_item("sub", "2026"),), delta_token="delta-1"),
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 0
        assert documents(db, org) == []

    def test_a_deleted_file_is_not_brought_back(self, db, org, storage, drive, folder) -> None:
        """Delta raportează și ștergerile. Noi nu ștergem nimic — dar nici nu
        reluăm un fișier pe care clientul l-a scos din dosar."""
        removed = file_item("f-sters", "sters.pdf")
        drive.put_page(
            FOLDER_ITEM,
            DeltaPage(items=(replace(removed, deleted=True),), delta_token="delta-1"),
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 0
        assert drive.downloaded == []


class TestWhenMicrosoftIsUnavailable:
    def test_a_temporary_failure_keeps_the_delta_token(
        self, db, org, storage, drive, folder
    ) -> None:
        """Tokenul păstrat înseamnă că turul următor continuă, nu reia tot."""
        folder.delta_token = "delta-de-ieri"
        db.flush()
        drive.delta_fails.add(FOLDER_ITEM)

        result = sync(db, storage, drive, org)

        assert folder.delta_token == "delta-de-ieri"
        assert result.folders[0].error
        assert folder.last_error

    def test_a_revoked_consent_says_what_to_do(self, db, org, storage, drive, folder) -> None:
        """Un token expirat trebuie să se vadă pe ecran: altfel documentele pur și
        simplu nu mai vin și nimeni nu află de ce."""
        drive.revoked = True

        sync(db, storage, drive, org)

        assert folder.last_error is not None
        assert "reconect" in folder.last_error.lower()

    def test_a_wrong_encryption_key_is_reported_not_crashed(
        self, db, org, storage, drive, folder, connection
    ) -> None:
        """Cheia schimbată este o eroare de instalare, nu una de dosar."""
        connection.refresh_token = "gAAAAABmnu-ceva-ce-nu-se-descifreaza"
        db.flush()

        result = sync(db, storage, drive, org)

        assert result.ingested == 0
        assert connection.last_error is not None
        assert "DRIVE_TOKEN_KEY" in connection.last_error


class TestProgress:
    def test_the_delta_token_advances_after_a_successful_pass(
        self, db, org, storage, drive, folder
    ) -> None:
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")], token="delta-nou")

        sync(db, storage, drive, org)

        assert folder.delta_token == "delta-nou"
        assert folder.last_synced_at is not None
        assert folder.files_ingested == 1

    def test_a_folder_with_history_is_taken_in_batches(
        self, db, org, storage, drive, folder
    ) -> None:
        """La prima conectare, un an de facturi nu blochează coada."""
        first = file_item("f1", "prima.pdf")
        second = file_item("f2", "a-doua.pdf")
        drive.put_file(first)
        drive.put_file(second)
        drive.put_page(FOLDER_ITEM, DeltaPage(items=(first,), delta_token="pag-2", has_more=True))
        drive.put_page(FOLDER_ITEM, DeltaPage(items=(second,), delta_token="delta-final"))

        first_pass = sync(db, storage, drive, org)
        assert first_pass.has_more is True
        assert first_pass.ingested == 1

        second_pass = sync(db, storage, drive, org)
        assert second_pass.has_more is False
        assert len(documents(db, org)) == 2

    def test_an_inactive_folder_is_left_alone(self, db, org, storage, drive, folder) -> None:
        folder.is_active = False
        db.flush()
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])

        assert sync(db, storage, drive, org).ingested == 0
        assert drive.downloaded == []


class TestTheOrganizationBoundary:
    def test_another_organizations_folders_are_not_touched(
        self, db, org, storage, drive, folder
    ) -> None:
        """R10: filtrarea pe organizație stă în interogare, nu după."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        drive.put_files(FOLDER_ITEM, [file_item("f1", "factura.pdf")])

        result = DriveSyncService(db, storage, drive).sync_organization(other.id)

        assert result.ingested == 0
        assert drive.downloaded == []


class TestImages:
    def test_a_photo_is_a_valid_document(self, db, org, storage, drive, folder) -> None:
        """Clienții pun poze de bonuri. Sunt documente, chiar dacă fără text."""
        photo = file_item("f1", "bon.jpg")
        drive.put_page(FOLDER_ITEM, DeltaPage(items=(photo,), delta_token="d"))
        drive.put_file(photo, JPEG)

        sync(db, storage, drive, org)

        assert documents(db, org)[0].mime_type == "image/jpeg"


def test_the_bytes_used_in_these_tests_are_what_they_claim() -> None:
    """Dacă falsul ar produce octeți respinși de validare, testele de mai sus ar
    trece din motivul greșit — sau ar cădea toate deodată, fără să spună de ce."""
    from app.services.files import sniff_mime_type

    assert sniff_mime_type(PDF[:32]) == "application/pdf"
    assert sniff_mime_type(JPEG[:32]) == "image/jpeg"
    assert sniff_mime_type(NOT_A_DOCUMENT[:32]) is None
