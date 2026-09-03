"""Providerul care citește facturi electronice, prin protocolul de extracție.

`test_efactura.py` verifică regulile de citire; aici se verifică **contractul**:
ce ajunge în `ExtractionResult` și cum. Trei lucruri contează:

1. Proveniența fiecărei valori este `OCR` — citit de pe document — cu încredere
   întreagă. Într-un document structurat nu există „80% sigur": elementul e acolo
   sau nu e. Un badge „AI 80%" pe o valoare pe care niciun model nu a produs-o
   este exact minciuna pe care ecranul de verificare promite să nu o spună.
2. Providerul **nu** decide direcția facturii. Știe cine e furnizorul și cine
   cumpărătorul, dar nu știe pentru cine lucrează cabinetul.
3. Ce nu este XML trece mai departe fără eroare: o poză nu e un document greșit.

Toate facturile sunt inventate (§70).
"""

from __future__ import annotations

import io

import pytest

from app.domain.enums import FieldSource
from app.services.extraction.base import ExtractionError, ExtractionInput
from app.services.extraction.efactura import FIELDS, EFacturaExtractionProvider
from app.services.extraction.local import LocalExtractionProvider
from tests.test_efactura import COMPLETE

TYPES = frozenset({"FACTURA_INTRARE", "FACTURA_IESIRE", "BON_FISCAL"})


def source(content: bytes, *, mime_type: str = "application/xml") -> ExtractionInput:
    return ExtractionInput(
        stream=io.BytesIO(content),
        mime_type=mime_type,
        original_filename="factura.xml",
        sha256="a" * 64,
    )


@pytest.fixture
def provider() -> EFacturaExtractionProvider:
    return EFacturaExtractionProvider(known_type_codes=TYPES)


class TestWhatItReads:
    def test_the_fields_come_out_as_the_screen_expects_them(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        result = provider.extract(source(COMPLETE))
        values = {name: field.value for name, field in result.fields.items()}

        assert values["documentDate"] == "2026-08-14"
        assert values["series"] == "FCT"
        assert values["documentNumber"] == "7001"
        assert values["supplierName"] == "Tert Furnizor SRL"
        assert values["supplierTaxId"] == "RO99887766"
        assert values["customerName"] == "Alfa Conta SRL"
        assert values["customerTaxId"] == "RO10000101"
        assert values["currency"] == "RON"
        assert values["subtotal"] == "1000.00"
        assert values["vatAmount"] == "190.00"
        assert values["totalAmount"] == "1190.00"

    def test_every_expected_field_is_reported(self, provider: EFacturaExtractionProvider) -> None:
        """`EMPTY` spune „am căutat și nu am găsit"; absența ar spune „nici nu am încercat"."""
        assert set(provider.extract(source(COMPLETE)).fields) == set(FIELDS)

    def test_a_value_read_from_a_named_field_is_certain(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        total = provider.extract(source(COMPLETE)).fields["totalAmount"]

        assert total.source is FieldSource.OCR
        assert total.confidence == 1.0

    def test_a_missing_field_is_empty_not_guessed(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        """O factură validă, dar goală: nimic nu se completează din context."""
        empty = (
            b'<?xml version="1.0"?>'
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>'
        )
        result = provider.extract(source(empty))

        assert all(field.source is FieldSource.EMPTY for field in result.fields.values())
        assert all(field.value is None for field in result.fields.values())

    def test_the_accounting_month_is_not_the_documents_business(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        """Luna contabilă o derivă sistemul din dată (ADR-008), nu documentul."""
        assert provider.extract(source(COMPLETE)).fields["referenceMonth"].value is None


class TestWhatItRefusesToDecide:
    def test_the_direction_is_left_open(self, provider: EFacturaExtractionProvider) -> None:
        """Un cititor de XML nu are de unde să știe pentru cine lucrează cabinetul."""
        result = provider.extract(source(COMPLETE))

        assert result.document_type_code is None
        assert set(result.document_type_candidates) == {"FACTURA_INTRARE", "FACTURA_IESIRE"}

    def test_nothing_is_proposed_without_both_codes_configured(self) -> None:
        """Altfel rezolvarea de mai târziu ar alege un cod pe care scrierea îl refuză."""
        narrow = EFacturaExtractionProvider(known_type_codes=frozenset({"FACTURA_INTRARE"}))
        assert narrow.extract(source(COMPLETE)).document_type_candidates == ()

    def test_a_credit_note_is_not_offered_as_an_ordinary_invoice(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        """Un storno are semn invers; trecut drept factură, ar dubla suma în registru."""
        storno = COMPLETE.replace(
            b"<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
            b"<cbc:InvoiceTypeCode>381</cbc:InvoiceTypeCode>",
        )
        assert provider.extract(source(storno)).document_type_candidates == ()


class TestWhatItCannotRead:
    def test_a_pdf_passes_through_without_an_error(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        """Nu e documentul lui. Nu este o eroare, ci o limită — și se spune."""
        result = provider.extract(source(b"%PDF-1.4", mime_type="application/pdf"))

        assert all(field.source is FieldSource.EMPTY for field in result.fields.values())
        assert result.ocr_confidence is None

    def test_an_xml_that_is_not_an_invoice_is_an_error(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        """A trecut de validarea de tip la încărcare, deci ar fi trebuit să fie una."""
        with pytest.raises(ExtractionError) as caught:
            provider.extract(source(b'<?xml version="1.0"?><configurare/>'))

        # Aceiași octeți la a doua încercare: reluarea nu ar schimba nimic.
        assert caught.value.retryable is False


class TestTheReadableRendering:
    def test_the_summary_takes_the_place_of_the_facsimile(
        self, provider: EFacturaExtractionProvider
    ) -> None:
        text = provider.extract(source(COMPLETE)).ocr_text or ""

        assert "Tert Furnizor SRL" in text
        assert "1190.00" in text


class TestTheLocalReader:
    """Cabinetul primește în aceeași zi XML-uri și PDF-uri; alegerea e a conținutului."""

    def test_an_xml_goes_to_the_invoice_reader(self) -> None:
        result = LocalExtractionProvider(known_type_codes=TYPES).extract(source(COMPLETE))

        assert result.provider == "efactura"
        assert result.fields["totalAmount"].value == "1190.00"

    def test_anything_else_goes_to_the_pdf_reader(self) -> None:
        """O imagine ajunge la cititorul de PDF, care raportează cinstit că n-are text."""
        result = LocalExtractionProvider(known_type_codes=TYPES).extract(
            source(b"\xff\xd8\xff", mime_type="image/jpeg")
        )

        assert result.provider == "pdf_text"
        assert all(field.source is FieldSource.EMPTY for field in result.fields.values())

    def test_the_reader_that_answered_is_named(self) -> None:
        """În audit și în interfață trebuie să se vadă cine a citit, nu un „local" generic."""
        assert LocalExtractionProvider().name == "local"
