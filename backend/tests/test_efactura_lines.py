"""Liniile facturii electronice: ce s-a vândut și cu ce cotă (§9).

**Ce lipsea.** Din XML se citeau totalurile — bază, TVA, total — și atât. Pentru
un contabil, TVA-ul unei facturi nu este un număr: pe aceeași factură pot sta
21% pentru un produs, 11% pentru altul și 0% pentru un serviciu scutit, iar
decontul le cere separat. Un singur procent la nivel de document este o medie
fără sens contabil, din care defalcarea nu se poate reconstitui.

**De ce se poate face aici, și nu din PDF.** Într-un XML UBL fiecare valoare stă
într-un element cu nume: nu se citește un procent dintr-un text, se citește
câmpul `Percent`. Nu există „80% sigur". Din PDF-uri liniile rămân necitite și nu
se vor ghici — o linie inventată intră direct în decontul de TVA.
"""

from __future__ import annotations

from app.domain.efactura import parse

UBL = (
    'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
)
CREDIT_UBL = UBL.replace("Invoice-2", "CreditNote-2")


def invoice(body: str, *, root: str = "Invoice", namespace: str = UBL) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><{root} {namespace}>{body}</{root}>'.encode()


#: Trei cote pe aceeași factură — cazul care justifică tot modulul.
THREE_RATES = invoice(
    """
    <cbc:ID>FCT 7001</cbc:ID>
    <cbc:IssueDate>2026-08-14</cbc:IssueDate>
    <cbc:DocumentCurrencyCode>RON</cbc:DocumentCurrencyCode>
    <cac:InvoiceLine>
      <cbc:ID>1</cbc:ID>
      <cbc:InvoicedQuantity unitCode="H87">2</cbc:InvoicedQuantity>
      <cbc:LineExtensionAmount currencyID="RON">1000.00</cbc:LineExtensionAmount>
      <cac:Item>
        <cbc:Name>Monitor 24 inch</cbc:Name>
        <cac:ClassifiedTaxCategory>
          <cbc:ID>S</cbc:ID><cbc:Percent>21.00</cbc:Percent>
        </cac:ClassifiedTaxCategory>
      </cac:Item>
      <cac:Price><cbc:PriceAmount currencyID="RON">500.00</cbc:PriceAmount></cac:Price>
    </cac:InvoiceLine>
    <cac:InvoiceLine>
      <cbc:ID>2</cbc:ID>
      <cbc:InvoicedQuantity unitCode="H87">10</cbc:InvoicedQuantity>
      <cbc:LineExtensionAmount currencyID="RON">250.00</cbc:LineExtensionAmount>
      <cac:Item>
        <cbc:Name>Manual de utilizare (tiparit)</cbc:Name>
        <cac:ClassifiedTaxCategory>
          <cbc:ID>S</cbc:ID><cbc:Percent>11</cbc:Percent>
        </cac:ClassifiedTaxCategory>
      </cac:Item>
      <cac:Price><cbc:PriceAmount currencyID="RON">25.00</cbc:PriceAmount></cac:Price>
    </cac:InvoiceLine>
    <cac:InvoiceLine>
      <cbc:ID>3</cbc:ID>
      <cbc:InvoicedQuantity unitCode="HUR">1.5</cbc:InvoicedQuantity>
      <cbc:LineExtensionAmount currencyID="RON">300.00</cbc:LineExtensionAmount>
      <cac:Item>
        <cbc:Name>Consultanta</cbc:Name>
        <cac:ClassifiedTaxCategory>
          <cbc:ID>AE</cbc:ID><cbc:Percent>0</cbc:Percent>
        </cac:ClassifiedTaxCategory>
      </cac:Item>
      <cac:Price><cbc:PriceAmount currencyID="RON">200.00</cbc:PriceAmount></cac:Price>
    </cac:InvoiceLine>
    """
)


class TestReadingTheLines:
    def test_three_vat_rates_on_the_same_invoice_stay_three(self) -> None:
        """Motivul întreg al modulului, într-o singură asertiune."""
        lines = parse(THREE_RATES).lines

        assert [line.vat_rate for line in lines] == ["21", "11", "0"]

    def test_every_column_the_screen_shows_is_read(self) -> None:
        first = parse(THREE_RATES).lines[0]

        assert first.number == "1"
        assert first.description == "Monitor 24 inch"
        assert first.quantity == "2"
        assert first.unit_code == "H87"
        assert first.unit_price == "500.00"
        assert first.net_amount == "1000.00"
        assert first.vat_rate == "21"
        assert first.vat_category == "S"

    def test_a_percent_written_with_decimals_reads_as_a_whole_number(self) -> None:
        """`21.00` din XML se citește `21`: pe ecran stă lângă „%", nu într-un total."""
        assert parse(THREE_RATES).lines[0].vat_rate == "21"

    def test_a_fractional_quantity_keeps_its_decimals(self) -> None:
        """O oră și jumătate nu se rotunjește la două ore."""
        assert parse(THREE_RATES).lines[2].quantity == "1.5"

    def test_the_reverse_charge_category_explains_a_zero(self) -> None:
        """`AE` este taxare inversă. Fără categorie, un `0%` arată ca o eroare."""
        third = parse(THREE_RATES).lines[2]

        assert third.vat_rate == "0"
        assert third.vat_category == "AE"

    def test_the_order_from_the_document_is_kept(self) -> None:
        """Ordinea liniilor este a documentului, nu una sortată de noi."""
        assert [line.number for line in parse(THREE_RATES).lines] == ["1", "2", "3"]


