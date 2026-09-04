"""Preluarea facturilor electronice din SPV (M11).

Ce apără testele de aici este exact ce a cerut cabinetul și exact ce poate merge
prost la o integrare care rulează nesupravegheată, noaptea:

- **cele trei fișiere** ale unei facturi ajung toate, pe **un singur** document:
  XML-ul, arhiva ZIP cu sigiliul ANAF și PDF-ul oficial;
- factura ajunge la clientul potrivit, pentru că interogarea s-a făcut pe CUI-ul
  lui — aici atribuirea nu se ghicește;
- **nu intră de două ori**, oricâte tururi ar rula;
- o factură stricată sau un mesaj care nu conține o factură **nu opresc** restul;
- când ANAF cade, nu se pierde nimic: fereastra nu se închide, iar turul următor
  reia de unde a rămas;
- când **doar convertorul** cade, factura și dovada ei rămân salvate — PDF-ul se
  poate reface, ele nu.

Toate facturile sunt sintetice (§70). ANAF nu este chemat niciodată —
`FakeAnafClient` ține locul lui prin protocolul din `app/services/anaf/base.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt
from app.domain.enums import DocumentSource, EFacturaMessageKind, IntakeStatus
from app.models.anaf import AnafConnection, AnafMandate
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import (
    VERSION_ANAF_PDF,
    VERSION_ANAF_ZIP,
    VERSION_ORIGINAL,
    Document,
    DocumentIntake,
    DocumentProcessingJob,
    DocumentVersion,
)
from app.models.organization import Organization
from app.services.anaf.sync import PDF_MISSING, AnafSyncService
from app.services.storage.local import LocalStorageProvider
from tests.anaf_fake import VALID_REFRESH, FakeAnafClient, anaf_zip, invoice_xml, message
from tests.conftest import requires_db

pytestmark = requires_db

TAX_ID = "10000101"


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id=f"RO{TAX_ID}")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def anaf() -> FakeAnafClient:
    return FakeAnafClient()


@pytest.fixture
def connection(db: Session, org: Organization) -> AnafConnection:
    row = AnafConnection(
        organization_id=org.id,
        environment="test",
        refresh_token=encrypt(VALID_REFRESH),
        certificate_holder="Certificat cabinet",
        connected_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def mandate(
    db: Session, org: Organization, connection: AnafConnection, client_row: Client
) -> AnafMandate:
    row = AnafMandate(
        organization_id=org.id,
        connection_id=connection.id,
        client_id=client_row.id,
        tax_id=TAX_ID,
    )
    db.add(row)
    db.flush()
    return row


def sync(db: Session, storage: LocalStorageProvider, anaf: FakeAnafClient, org: Organization):
    return AnafSyncService(db, storage, anaf).sync_organization(org.id)


def documents(db: Session, org: Organization) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.organization_id == org.id).order_by(Document.created_at)
        )
    )


def versions(db: Session, document: Document) -> dict[str, DocumentVersion]:
    rows = db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id)
    ).all()
    return {row.kind: row for row in rows}


# ── Cele trei fișiere ────────────────────────────────────────────────────────


class TestTheThreeFiles:
    def test_an_invoice_becomes_one_document_with_three_files(
        self, db, org, storage, anaf, mandate
    ) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        result = sync(db, storage, anaf, org)

        assert result.ingested == 1
        # Un contabil vede o factură, nu trei documente.
        assert len(documents(db, org)) == 1
        files = versions(db, documents(db, org)[0])
        assert set(files) == {VERSION_ORIGINAL, VERSION_ANAF_ZIP, VERSION_ANAF_PDF}

    def test_the_document_itself_is_the_xml(self, db, org, storage, anaf, mandate) -> None:
        """XML-ul este documentul fiscal și tot el este ce citește extracția."""
        original = invoice_xml(number="FCT 118")
        anaf.put_invoice("3001", tax_id=TAX_ID, invoice=original)

        sync(db, storage, anaf, org)
        document = documents(db, org)[0]

        assert document.mime_type in {"application/xml", "text/xml"}
        with storage.open(document.storage_key) as handle:
            assert handle.read() == original

    def test_the_archive_is_stored_byte_for_byte(self, db, org, storage, anaf, mandate) -> None:
        """Arhiva este dovada acceptării: rescrisă, ar înceta să mai fie una."""
        payload = anaf_zip("3001", invoice=invoice_xml())
        anaf.put_invoice("3001", tax_id=TAX_ID, archive=payload)

        sync(db, storage, anaf, org)
        seal = versions(db, documents(db, org)[0])[VERSION_ANAF_ZIP]

        assert seal.mime_type == "application/zip"
        with storage.open(seal.storage_key) as handle:
            assert handle.read() == payload

    def test_the_official_pdf_is_stored_too(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        rendered = versions(db, documents(db, org)[0])[VERSION_ANAF_PDF]

        assert rendered.mime_type == "application/pdf"
        with storage.open(rendered.storage_key) as handle:
            assert handle.read().startswith(b"%PDF")

    def test_each_file_has_its_own_version_number(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        numbers = sorted(v.version_number for v in versions(db, documents(db, org)[0]).values())

        assert numbers == [1, 2, 3]


# ── Al cui este documentul ───────────────────────────────────────────────────


class TestWhoTheInvoiceBelongsTo:
    def test_the_mandate_says_whose_invoice_it_is(
        self, db, org, storage, anaf, mandate, client_row
    ) -> None:
        """Singura sursă în care atribuirea nu poate greși: am întrebat pe CUI-ul lui."""
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)

        assert documents(db, org)[0].client_id == client_row.id

    def test_the_source_says_where_it_came_from(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)

        assert documents(db, org)[0].source is DocumentSource.EFACTURA

    def test_invoices_issued_by_the_client_come_too(self, db, org, storage, anaf, mandate) -> None:
        """Aceeași factură există la ambele părți; direcția schimbă înregistrarea."""
        anaf.put_invoice("3001", tax_id=TAX_ID, kind=EFacturaMessageKind.RECEIVED)
        anaf.put_invoice("3002", tax_id=TAX_ID, kind=EFacturaMessageKind.SENT)

        sync(db, storage, anaf, org)
        intakes = db.scalars(select(DocumentIntake).order_by(DocumentIntake.subject)).all()

        assert {i.raw_payload["kind"] for i in intakes} == {"FACTURA PRIMITA", "FACTURA TRIMISA"}

    def test_notifications_are_not_documents(self, db, org, storage, anaf, mandate) -> None:
        """`MESAJ` și `ERORI FACTURA` privesc trimiterea, pe care nu o facem."""
        anaf.put_message(message("9001", kind=EFacturaMessageKind.MESSAGE, tax_id=TAX_ID))
        anaf.put_message(message("9002", kind=EFacturaMessageKind.ERRORS, tax_id=TAX_ID))

        result = sync(db, storage, anaf, org)

        assert result.ingested == 0
        # Nici măcar nu s-au descărcat: ANAF numără cererile.
        assert anaf.downloaded == []


# ── Idempotență ──────────────────────────────────────────────────────────────


class TestNothingEntersTwice:
    def test_two_runs_leave_one_document(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        # Fereastra se redeschide: altfel al doilea tur nu ar mai vedea factura,
        # iar testul ar trece fără să atingă idempotența. Cazul este real —
        # exact asta se întâmplă când o pagină rămâne necitită.
        mandate.synced_through = None
        db.flush()
        sync(db, storage, anaf, org)

        assert len(documents(db, org)) == 1

    def test_an_invoice_already_taken_is_not_downloaded_again(
        self, db, org, storage, anaf, mandate
    ) -> None:
        """Se întreabă înainte de descărcare: ANAF numără cererile pe zi."""
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        mandate.synced_through = None  # ca fereastra să acopere iar aceeași factură
        db.flush()
        sync(db, storage, anaf, org)

        assert anaf.downloaded == ["3001"]


# ── Ce merge prost ───────────────────────────────────────────────────────────


class TestFailuresStayLocal:
    def test_a_message_without_an_invoice_does_not_stop_the_rest(
        self, db, org, storage, anaf, mandate
    ) -> None:
        """Cazul real: factura a fost respinsă, iar arhiva poartă raportul de erori."""
        anaf.put_invoice(
            "3001",
            tax_id=TAX_ID,
            archive=anaf_zip(
                "3001",
                invoice=None,
                with_signature=False,
                extra={"3001.xml": b'<?xml version="1.0"?><Erori/>'},
            ),
        )
        anaf.put_invoice("3002", tax_id=TAX_ID)

        result = sync(db, storage, anaf, org)

        assert result.ingested == 1
        assert result.failed == 1
        rejected = db.scalars(
            select(DocumentIntake).where(DocumentIntake.status == IntakeStatus.REJECTED)
        ).one()
        assert "nu conține o factură" in (rejected.rejection_reason or "")

    def test_a_missing_mandate_is_reported_on_the_client_row(
        self, db, org, storage, anaf, mandate
    ) -> None:
        anaf.without_mandate.add(TAX_ID)

        sync(db, storage, anaf, org)

        assert mandate.last_error is not None
        # Mesajul spune ce are de făcut clientul, nu doar că a eșuat ceva.
        assert "formular 150" in mandate.last_error

    def test_one_client_without_a_mandate_does_not_block_another(
        self, db, org, storage, anaf, connection, mandate, client_row
    ) -> None:
        other = Client(organization_id=org.id, name="Beta Prod SRL", tax_id="RO20000202")
        db.add(other)
        db.flush()
        db.add(
            AnafMandate(
                organization_id=org.id,
                connection_id=connection.id,
                client_id=other.id,
                tax_id="20000202",
            )
        )
        db.flush()
        anaf.without_mandate.add(TAX_ID)
        anaf.put_invoice("3002", tax_id="20000202")

        result = sync(db, storage, anaf, org)

        assert result.ingested == 1
        assert documents(db, org)[0].client_id == other.id

    def test_anaf_being_down_leaves_the_window_open(self, db, org, storage, anaf, mandate) -> None:
        """Fereastra închisă pe o eroare ar pierde tăcut facturile necitite."""
        anaf.listing_fails = True

        sync(db, storage, anaf, org)

        assert mandate.synced_through is None


class TestTheConverterIsTheOnlyThingThatCanBeRedone:
    def test_the_invoice_and_the_proof_survive_a_dead_converter(
        self, db, org, storage, anaf, mandate
    ) -> None:
        anaf.converter_down = True
        anaf.put_invoice("3001", tax_id=TAX_ID)

        result = sync(db, storage, anaf, org)

        assert result.ingested == 1
        files = versions(db, documents(db, org)[0])
        assert VERSION_ANAF_ZIP in files
        assert VERSION_ANAF_PDF not in files

    def test_the_pdf_is_picked_up_on_the_next_run(self, db, org, storage, anaf, mandate) -> None:
        """Altfel o oră proastă a ANAF ar lăsa facturile fără PDF pentru totdeauna.

        Reprocesarea nu ajută: ea cheamă extracția, care citește XML-ul deja
        stocat, nu convertorul ANAF. Dacă turul nu reia, nimic nu reia.
        """
        anaf.converter_down = True
        anaf.put_invoice("3001", tax_id=TAX_ID)
        sync(db, storage, anaf, org)
        assert VERSION_ANAF_PDF not in versions(db, documents(db, org)[0])

        anaf.converter_down = False
        sync(db, storage, anaf, org)

        document = documents(db, org)[0]
        assert VERSION_ANAF_PDF in versions(db, document)
        # Nota dispare odată cu motivul ei: altfel ar rămâne o avertizare despre
        # ceva ce s-a rezolvat, iar operatorul ar învăța să ignore avertizările.
        assert PDF_MISSING not in document.validation_issues

    def test_the_retry_does_not_need_the_certificate(
        self, db, org, storage, anaf, connection, mandate
    ) -> None:
        """Convertorul este public: reluarea merge și când autorizarea a expirat."""
        anaf.converter_down = True
        anaf.put_invoice("3001", tax_id=TAX_ID)
        sync(db, storage, anaf, org)

        anaf.converter_down = False
        # Certificatul retras: listarea eșuează, dar conversia nu o cere.
        anaf.revoked = True
        sync(db, storage, anaf, org)

        assert VERSION_ANAF_PDF in versions(db, documents(db, org)[0])

    def test_the_missing_pdf_is_visible_to_a_person(self, db, org, storage, anaf, mandate) -> None:
        """Nu doar în log: cineva trebuie să afle că lipsește forma tipăribilă."""
        anaf.converter_down = True
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        document = documents(db, org)[0]

        assert PDF_MISSING in document.validation_issues
        assert document.review_required is True


# ── Fereastra de timp ────────────────────────────────────────────────────────


class TestTheTimeWindow:
    def test_a_finished_window_closes(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)

        assert mandate.synced_through is not None

    def test_a_window_with_more_pages_stays_open(self, db, org, storage, anaf, mandate) -> None:
        """Închisă la jumătate, restul paginilor nu s-ar mai citi niciodată."""
        anaf.has_more = True
        anaf.put_invoice("3001", tax_id=TAX_ID)

        result = sync(db, storage, anaf, org)

        assert result.has_more is True
        assert mandate.synced_through is None

    def test_the_next_window_overlaps_the_closed_one(self, db, org, storage, anaf, mandate) -> None:
        """Un mesaj apărut chiar în secunda închiderii nu are voie să cadă între ferestre."""
        service = AnafSyncService(db, storage, anaf)
        closed_at = datetime.now(UTC) - timedelta(hours=1)
        mandate.synced_through = closed_at

        start, _ = service._window(mandate)

        assert start < closed_at


# ── Legături cu restul sistemului ────────────────────────────────────────────


class TestItJoinsTheNormalFlow:
    def test_the_invoice_is_queued_for_extraction(self, db, org, storage, anaf, mandate) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        jobs = db.scalars(select(DocumentProcessingJob)).all()

        assert len(jobs) == 1

    def test_the_audit_says_the_system_did_it(self, db, org, storage, anaf, mandate) -> None:
        """Auditul trebuie să poată spune „sistemul a făcut asta", nu un om (§33)."""
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)
        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "DOCUMENT_INGESTED_FROM_ANAF")
        ).one()

        assert entry.user_id is None
        assert entry.user_name == "Sistem · e-Factura"

    def test_the_connection_records_the_run(
        self, db, org, storage, anaf, mandate, connection
    ) -> None:
        anaf.put_invoice("3001", tax_id=TAX_ID)

        sync(db, storage, anaf, org)

        assert connection.last_sync_at is not None
        assert mandate.invoices_ingested == 1

    def test_an_inactive_mandate_is_not_queried(self, db, org, storage, anaf, mandate) -> None:
        mandate.is_active = False
        db.flush()
        anaf.put_invoice("3001", tax_id=TAX_ID)

        result = sync(db, storage, anaf, org)

        assert result.ingested == 0
        assert anaf.downloaded == []

    def test_without_a_connection_nothing_happens(self, db, org, storage, anaf) -> None:
        assert sync(db, storage, anaf, org).mandates == []

    def test_a_changed_encryption_key_is_reported_on_the_connection(
        self, db, org, storage, anaf, connection, mandate
    ) -> None:
        """Nu este o problemă a vreunui client, ci a instalării."""
        connection.refresh_token = "ceva-ce-nu-se-poate-descifra"
        db.flush()

        sync(db, storage, anaf, org)

        assert connection.last_error is not None
        assert anaf.downloaded == []
