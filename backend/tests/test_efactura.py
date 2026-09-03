"""Citirea unei facturi electronice (UBL 2.1 / RO_CIUS).

Aici regula este alta decât la `pdf_text`. Acolo, orice valoare este o
interpretare a unui text și modulul trebuie să refuze să ghicească. Aici fiecare
valoare stă într-un element cu nume: nu există incertitudine de citire, ci doar
prezență sau absență. Testele apără exact asta — **ce lipsește rămâne lipsă**, și
nimic nu se completează din context.

A doua proprietate, la fel de importantă: XML-ul vine din afară. Un fișier cu DTD
sau entități este respins, nu curățat.

Toate facturile de mai jos sunt inventate (§70).
"""

from __future__ import annotations

import pytest

from app.domain import efactura as ef

UBL = (
    'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
)


def invoice(body: str, *, root: str = "Invoice", namespace: str = UBL) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><{root} {namespace}>{body}</{root}>'.encode()


COMPLETE = invoice(
    """
    <cbc:ID>FCT 7001</cbc:ID>
    <cbc:IssueDate>2026-08-14</cbc:IssueDate>
    <cbc:DueDate>2026-09-13</cbc:DueDate>
    <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>RON</cbc:DocumentCurrencyCode>
    <cac:AccountingSupplierParty><cac:Party>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Tert Furnizor SRL</cbc:RegistrationName>
        <cbc:CompanyID>RO99887766</cbc:CompanyID>
      </cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>RO99887766</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party></cac:AccountingSupplierParty>
    <cac:AccountingCustomerParty><cac:Party>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>Alfa Conta SRL</cbc:RegistrationName>
        <cbc:CompanyID>RO10000101</cbc:CompanyID>
      </cac:PartyLegalEntity>
    </cac:Party></cac:AccountingCustomerParty>
    <cac:TaxTotal><cbc:TaxAmount currencyID="RON">190.00</cbc:TaxAmount></cac:TaxTotal>
    <cac:LegalMonetaryTotal>
      <cbc:TaxExclusiveAmount currencyID="RON">1000.00</cbc:TaxExclusiveAmount>
      <cbc:TaxInclusiveAmount currencyID="RON">1190.00</cbc:TaxInclusiveAmount>
      <cbc:PayableAmount currencyID="RON">1190.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
    """
)


class TestRecognisingTheFile:
    def test_an_xml_declaration_is_recognised(self) -> None:
        assert ef.looks_like_xml(b'<?xml version="1.0"?><Invoice/>')

    def test_a_byte_order_mark_does_not_hide_it(self) -> None:
        """Exportul din Windows pune adesea BOM."""
        assert ef.looks_like_xml(b'\xef\xbb\xbf<?xml version="1.0"?>')

    def test_html_is_not_an_invoice(self) -> None:
        """Fără declarație, orice fișier care începe cu `<` ar trece."""
        assert not ef.looks_like_xml(b"<html><body>Factura</body></html>")

    def test_a_pdf_is_not_xml(self) -> None:
        assert not ef.looks_like_xml(b"%PDF-1.4")


class TestReadingAnInvoice:
    def test_every_field_comes_from_the_document(self) -> None:
        parsed = ef.parse(COMPLETE)

        assert parsed.series == "FCT"
        assert parsed.number == "7001"
        assert parsed.issue_date == "2026-08-14"
        assert parsed.currency == "RON"
        assert parsed.supplier.name == "Tert Furnizor SRL"
        assert parsed.supplier.tax_id == "RO99887766"
        assert parsed.customer.name == "Alfa Conta SRL"
        assert parsed.customer.tax_id == "RO10000101"
        assert parsed.subtotal == "1000.00"
        assert parsed.vat_amount == "190.00"
        assert parsed.total == "1190.00"
        assert parsed.is_credit_note is False

    def test_the_due_date_is_not_taken_for_the_issue_date(self) -> None:
        """Confuzia dintre ele mută documentul în altă lună contabilă.

        În text distincția se poate rata; aici este explicită în document, deci un
        eșec ar însemna că citim elementul greșit.
        """
        assert ef.parse(COMPLETE).issue_date == "2026-08-14"

    def test_amounts_are_normalised_to_two_decimals(self) -> None:
        parsed = ef.parse(
            invoice(
                "<cac:LegalMonetaryTotal>"
                "<cbc:TaxInclusiveAmount>1190</cbc:TaxInclusiveAmount>"
                "</cac:LegalMonetaryTotal>"
            )
        )
        assert parsed.total == "1190.00"

    def test_the_invoice_total_wins_over_what_is_left_to_pay(self) -> None:
        """`PayableAmount` scade cu avansurile deja plătite; contabilitatea vrea totalul."""
        parsed = ef.parse(
            invoice(
                "<cac:LegalMonetaryTotal>"
                "<cbc:TaxInclusiveAmount>1190.00</cbc:TaxInclusiveAmount>"
                "<cbc:PayableAmount>190.00</cbc:PayableAmount>"
                "</cac:LegalMonetaryTotal>"
            )
        )
        assert parsed.total == "1190.00"

    def test_the_payable_amount_is_the_fallback(self) -> None:
        parsed = ef.parse(
            invoice(
                "<cac:LegalMonetaryTotal>"
                "<cbc:PayableAmount>250.00</cbc:PayableAmount>"
                "</cac:LegalMonetaryTotal>"
            )
        )
        assert parsed.total == "250.00"


