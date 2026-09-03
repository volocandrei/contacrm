"""Regulile de citire a unui document contabil (§20, §21).

Testele astea apără o singură proprietate, care contează mai mult decât acoperirea:
**modulul nu ghicește**. Fiecare clasă de mai jos are perechea ei — un caz în care
valoarea se găsește, și un caz în care textul e ambiguu și răspunsul corect este
„nu știu".

Un câmp gol costă zece secunde de completat de pe facsimil. Un câmp completat
greșit trece pe lângă operator, pentru că ecranul arată o valoare care pare citită
de pe document. De aceea, aici, un fals negativ este un test care trece și un fals
pozitiv este un test care cade.

Toate textele sunt inventate. Niciun document contabil real nu intră în repo (§70).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.romanian_documents import (
    AMBIGUOUS,
    COMPETING,
    LABELLED,
    classify,
    find_amounts,
    find_currency,
    find_document_date,
    find_series_and_number,
    find_tax_ids,
    is_valid_tax_id,
    normalize,
    parse_amount,
    strip_diacritics,
)

TYPES = frozenset({"FACTURA_INTRARE", "BON_FISCAL", "EXTRAS_CONT", "CHITANTA"})


class TestNormalisation:
    def test_diacritics_are_reduced(self) -> None:
        assert strip_diacritics("Șerbănescu Impex") == "Serbanescu Impex"
        assert strip_diacritics("Total de plată") == "Total de plata"

    def test_both_romanian_comma_and_cedilla_forms_reduce_alike(self) -> None:
        """Documentele reale amestecă `ș` (corect) cu `ş` (sedilă, greșit)."""
        assert strip_diacritics("şi") == strip_diacritics("și") == "si"

    def test_whitespace_from_pdf_extraction_is_collapsed(self) -> None:
        """Extragerea din PDF varsă des spații și rânduri în locuri ciudate."""
        assert normalize("Total   de\n\n plată") == "total de plata"


class TestTaxId:
    def test_a_labelled_code_is_read(self) -> None:
        supplier, customer = find_tax_ids("Furnizor: Alfa SRL\nCUI: RO 14399840")
        assert supplier is not None
        assert supplier.value == "14399840"
        # Un singur cod, marcat ca al furnizorului — cumpărătorul rămâne necunoscut.
        assert customer is None

    def test_the_role_decides_which_side_the_code_belongs_to(self) -> None:
        text = "Furnizor: Alfa SRL CIF: RO1234567\nCumparator: Beta SRL CIF: RO7654321"
        supplier, customer = find_tax_ids(text)

        assert supplier is not None and supplier.value == "1234567"
        assert customer is not None and customer.value == "7654321"

    def test_without_a_role_marker_nothing_is_assigned(self) -> None:
        """Un CUI pus pe partea greșită schimbă cine datorează cui."""
        supplier, customer = find_tax_ids("CUI: RO1234567 si CIF: RO7654321")
        assert supplier is None
        assert customer is None

    def test_a_number_without_a_label_is_just_a_number(self) -> None:
        supplier, customer = find_tax_ids("Furnizor: Alfa SRL, telefon 0722123456")
        assert supplier is None and customer is None

    def test_separators_from_pdf_extraction_do_not_break_it(self) -> None:
        supplier, _ = find_tax_ids("Furnizor Alfa\nC.U.I. : RO 14 399 840")
        assert supplier is not None and supplier.value == "14399840"

    def test_a_failing_checksum_still_reports_but_with_less_confidence(self) -> None:
        """Verificarea ridică încrederea; nu respinge.

        Dacă algoritmul ar fi greșit, efectul este că valorile corecte ajung la
        verificare umană în loc să treacă automat — un eșec în direcția bună.
        """
        supplier, _ = find_tax_ids("Furnizor: Alfa SRL CUI: RO1234567")
        assert supplier is not None
        assert supplier.confidence in {LABELLED, COMPETING}


class TestTaxIdChecksum:
    def test_the_control_digit_is_unique(self) -> None:
        """Exact una dintre cele zece cifre finale poate fi corectă."""
        valid = [d for d in range(10) if is_valid_tax_id(f"1439984{d}")]
        assert len(valid) == 1

    def test_changing_a_digit_breaks_it(self) -> None:
        body = "1439984"
        control = next(d for d in range(10) if is_valid_tax_id(f"{body}{d}"))
        good = f"{body}{control}"
        assert is_valid_tax_id(good)
        # Orice altă cifră în corp trebuie să strice verificarea.
        broken = ("9" if good[0] != "9" else "1") + good[1:]
        assert not is_valid_tax_id(broken)

    def test_nonsense_is_refused(self) -> None:
        assert not is_valid_tax_id("")
        assert not is_valid_tax_id("R01234")
        assert not is_valid_tax_id("1")
        assert not is_valid_tax_id("12345678901")


class TestDate:
    def test_a_labelled_date_is_read(self) -> None:
        found = find_document_date("Factura fiscala\nData emiterii: 14.08.2026")
        assert found is not None
        assert found.value == "2026-08-14"
        assert found.confidence == LABELLED

    @pytest.mark.parametrize("written", ["14.08.2026", "14/08/2026", "14-08-2026"])
    def test_the_usual_separators_all_work(self, written: str) -> None:
        found = find_document_date(f"Data: {written}")
        assert found is not None and found.value == "2026-08-14"

    def test_the_due_date_is_not_the_document_date(self) -> None:
        """Confuzia dintre ele mută documentul în altă lună contabilă."""
        assert find_document_date("Data scadentei: 14.09.2026") is None

    def test_the_document_date_survives_next_to_a_due_date(self) -> None:
        text = "Data emiterii: 14.08.2026\nData scadentei: 13.09.2026"
        found = find_document_date(text)
        assert found is not None and found.value == "2026-08-14"

    def test_an_impossible_date_is_not_repaired(self) -> None:
        assert find_document_date("Data: 31.02.2026") is None

    def test_two_different_labelled_dates_lower_the_confidence(self) -> None:
        found = find_document_date("Data: 14.08.2026 ... Data: 20.08.2026")
        assert found is not None
        assert found.confidence == COMPETING

    def test_a_bare_date_is_not_taken(self) -> None:
        assert find_document_date("Valabil pana la 14.08.2026") is None


class TestSeriesAndNumber:
    def test_series_and_number_together(self) -> None:
        series, number = find_series_and_number("Seria FCT nr. 7001")
        assert series is not None and series.value == "FCT"
        assert number is not None and number.value == "7001"

    def test_a_lone_number_is_accepted(self) -> None:
        """Bonurile fiscale nu au serie."""
        series, number = find_series_and_number("Bon fiscal nr. 12345")
        assert series is None
        assert number is not None and number.value == "12345"

    def test_several_numbers_mean_we_cannot_tell_which(self) -> None:
        """„nr." apare și în „nr. crt." dintr-un tabel de poziții."""
        series, number = find_series_and_number("nr. crt. 1 ... nr. 7001")
        assert series is None
        assert number is not None
        assert number.confidence == AMBIGUOUS

    def test_nothing_labelled_means_nothing_found(self) -> None:
        assert find_series_and_number("Factura pentru servicii 2026") == (None, None)


class TestAmounts:
    def test_romanian_number_format(self) -> None:
        assert parse_amount("1.234,56") == Decimal("1234.56")
        assert parse_amount("12,50") == Decimal("12.50")

    def test_plain_format(self) -> None:
        assert parse_amount("1234.56") == Decimal("1234.56")
        assert parse_amount("1234") == Decimal("1234.00")

    def test_thousands_separator_without_decimals(self) -> None:
        assert parse_amount("1.234") == Decimal("1234.00")

    def test_a_labelled_total_is_read(self) -> None:
        found = find_amounts("Total de plata: 1.234,56 lei")
        assert found["totalAmount"].value == "1234.56"
        assert found["totalAmount"].confidence == LABELLED

    def test_vat_and_base_are_read_separately(self) -> None:
        text = "Baza impozabila: 1.000,00\nTVA: 190,00\nTotal de plata: 1.190,00"
        found = find_amounts(text)

        assert found["subtotal"].value == "1000.00"
        assert found["vatAmount"].value == "190.00"
        assert found["totalAmount"].value == "1190.00"

    def test_nothing_is_computed_from_the_rest(self) -> None:
        """O factură poate avea mai multe cote de TVA; cota nu e a noastră de presupus."""
        found = find_amounts("Total de plata: 1.190,00")
        assert "vatAmount" not in found
        assert "subtotal" not in found

    def test_conflicting_totals_lower_the_confidence(self) -> None:
        found = find_amounts("Total 100,00 ... Total de plata 250,00")
        assert found["totalAmount"].confidence == AMBIGUOUS

    def test_an_unlabelled_amount_is_ignored(self) -> None:
        assert find_amounts("Va multumim! 1.234,56") == {}


class TestCurrency:
    def test_a_single_currency_is_read(self) -> None:
        found = find_currency("Total de plata: 1.234,56 lei")
        assert found is not None and found.value == "RON"

    def test_two_currencies_mean_we_cannot_tell(self) -> None:
        """Un curs de schimb afișat alături nu spune în ce monedă e factura."""
        assert find_currency("Total 250,00 EUR (curs 4,97 RON/EUR)") is None

    def test_no_currency_at_all(self) -> None:
        assert find_currency("Total de plata: 1.234,56") is None


class TestClassification:
    def test_an_unambiguous_title_is_read(self) -> None:
        found = classify("BON FISCAL\nTotal 25,00 lei", known_codes=TYPES)
        assert found is not None and found.value == "BON_FISCAL"

    def test_an_invoice_is_deliberately_not_classified(self) -> None:
        """Direcția (intrare/ieșire) depinde de al cui este cabinetul.

        Un document pus în registrul greșit este mai rău decât unul neclasificat,
        pe care oricum îl atinge un om.
        """
        assert classify("FACTURA FISCALA nr. 7001", known_codes=TYPES) is None

    def test_a_code_the_office_does_not_have_is_not_proposed(self) -> None:
        """§6 — tipurile sunt administrabile; scrierea ar respinge un cod străin."""
        assert classify("BON FISCAL", known_codes=frozenset({"FACTURA_INTRARE"})) is None

    def test_two_titles_mean_we_cannot_tell(self) -> None:
        assert classify("EXTRAS DE CONT ... CHITANTA", known_codes=TYPES) is None