class TestWhenTheDocumentSaysNothing:
    def test_an_invoice_without_lines_has_none_and_does_not_invent_any(self) -> None:
        """Absența liniilor nu este un eșec: multe facturi vechi nu le declară."""
        without = invoice("<cbc:ID>FCT 1</cbc:ID><cbc:IssueDate>2026-08-01</cbc:IssueDate>")

        assert parse(without).lines == ()

    def test_an_empty_line_element_is_skipped_not_kept_as_a_blank_row(self) -> None:
        """Un rând gol în registru arată ca o pierdere de date fără să fie."""
        with_empty = invoice(
            "<cbc:ID>FCT 2</cbc:ID><cac:InvoiceLine><cbc:ID>1</cbc:ID></cac:InvoiceLine>"
        )

        assert parse(with_empty).lines == ()

    def test_a_line_without_a_tax_category_keeps_the_rest(self) -> None:
        """Ce lipsește lipsește; ce se poate citi se citește."""
        partial = invoice(
            """
            <cbc:ID>FCT 3</cbc:ID>
            <cac:InvoiceLine>
              <cbc:ID>1</cbc:ID>
              <cbc:LineExtensionAmount currencyID="RON">99.00</cbc:LineExtensionAmount>
              <cac:Item><cbc:Name>Ceva</cbc:Name></cac:Item>
            </cac:InvoiceLine>
            """
        )

        line = parse(partial).lines[0]
        assert line.description == "Ceva"
        assert line.net_amount == "99.00"
        assert line.vat_rate is None
        assert line.vat_category is None

    def test_a_broken_number_is_absent_not_zero(self) -> None:
        """Zero este o afirmație. „Nu s-a putut citi" este alta."""
        broken = invoice(
            """
            <cbc:ID>FCT 4</cbc:ID>
            <cac:InvoiceLine>
              <cbc:ID>1</cbc:ID>
              <cbc:InvoicedQuantity unitCode="H87">doua</cbc:InvoicedQuantity>
              <cbc:LineExtensionAmount currencyID="RON">50.00</cbc:LineExtensionAmount>
              <cac:Item><cbc:Name>Ceva</cbc:Name></cac:Item>
            </cac:InvoiceLine>
            """
        )

        assert parse(broken).lines[0].quantity is None


class TestTheCreditNote:
    def test_its_lines_are_read_too_despite_the_different_element_names(self) -> None:
        """`CreditNoteLine` și `CreditedQuantity` — restul este identic.

        Fără cazul ăsta, o notă de credit ar fi apărut fără linii, iar stornarea
        este exact momentul în care contabilul verifică defalcarea.
        """
        note = invoice(
            """
            <cbc:ID>STORNO 5</cbc:ID>
            <cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode>
            <cac:CreditNoteLine>
              <cbc:ID>1</cbc:ID>
              <cbc:CreditedQuantity unitCode="H87">1</cbc:CreditedQuantity>
              <cbc:LineExtensionAmount currencyID="RON">100.00</cbc:LineExtensionAmount>
              <cac:Item>
                <cbc:Name>Retur monitor</cbc:Name>
                <cac:ClassifiedTaxCategory>
                  <cbc:ID>S</cbc:ID><cbc:Percent>21</cbc:Percent>
                </cac:ClassifiedTaxCategory>
              </cac:Item>
            </cac:CreditNoteLine>
            """,
            root="CreditNote",
            namespace=CREDIT_UBL,
        )

        parsed = parse(note)
        assert parsed.is_credit_note
        assert len(parsed.lines) == 1
        assert parsed.lines[0].description == "Retur monitor"
        assert parsed.lines[0].quantity == "1"
        assert parsed.lines[0].vat_rate == "21"


class TestWhatTheOperatorReads:
    def test_the_summary_shows_the_lines_under_the_totals(self) -> None:
        """Un XML nu se poate privi; rezumatul ține locul facsimilului.

        Cotele diferite de pe aceeași factură sunt exact ce nu se vede din
        totaluri: cu „TVA: 250,00" și nimic altceva, operatorul nu are cum să afle
        din ce s-a compus.
        """
        summary = parse(THREE_RATES).summary

        assert "Linii:" in summary
        assert "Monitor 24 inch" in summary
        assert "21%" in summary
        assert "11%" in summary

    def test_an_invoice_without_lines_has_no_empty_heading(self) -> None:
        without = invoice("<cbc:ID>FCT 1</cbc:ID>")

        assert "Linii:" not in parse(without).summary
