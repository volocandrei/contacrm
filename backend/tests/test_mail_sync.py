"""Atașamentele din email devin documente (M10).

Cealaltă jumătate a lui *„ce documente trimit domnii clienți"*: unii le pun în
dosarul lor din OneDrive, ceilalți le trimit pe email.

Diferența pe care o apără testele de aici este **cine dă clientul**. La drive,
dosarul — o mapare făcută o dată. Într-o cutie poștală intră toți clienții
deodată, deci răspunsul trebuie găsit pe mesaj: adresa expeditorului, căutată
printre contactele din CRM.

A doua grijă este ce **nu** este un document: logo-ul din semnătura
expeditorului este tot un atașament. Fără filtru, fiecare email ar produce trei
„documente" pe care cineva ar trebui să le respingă manual — iar o listă plină de
gunoi se citește la fel de prost ca una goală.

Toate adresele și fișierele sunt inventate (§70).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt
from app.domain.enums import DocumentSource, IntakeStatus
from app.models.client import Client, Contact
from app.models.document import Document, DocumentIntake, DocumentProcessingJob
from app.models.microsoft import MailFolder, MicrosoftConnection
from app.models.organization import Organization
from app.services.microsoft.base import MailPage
from app.services.microsoft.mail_sync import MIN_ATTACHMENT_BYTES, MailSyncService
from app.services.storage.local import LocalStorageProvider
from tests.conftest import requires_db
from tests.drive_fake import (
    NOT_A_DOCUMENT,
    VALID_REFRESH,
    FakeDriveClient,
    mail_attachment,
    mail_message,
)

pytestmark = requires_db

FOLDER = "inbox"
ALFA_CONTACT = "ana.popescu@alfa.test"
STRANGER = "cineva@necunoscut.test"


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
    db.add(
        Contact(
            client_id=row.id,
            full_name="Ana Popescu",
            email=ALFA_CONTACT,
            is_active=True,
        )
    )
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
def folder(db: Session, org: Organization, connection: MicrosoftConnection) -> MailFolder:
    row = MailFolder(
        organization_id=org.id,
        connection_id=connection.id,
        folder_id=FOLDER,
        display_name="Documente clienți",
    )
    db.add(row)
    db.flush()
    return row


def sync(db: Session, storage: LocalStorageProvider, drive: FakeDriveClient, org: Organization):
    return MailSyncService(db, storage, drive).sync_organization(org.id)


def documents(db: Session, org: Organization) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.organization_id == org.id)
            .order_by(Document.original_filename)
        )
    )


# ── Expeditorul dă clientul ──────────────────────────────────────────────────


class TestTheSenderIdentifiesTheClient:
    def test_an_attachment_from_a_known_contact_reaches_the_client(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Piesa care rezolvă cererea: nimeni nu descarcă și nimeni nu atribuie."""
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "factura.pdf"),))],
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 1
        assert documents(db, org)[0].client_id == client_row.id

    def test_the_address_is_matched_case_insensitively(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Clientul scrie de pe telefon, cu majuscule. Tot el este."""
        drive.put_messages(
            FOLDER,
            [
                mail_message(
                    "m1",
                    ALFA_CONTACT.upper(),
                    attachments=(mail_attachment("a1", "factura.pdf"),),
                )
            ],
        )

        sync(db, storage, drive, org)

        assert documents(db, org)[0].client_id == client_row.id

    def test_an_unknown_sender_does_not_invent_a_client(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Intră oricum: mai bine la un om decât nicăieri."""
        drive.put_messages(
            FOLDER,
            [mail_message("m1", STRANGER, attachments=(mail_attachment("a1", "ceva.pdf"),))],
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 1
        assert documents(db, org)[0].client_id is None

    def test_an_address_shared_by_two_clients_is_not_guessed(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Un contabil care e contact la două firme: nu putem alege noi."""
        other = Client(organization_id=org.id, name="Beta SRL", tax_id="RO2")
        db.add(other)
        db.flush()
        db.add(
            Contact(
                client_id=other.id,
                full_name="Ana Popescu",
                email=ALFA_CONTACT,
                is_active=True,
            )
        )
        db.flush()
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )

        sync(db, storage, drive, org)

        assert documents(db, org)[0].client_id is None

    def test_an_inactive_contact_no_longer_identifies(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Un angajat plecat nu mai vorbește în numele firmei."""
        contact = db.scalars(select(Contact)).one()
        contact.is_active = False
        db.flush()
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )

        sync(db, storage, drive, org)

        assert documents(db, org)[0].client_id is None

    def test_the_sender_and_subject_are_kept(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Când clientul întreabă „v-a ajuns?", răspunsul trebuie să fie în sistem."""
        drive.put_messages(
            FOLDER,
            [
                mail_message(
                    "m1",
                    ALFA_CONTACT,
                    subject="Facturi august",
                    attachments=(mail_attachment("a1", "factura.pdf"),),
                )
            ],
        )

        sync(db, storage, drive, org)

        intake = db.scalars(select(DocumentIntake)).one()
        assert intake.source is DocumentSource.EMAIL
        assert intake.sender == ALFA_CONTACT
        assert intake.subject == "Facturi august"
        assert intake.recipient == "contabil@cabinet.test"


# ── Ce nu este un document ───────────────────────────────────────────────────


class TestWhatIsNotADocument:
    def test_a_signature_logo_is_skipped(self, db, org, storage, drive, folder) -> None:
        """Marcat `inline` de client: face parte din corpul mesajului, nu e atașat."""
        drive.put_messages(
            FOLDER,
            [
                mail_message(
                    "m1",
                    ALFA_CONTACT,
                    attachments=(mail_attachment("logo", "logo.png", inline=True),),
                )
            ],
        )

        result = sync(db, storage, drive, org)

        assert result.ingested == 0
        assert drive.downloaded == []

    def test_a_tiny_attachment_is_skipped(self, db, org, storage, drive, folder) -> None:
        """Sub prag este aproape sigur o imagine de semnătură, nu o factură."""
        drive.put_messages(
            FOLDER,
            [
                mail_message(
                    "m1",
                    ALFA_CONTACT,
                    attachments=(mail_attachment("mic", "icon.png", size=900),),
                )
            ],
        )

        assert sync(db, storage, drive, org).ingested == 0

    def test_a_real_invoice_is_above_the_threshold(self) -> None:
        """Pragul trebuie să lase să treacă cel mai mic PDF real, cu marjă."""
        assert MIN_ATTACHMENT_BYTES <= 10 * 1024

    def test_a_message_without_attachments_costs_nothing(
        self, db, org, storage, drive, folder
    ) -> None:
        drive.put_messages(FOLDER, [mail_message("m1", ALFA_CONTACT)])

        assert sync(db, storage, drive, org).ingested == 0
        assert drive.downloaded == []

    def test_a_file_that_is_not_a_document_is_rejected_with_a_reason(
        self, db, org, storage, drive, folder
    ) -> None:
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "notite.txt"),))],
        )
        drive.put_attachment("a1", NOT_A_DOCUMENT)

        result = sync(db, storage, drive, org)

        assert result.ingested == 0
        rejected = db.scalars(select(DocumentIntake)).one()
        assert rejected.status is IntakeStatus.REJECTED
        assert rejected.rejection_reason


