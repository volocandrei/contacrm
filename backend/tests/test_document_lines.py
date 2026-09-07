"""Liniile facturii, de la XML până pe fișa documentului (§9, §10).

**Ce cere cabinetul.** „TVA-ul pe fiecare produs sau serviciu, și descrierea lui."
Nu este un moft de afișare: pe aceeași factură pot sta 21% pentru un produs, 11%
pentru altul și 0% pentru un serviciu scutit, iar decontul le cere separat. Din
totalul documentului defalcarea nu se poate reconstitui.

**De unde vin.** Doar din facturi electronice, unde fiecare valoare stă într-un
element cu nume. Din PDF nu se citesc și nu se ghicesc: o linie inventată intră
direct în decontul de TVA, iar acolo greșeala se plătește.

Testele urmăresc drumul întreg — fișier încărcat, procesat, citit prin API —
fiindcă fiecare bucată a lui a funcționat deja separat și tot nu ajungea nimic pe
ecran.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentLine
from app.models.organization import Organization
from app.models.user import User
from app.services.document_processing import DocumentProcessingService
from app.services.extraction.base import ExtractedLine, ExtractionResult
from app.services.extraction.efactura import EFacturaExtractionProvider
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

UBL = (
    'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
)


def invoice_with_three_rates(number: str) -> bytes:
    """O factură reală ca formă: trei cote pe același document."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Invoice {UBL}>'
        f"<cbc:ID>{number}</cbc:ID>"
        "<cbc:IssueDate>2026-08-14</cbc:IssueDate>"
        "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>"
        "<cbc:DocumentCurrencyCode>RON</cbc:DocumentCurrencyCode>"
        "<cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity>"
        "<cbc:RegistrationName>Tert Furnizor SRL</cbc:RegistrationName>"
        "<cbc:CompanyID>RO99887766</cbc:CompanyID>"
        "</cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>"
        '<cac:TaxTotal><cbc:TaxAmount currencyID="RON">237.50</cbc:TaxAmount></cac:TaxTotal>'
        "<cac:LegalMonetaryTotal>"
        '<cbc:TaxExclusiveAmount currencyID="RON">1550.00</cbc:TaxExclusiveAmount>'
        '<cbc:TaxInclusiveAmount currencyID="RON">1787.50</cbc:TaxInclusiveAmount>'
        "</cac:LegalMonetaryTotal>"
        "<cac:InvoiceLine><cbc:ID>1</cbc:ID>"
        '<cbc:InvoicedQuantity unitCode="H87">2</cbc:InvoicedQuantity>'
        '<cbc:LineExtensionAmount currencyID="RON">1000.00</cbc:LineExtensionAmount>'
        "<cac:Item><cbc:Name>Monitor 24 inch</cbc:Name><cac:ClassifiedTaxCategory>"
        "<cbc:ID>S</cbc:ID><cbc:Percent>21</cbc:Percent>"
        "</cac:ClassifiedTaxCategory></cac:Item>"
        '<cac:Price><cbc:PriceAmount currencyID="RON">500.00</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
        "<cac:InvoiceLine><cbc:ID>2</cbc:ID>"
        '<cbc:InvoicedQuantity unitCode="H87">10</cbc:InvoicedQuantity>'
        '<cbc:LineExtensionAmount currencyID="RON">250.00</cbc:LineExtensionAmount>'
        "<cac:Item><cbc:Name>Manual tiparit</cbc:Name><cac:ClassifiedTaxCategory>"
        "<cbc:ID>S</cbc:ID><cbc:Percent>11</cbc:Percent>"
        "</cac:ClassifiedTaxCategory></cac:Item>"
        '<cac:Price><cbc:PriceAmount currencyID="RON">25.00</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
        "<cac:InvoiceLine><cbc:ID>3</cbc:ID>"
        '<cbc:InvoicedQuantity unitCode="HUR">1.5</cbc:InvoicedQuantity>'
        '<cbc:LineExtensionAmount currencyID="RON">300.00</cbc:LineExtensionAmount>'
        "<cac:Item><cbc:Name>Consultanta</cbc:Name><cac:ClassifiedTaxCategory>"
        "<cbc:ID>AE</cbc:ID><cbc:Percent>0</cbc:Percent>"
        "</cac:ClassifiedTaxCategory></cac:Item>"
        '<cac:Price><cbc:PriceAmount currencyID="RON">200.00</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
        "</Invoice>"
    ).encode()


def processor(db: Session, storage: LocalStorageProvider) -> DocumentProcessingService:
    """Procesarea, cu providerul de facturi electronice."""
    return DocumentProcessingService(db, storage, EFacturaExtractionProvider())


@pytest.fixture
def processed(
    api_storage: TestClient,
    db: Session,
    admin: User,
    storage_provider: LocalStorageProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> Document:
    """O factură electronică urcată și procesată, ca în producție.

    Se folosește providerul `efactura` **adevărat**, nu unul simulat: altfel
    testul ar verifica doar că știm să scriem într-un tabel, nu că liniile chiar
    se citesc din XML-ul pe care îl trimite ANAF.
    """
    login(api_storage, admin.email)

    answer = api_storage.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "factura.xml",
                io.BytesIO(invoice_with_three_rates(f"FCT {uuid.uuid4().int % 10000}")),
                "application/xml",
            )
        },
    )
    assert answer.status_code == 201, answer.text
    document_id = uuid.UUID(answer.json()["id"])

    processor(db, storage_provider).process(admin.organization_id, document_id)
    db.flush()
    document = db.get(Document, document_id)
    assert document is not None
    return document