class TestWhatIsMissingStaysMissing:
    def test_an_empty_invoice_yields_nothing(self) -> None:
        parsed = ef.parse(invoice(""))

        assert parsed.number is None
        assert parsed.issue_date is None
        assert parsed.total is None
        assert parsed.supplier.name is None
        assert parsed.customer.tax_id is None

    def test_an_unreadable_amount_is_absent_not_zero(self) -> None:
        """Zero este o afirmație: ar spune că factura este pe nimic."""
        parsed = ef.parse(
            invoice(
                "<cac:LegalMonetaryTotal>"
                "<cbc:TaxInclusiveAmount>o mie</cbc:TaxInclusiveAmount>"
                "</cac:LegalMonetaryTotal>"
            )
        )
        assert parsed.total is None


class TestSeriesAndNumber:
    def test_a_clear_shape_is_split(self) -> None:
        """Numele de arhivă (§10) folosește seria și numărul separat."""
        assert ef._split_number("FCT7001") == ("FCT", "7001")
        assert ef._split_number("FCT 7001") == ("FCT", "7001")
        assert ef._split_number("FCT-7001") == ("FCT", "7001")

    def test_anything_else_stays_whole(self) -> None:
        """O serie inventată ar ajunge în numele fișierului arhivat."""
        assert ef._split_number("2026/A/7001") == (None, "2026/A/7001")
        assert ef._split_number("7001") == (None, "7001")


class TestTaxIdLocation:
    def test_a_company_without_vat_registration_is_still_identified(self) -> None:
        """Neplătitorul de TVA nu are `PartyTaxScheme`, dar are `PartyLegalEntity`."""
        parsed = ef.parse(
            invoice(
                "<cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity>"
                "<cbc:RegistrationName>Mica Firma SRL</cbc:RegistrationName>"
                "<cbc:CompanyID>12345678</cbc:CompanyID>"
                "</cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>"
            )
        )
        assert parsed.supplier.tax_id == "12345678"

    def test_the_trade_name_is_the_fallback(self) -> None:
        parsed = ef.parse(
            invoice(
                "<cac:AccountingSupplierParty><cac:Party><cac:PartyName>"
                "<cbc:Name>Denumire Comerciala</cbc:Name>"
                "</cac:PartyName></cac:Party></cac:AccountingSupplierParty>"
            )
        )
        assert parsed.supplier.name == "Denumire Comerciala"


class TestCreditNotes:
    def test_the_root_element_marks_it(self) -> None:
        content = invoice(
            "<cbc:ID>STORNO1</cbc:ID>",
            root="CreditNote",
            namespace=UBL.replace("Invoice-2", "CreditNote-2"),
        )
        assert ef.parse(content).is_credit_note is True

    def test_the_type_code_marks_it_too(self) -> None:
        """381 este nota de credit în UNTDID 1001."""
        assert ef.parse(invoice("<cbc:InvoiceTypeCode>381</cbc:InvoiceTypeCode>")).is_credit_note

    def test_an_ordinary_invoice_is_not_one(self) -> None:
        ordinary = invoice("<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>")
        assert not ef.parse(ordinary).is_credit_note


class TestRefusals:
    def test_something_that_is_not_ubl(self) -> None:
        with pytest.raises(ef.EFacturaError, match="UBL"):
            ef.parse(b'<?xml version="1.0"?><configurare><valoare>1</valoare></configurare>')

    def test_broken_xml(self) -> None:
        with pytest.raises(ef.EFacturaError):
            ef.parse(b'<?xml version="1.0"?><Invoice><cbc:ID>')

    def test_a_document_type_definition_is_refused_not_cleaned(self) -> None:
        """„Billion laughs": o entitate care se expandează până umple memoria.

        O factură reală nu are DOCTYPE, deci refuzul nu costă niciun caz legitim.
        """
        bomb = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE Invoice [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            b"<Invoice><cbc:ID>&b;</cbc:ID></Invoice>"
        )
        with pytest.raises(ef.EFacturaError):
            ef.parse(bomb)

    def test_an_external_entity_cannot_read_a_local_file(self) -> None:
        """XXE — clasicul prin care un XML citește `/etc/passwd` sau un secret."""
        xxe = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE Invoice [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<Invoice><cbc:ID>&x;</cbc:ID></Invoice>"
        )
        with pytest.raises(ef.EFacturaError):
            ef.parse(xxe)


class TestTheSummary:
    def test_it_carries_what_an_operator_would_read_off_the_page(self) -> None:
        """Un XML nu se poate privi; rezumatul ține locul facsimilului."""
        summary = ef.parse(COMPLETE).summary

        assert "Tert Furnizor SRL" in summary
        assert "RO10000101" in summary
        assert "1190.00" in summary
        assert "2026-08-14" in summary

    def test_a_credit_note_says_so_first(self) -> None:
        content = invoice("<cbc:InvoiceTypeCode>381</cbc:InvoiceTypeCode>")
        assert ef.parse(content).summary.startswith("NOTĂ DE CREDIT")