# ── Idempotență ──────────────────────────────────────────────────────────────


class TestNothingArrivesTwice:
    def test_a_second_pass_brings_nothing_new(self, db, org, storage, drive, folder) -> None:
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )
        sync(db, storage, drive, org)

        assert sync(db, storage, drive, org).ingested == 0
        assert len(documents(db, org)) == 1

    def test_a_message_seen_again_is_not_downloaded(self, db, org, storage, drive, folder) -> None:
        message = mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))
        drive.put_messages(FOLDER, [message])
        sync(db, storage, drive, org)

        # Tokenul delta s-a pierdut și Graph dă mesajul din nou.
        drive.put_mail(FOLDER, MailPage(messages=(message,), delta_token="mail-2"))
        sync(db, storage, drive, org)

        assert drive.downloaded == ["a1"]

    def test_two_attachments_on_one_message_are_two_documents(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        """Un client trimite factura și extrasul în același email."""
        drive.put_messages(
            FOLDER,
            [
                mail_message(
                    "m1",
                    ALFA_CONTACT,
                    attachments=(
                        mail_attachment("a1", "factura.pdf"),
                        mail_attachment("a2", "extras.pdf"),
                    ),
                )
            ],
        )
        # Conținut diferit, altfel al doilea ar fi duplicat pe hash.
        drive.put_attachment("a2", b"%PDF-1.4\n% extras\ntrailer<</Root 1 0 R>>\n%%EOF\n")

        result = sync(db, storage, drive, org)

        assert result.ingested == 2
        assert [d.original_filename for d in documents(db, org)] == ["extras.pdf", "factura.pdf"]


# ── Când ceva merge prost ────────────────────────────────────────────────────


class TestFailures:
    def test_a_failed_download_does_not_lose_the_rest(
        self, db, org, storage, drive, folder
    ) -> None:
        drive.put_mail(
            FOLDER,
            MailPage(
                messages=(
                    mail_message(
                        "m1",
                        ALFA_CONTACT,
                        attachments=(
                            mail_attachment("lipsa", "disparut.pdf"),
                            mail_attachment("a2", "bun.pdf"),
                        ),
                    ),
                ),
                delta_token="mail-1",
            ),
        )
        # Doar al doilea primește conținut.
        drive.put_attachment("a2")

        result = sync(db, storage, drive, org)

        assert result.ingested == 1
        assert result.failed == 1
        assert [d.original_filename for d in documents(db, org)] == ["bun.pdf"]

    def test_a_temporary_failure_keeps_the_delta_token(
        self, db, org, storage, drive, folder
    ) -> None:
        folder.delta_token = "mail-de-ieri"
        db.flush()
        drive.mail_delta_fails.add(FOLDER)

        result = sync(db, storage, drive, org)

        assert folder.delta_token == "mail-de-ieri"
        assert result.folders[0].error
        assert folder.last_error

    def test_a_revoked_consent_says_what_to_do(self, db, org, storage, drive, folder) -> None:
        drive.revoked = True

        sync(db, storage, drive, org)

        assert folder.last_error is not None
        assert "reconect" in folder.last_error.lower()

    def test_an_inactive_folder_is_left_alone(self, db, org, storage, drive, folder) -> None:
        folder.is_active = False
        db.flush()
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )

        assert sync(db, storage, drive, org).ingested == 0
        assert drive.downloaded == []


class TestProgress:
    def test_documents_are_queued_for_processing(
        self, db, org, storage, drive, folder, client_row
    ) -> None:
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )
        sync(db, storage, drive, org)

        assert db.scalar(select(func.count()).select_from(DocumentProcessingJob)) == 1

    def test_the_delta_token_advances(self, db, org, storage, drive, folder) -> None:
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
            token="mail-nou",
        )

        sync(db, storage, drive, org)

        assert folder.delta_token == "mail-nou"
        assert folder.files_ingested == 1
        assert folder.last_synced_at is not None


class TestTheOrganizationBoundary:
    def test_another_organizations_mailbox_is_not_touched(
        self, db, org, storage, drive, folder
    ) -> None:
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        drive.put_messages(
            FOLDER,
            [mail_message("m1", ALFA_CONTACT, attachments=(mail_attachment("a1", "f.pdf"),))],
        )

        result = MailSyncService(db, storage, drive).sync_organization(other.id)

        assert result.ingested == 0
        assert drive.downloaded == []