class TestFromTheFileToTheDatabase:
    def test_the_three_rates_are_stored_as_three_lines(self, processed: Document) -> None:
        """Motivul întreg al funcției, într-o singură asertiune."""
        assert [line.vat_rate for line in processed.lines] == [
            Decimal("21"),
            Decimal("11"),
            Decimal("0"),
        ]

    def test_every_column_the_accountant_asked_for_is_there(self, processed: Document) -> None:
        first = processed.lines[0]

        assert first.position == 1
        assert first.number == "1"
        assert first.description == "Monitor 24 inch"
        assert first.quantity == Decimal("2")
        assert first.unit_code == "H87"
        assert first.unit_price == Decimal("500")
        assert first.net_amount == Decimal("1000.00")
        assert first.vat_rate == Decimal("21")
        assert first.vat_category == "S"

    def test_a_fractional_quantity_survives_the_database(self, processed: Document) -> None:
        """`Numeric(18, 4)`: o oră și jumătate nu devine două ore."""
        assert processed.lines[2].quantity == Decimal("1.5")

    def test_what_the_document_does_not_say_stays_empty(self, processed: Document) -> None:
        """XML-ul nu declară TVA pe linie. Nu îl calculăm noi.

        S-ar putea: baza inmultita cu cota. Dar un număr calculat de noi, pus lângă unul citit
        de pe factură, arată identic pe ecran — iar contabilul nu ar avea cum să le
        deosebească. Ce lipsește din document lipsește și din registru.
        """
        assert all(line.vat_amount is None for line in processed.lines)
        assert all(line.gross_amount is None for line in processed.lines)

    def test_the_order_is_the_one_from_the_document(self, processed: Document) -> None:
        assert [line.position for line in processed.lines] == [1, 2, 3]


class TestReprocessing:
    def test_processing_twice_does_not_double_the_vat_base(
        self, processed: Document, db: Session, storage_provider: LocalStorageProvider
    ) -> None:
        """Cea mai scumpă greșeală posibilă aici, și nu s-ar fi văzut pe ecran.

        Adăugate în loc de înlocuite, liniile ar fi dublat baza de TVA a lunii la
        fiecare reîncercare. Fișa documentului ar fi arătat șase rânduri — vizibil
        — dar un raport pe cote ar fi arătat doar niște numere de două ori mai mari.
        """
        before = len(processed.lines)
        assert before == 3

        processor(db, storage_provider).process(processed.organization_id, processed.id)
        db.flush()
        db.refresh(processed)

        after = db.scalars(
            select(DocumentLine).where(DocumentLine.document_id == processed.id)
        ).all()
        assert len(after) == 3

    def test_a_provider_without_lines_does_not_erase_the_ones_we_have(
        self, processed: Document, db: Session, storage_provider: LocalStorageProvider
    ) -> None:
        """`pdf_text` și `mock` nu citesc linii. Asta nu înseamnă „șterge-le".

        Altfel o reprocesare cu alt provider ar pierde tăcut singurele date de
        încredere pe care le avem despre defalcarea TVA-ului.
        """
        service = processor(db, storage_provider)
        service._apply_lines(processed, ())
        db.flush()

        # Numărat **din bază**, nu din colecția sesiunii: un `session.delete` se
        # vede în colecție abia după expirare, deci o verificare pe obiectul din
        # memorie ar fi trecut și dacă rândurile chiar dispăreau.
        remaining = db.scalars(
            select(DocumentLine).where(DocumentLine.document_id == processed.id)
        ).all()
        assert len(remaining) == 3


class TestOnTheScreen:
    def test_the_document_detail_returns_the_lines(
        self, api_storage: TestClient, processed: Document
    ) -> None:
        """Ultima bucată a drumului: ce ajunge efectiv în interfață."""
        answer = api_storage.get(f"/api/v1/documents/{processed.id}")

        assert answer.status_code == 200, answer.text
        lines = answer.json()["lines"]
        # Cota iese ca "21", nu "21.00": stă lângă semnul procent pe ecran, nu
        # într-un total. Sumele rămân cu două zecimale — vezi `net_amount` mai jos.
        assert [line["vatRate"] for line in lines] == ["21", "11", "0"]
        assert lines[0]["netAmount"] == "1000.00"
        assert lines[0]["description"] == "Monitor 24 inch"
        assert lines[2]["vatCategory"] == "AE"

    def test_a_document_without_lines_answers_with_an_empty_list(
        self, api_storage: TestClient, db: Session, admin: User, org: Organization
    ) -> None:
        """Un PDF nu are linii, și asta nu este o eroare — este cazul obișnuit."""
        login(api_storage, admin.email)
        answer = api_storage.post(
            "/api/v1/documents/upload",
            files={
                "file": ("factura.pdf", b"%PDF-1.7\n" + b"0" * 600 + b"\n%%EOF", "application/pdf")
            },
        )
        assert answer.status_code == 201, answer.text

        detail = api_storage.get(f"/api/v1/documents/{answer.json()['id']}")

        assert detail.status_code == 200
        assert detail.json()["lines"] == []


class TestTheContract:
    def test_the_extraction_result_carries_lines_but_no_confidence(self) -> None:
        """O linie nu are „80% sigur": ori scrie în XML, ori nu.

        Ziua în care un provider va ghici linii dintr-un PDF, va trebui întâi să
        știe să spună cât de sigur este — iar tipul de aici o va cere.
        """
        line = ExtractedLine(description="Ceva", vat_rate="19")

        assert not hasattr(line, "confidence")
        assert ExtractionResult(provider="x", duration_ms=1).lines == ()
