"""XML-ul și PDF-ul aceleiași facturi, prin API și prin procesare (§16, §17).

Regulile de potrivire au testul lor, pur, în `test_efactura_pairing.py`. Aici se
verifică ce se întâmplă cu **documentele**:

1. **Legătura se face singură** la procesare, pe identitate exactă — și este
   reciprocă: fiecare exemplar știe unde este celălalt.
2. **Nimic nu se aruncă.** Amândouă rămân, fiecare cu fișierul lui: XML-ul este
   originalul fiscal, PDF-ul este ce se poate privi.
3. **Conflictul nu se leagă.** Sume diferite pe aceeași identitate înseamnă că una
   este citită greșit; legarea lor ar fi ascuns exact asta.
4. **Reversibil**, și izolat între cabinete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import User
from app.services.efactura_pairing import PairingService
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


def invoice(
    db: Session,
    org: Organization,
    client_row: Client,
    types: dict[str, DocumentType],
    *,
    electronic: bool,
    number: str = "7001",
    total: str = "1190.00",
    tax_id: str | None = "RO99887766",
) -> Document:
    """Un exemplar al facturii: XML sau PDF, cu aceleași date de identitate."""
    document = Document(
        organization_id=org.id,
        client_id=client_row.id,
        document_type_id=types["FACTURA_INTRARE"].id,
        status=DocumentStatus.REVIEW_REQUIRED,
        source=DocumentSource.EFACTURA if electronic else DocumentSource.UPLOAD,
        original_filename="factura.xml" if electronic else "factura.pdf",
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/xml" if electronic else "application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        document_date=date(2026, 8, 14),
        reference_month="2026-08",
        series="FCT",
        document_number=number,
        supplier_name="Terț Furnizor SRL",
        supplier_tax_id=tax_id,
        total_amount=Decimal(total),
        currency="RON",
    )
    db.add(document)
    db.flush()
    return document


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> None:
    login(api, admin.email)


@pytest.mark.usefixtures("as_admin")
class TestAutomaticPairing:
    def test_the_xml_and_the_pdf_find_each_other(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Rostul întreg: XML-ul din SPV și PDF-ul de pe email, legate singure."""
        pdf = invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)

        paired = PairingService(db, org.id).pair_automatically(xml)
        db.flush()

        assert paired is not None
        assert paired.id == pdf.id
        # Reciprocă: fiecare exemplar știe unde este celălalt.
        assert xml.paired_with_id == pdf.id
        assert pdf.paired_with_id == xml.id
        assert xml.paired_automatically is True

    def test_the_reasons_are_written_on_both(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Cine se uită peste o lună trebuie să poată verifica, nu doar să creadă."""
        invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)

        PairingService(db, org.id).pair_automatically(xml)
        db.flush()

        assert "CUI furnizor identic" in (xml.pairing_reasons or "")
        assert "aceeași sumă" in (xml.pairing_reasons or "")

    def test_neither_document_is_thrown_away(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Nu este o detecție de duplicate: amândouă rămân, cu fișierele lor."""
        pdf = invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)

        PairingService(db, org.id).pair_automatically(xml)
        db.flush()

        assert pdf.deleted_at is None and xml.deleted_at is None
        assert pdf.is_duplicate is False and xml.is_duplicate is False
        assert pdf.storage_key != xml.storage_key

    def test_a_conflict_is_not_linked(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Sume diferite: una este citită greșit. Legarea ar fi ascuns tocmai asta."""
        invoice(db, org, client_row, types, electronic=False, total="1900.00")
        xml = invoice(db, org, client_row, types, electronic=True)

        assert PairingService(db, org.id).pair_automatically(xml) is None
        assert xml.paired_with_id is None

    def test_an_incomplete_identity_is_not_linked_either(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Fără CUI pe una dintre ele, decizia rămâne a omului."""
        invoice(db, org, client_row, types, electronic=False, tax_id=None)
        xml = invoice(db, org, client_row, types, electronic=True)

        assert PairingService(db, org.id).pair_automatically(xml) is None

    def test_two_candidates_are_not_linked(
        self,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """A alege unul ar fi o monedă aruncată."""
        invoice(db, org, client_row, types, electronic=False)
        invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)

        assert PairingService(db, org.id).pair_automatically(xml) is None


@pytest.mark.usefixtures("as_admin")
class TestTheScreen:
    def test_the_pairing_route_shows_what_was_linked_and_why(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        pdf = invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)
        PairingService(db, org.id).pair_automatically(xml)
        db.flush()

        answer = api.get(f"/api/v1/documents/{xml.id}/pairing")

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["pairedWithId"] == str(pdf.id)
        assert body["pairedWithFilename"] == "factura.pdf"
        assert body["pairedAutomatically"] is True
        assert "CUI furnizor identic" in body["pairingReasons"]

    def test_candidates_come_with_their_reasons(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Propunerea neconfirmată: se arată, cu motivele ei."""
        invoice(db, org, client_row, types, electronic=False, tax_id=None)
        xml = invoice(db, org, client_row, types, electronic=True)
        db.flush()

        body = api.get(f"/api/v1/documents/{xml.id}/pairing").json()

        assert body["state"] == "PROBABLE"
        assert body["pairedWithId"] is None
        assert len(body["candidates"]) == 1
        assert body["candidates"][0]["reasons"]

    def test_a_conflict_is_visible_on_the_screen(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Cazul care merită cel mai mult atenția, și cel mai ușor de ascuns."""
        invoice(db, org, client_row, types, electronic=False, total="1900.00")
        xml = invoice(db, org, client_row, types, electronic=True)
        db.flush()

        body = api.get(f"/api/v1/documents/{xml.id}/pairing").json()

        assert body["state"] == "CONFLICT"
        assert any("sume diferite" in reason for reason in body["candidates"][0]["reasons"])


@pytest.mark.usefixtures("as_admin")
class TestPairingByHand:
    def test_a_human_can_link_a_probable_candidate(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        pdf = invoice(db, org, client_row, types, electronic=False, tax_id=None)
        xml = invoice(db, org, client_row, types, electronic=True)
        db.flush()

        answer = api.post(f"/api/v1/documents/{xml.id}/pairing", json={"documentId": str(pdf.id)})

        assert answer.status_code == 200, answer.text
        assert answer.json()["pairedWithId"] == str(pdf.id)
        assert answer.json()["pairedAutomatically"] is False

    def test_two_documents_of_the_same_kind_are_refused(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Două PDF-uri cu aceeași identitate sunt un duplicat, nu o pereche."""
        first = invoice(db, org, client_row, types, electronic=False)
        second = invoice(db, org, client_row, types, electronic=False)
        db.flush()

        answer = api.post(
            f"/api/v1/documents/{first.id}/pairing", json={"documentId": str(second.id)}
        )

        assert answer.status_code == 422
        assert "duplicat" in answer.json()["details"]["documentId"][0].lower()

    def test_the_link_can_be_undone(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        pdf = invoice(db, org, client_row, types, electronic=False)
        xml = invoice(db, org, client_row, types, electronic=True)
        PairingService(db, org.id).pair_automatically(xml)
        db.flush()

        answer = api.delete(f"/api/v1/documents/{xml.id}/pairing")

        assert answer.status_code == 200, answer.text
        assert answer.json()["pairedWithId"] is None
        db.flush()
        assert pdf.paired_with_id is None

    def test_another_offices_document_does_not_exist(self, api: TestClient, db: Session) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO777888")
        db.add(other)
        db.flush()
        foreign = Document(
            organization_id=other.id,
            status=DocumentStatus.RECEIVED,
            source=DocumentSource.UPLOAD,
            original_filename="factura.pdf",
            storage_key=f"organizations/{other.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="0" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(foreign)
        db.flush()

        assert api.get(f"/api/v1/documents/{foreign.id}/pairing").status_code == 404
