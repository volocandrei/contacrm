"""Unde se taie un teanc scanat — și, mai ales, unde nu se taie (§8).

**Ce se apără aici.** O factură tăiată greșit în două produce două jumătăți care
arată ca documente adevărate: fiecare cu numărul ei citit greșit, fiecare cu un
total parțial. Un teanc netăiat este o supărare cunoscută, pe care contabilul o
rezolvă de mână; un teanc tăiat greșit este o eroare care intră în decont fără să
pară o eroare.

De aceea majoritatea testelor de mai jos verifică **ce nu se taie**, iar ordinea
lor este a gravității:

1. **O factură de trei pagini rămâne un document.** Cazul cel mai frecvent și cel
   mai ușor de stricat: paginile 2 și 3 au antet, au numărul facturii, au tot.
2. **Un singur semnal nu taie.** Nici antetul singur, nici numărul singur.
3. **Paginarea interzice**, oricâte alte semnale ar fi pe pagină.
4. **Cuvântul „factură" din corpul textului nu începe un document** — apare de
   zece ori pe orice factură.
"""

from __future__ import annotations

from app.domain.pdf_split import Segment, detect, read_page

NEWLINE = chr(10)

# ── Pagini de probă ──────────────────────────────────────────────────────────


def invoice_page(number: str, page: int | None = None, total: int | None = None) -> str:
    """Prima pagină a unei facturi, cu antet sus și numărul în antet."""
    paging = f"pagina {page} din {total}" if page and total else ""
    return f"""
    FACTURA FISCALA nr. {number}
    Serie FCT   Data: 14.08.2026
    Furnizor: Terț Furnizor SRL  CUI: RO99887766
    Cumparator: Alfa Conta SRL   CUI: RO10000101
    {paging}
    Denumire produs        Cantitate   Pret     Valoare
    Monitor 24 inch        2           500,00   1000,00
    Total de plata: 1190,00 lei
    Plata se face conform facturii, in 30 de zile.
    """


def continuation_page(number: str, page: int, total: int) -> str:
    """A doua pagină a aceleiași facturi: are tot ce are prima, plus paginarea."""
    return f"""
    FACTURA FISCALA nr. {number}   pagina {page} din {total}
    Continuare produse
    Tastatura              1           120,00   120,00
    Mouse                  1            60,00    60,00
    Total pagina: 180,00 lei
    """


def receipt_page(number: str) -> str:
    return f"""
    CHITANTA nr. {number}
    Am primit de la Alfa Conta SRL suma de 500,00 lei
    Reprezentand: contravaloare factura FCT 7001
    """


class TestWhatMustNotBeCut:
    def test_a_three_page_invoice_stays_one_document(self) -> None:
        """Cazul cel mai frecvent, și cel mai ușor de stricat.

        Paginile 2 și 3 au antet, au numărul facturii, au totul. Singurul lucru
        care le deosebește de o factură nouă este paginarea — iar ea trebuie să
        fie de ajuns.
        """
        pages = [
            invoice_page("7001", 1, 3),
            continuation_page("7001", 2, 3),
            continuation_page("7001", 3, 3),
        ]

        segments = detect(pages)

        assert len(segments) == 1
        assert segments[0] == Segment(
            page_from=1, page_to=3, document_type="factură", document_number="7001"
        )

    def test_the_same_invoice_twice_in_a_row_is_not_cut_without_a_new_number(self) -> None:
        """Un exemplar în plus al aceleiași facturi are antet, dar același număr.

        Antetul singur nu taie. Altfel, orice copie xerox dublată în scanner ar fi
        devenit un document nou, cu aceeași sumă — adică o cheltuială înregistrată
        de două ori.
        """
        pages = [invoice_page("7001"), invoice_page("7001")]

        assert len(detect(pages)) == 1

    def test_a_page_that_says_it_is_the_second_is_never_a_start(self) -> None:
        """Paginarea este singurul semnal care **interzice**, și bate tot.

        Pagina de mai jos are antet nou **și** alt număr — două semnale care ar
        tăia oriunde altundeva — dar spune despre ea însăși că este a doua.
        """
        pages = [
            invoice_page("7001", 1, 2),
            continuation_page("7002", 2, 2),
        ]

        assert len(detect(pages)) == 1

    def test_the_word_invoice_inside_the_body_does_not_start_a_document(self) -> None:
        """„conform facturii", „factura se achită" — apar pe orice factură.

        De aceea antetul se caută doar în prima treime a paginii.
        """
        # Antetul se cauta in primele randuri. Pagina de mai jos are cuvantul
        # „factura" abia dupa doisprezece randuri de text — exact ca in corpul
        # unei anexe adevarate.
        body = (
            "Anexa la contract" + NEWLINE + (NEWLINE.join(f"Articolul {i}" for i in range(1, 14)))
        )
        body += NEWLINE + "Prezenta anexa se factureaza lunar, conform facturii nr. 9999."
        pages = [invoice_page("7001"), body]

        assert len(detect(pages)) == 1

    def test_a_single_page_file_is_one_document(self) -> None:
        assert detect([invoice_page("7001")]) == [
            Segment(page_from=1, page_to=1, document_type="factură", document_number="7001")
        ]

    def test_an_empty_file_produces_nothing(self) -> None:
        assert detect([]) == []

    def test_a_scan_without_a_text_layer_stays_whole(self) -> None:
        """O poză nu spune nimic despre ea. Nu se ghicesc granițe din nimic.

        Este cazul obișnuit al unui teanc fotografiat, iar tăierea lui la
        întâmplare ar fi produs cinci documente goale în loc de unul.
        """
        segments = detect(["", "", ""])

        assert len(segments) == 1
        assert segments[0].pages == 3


class TestWhatIsCut:
    def test_two_invoices_with_different_numbers_become_two_documents(self) -> None:
        """Rostul întreg al modulului."""
        pages = [invoice_page("7001"), invoice_page("7002")]

        segments = detect(pages)

        assert len(segments) == 2
        assert [s.document_number for s in segments] == ["7001", "7002"]
        assert [s.page_from for s in segments] == [1, 2]
        assert [s.page_to for s in segments] == [1, 2]

    def test_a_receipt_after_an_invoice_is_a_separate_document(self) -> None:
        """Teancul real: o factură, apoi chitanța pentru ea."""
        segments = detect([invoice_page("7001"), receipt_page("55")])

        assert [s.document_type for s in segments] == ["factură", "chitanță"]

    def test_a_page_that_declares_itself_first_starts_a_document(self) -> None:
        """„pagina 1 din 2" este explicit, deci taie singur.

        Este singurul semnal care nu are nevoie de al doilea: documentul spune
        despre el însuși unde începe.
        """
        pages = [
            invoice_page("7001"),
            # Fără antet și fără număr nou — doar paginarea proprie.
            "pagina 1 din 2\nContinut oarecare fara antet",
            "pagina 2 din 2\nRestul continutului",
        ]

        segments = detect(pages)

        assert len(segments) == 2
        assert segments[1].page_from == 2
        assert segments[1].page_to == 3

    def test_a_multi_page_invoice_followed_by_another_is_split_correctly(self) -> None:
        """Cazul complet: 1-2 prima factură, 3-4 a doua."""
        pages = [
            invoice_page("7001", 1, 2),
            continuation_page("7001", 2, 2),
            invoice_page("7002", 1, 2),
            continuation_page("7002", 2, 2),
        ]

        segments = detect(pages)

        assert [(s.page_from, s.page_to) for s in segments] == [(1, 2), (3, 4)]
        assert [s.document_number for s in segments] == ["7001", "7002"]


class TestWhatTheHumanReads:
    def test_every_cut_says_why(self) -> None:
        """O tăietură fără motiv nu se poate verifica, deci nu se poate accepta."""
        segments = detect([invoice_page("7001"), invoice_page("7002")])

        assert segments[0].reasons == ()  # primul segment nu este o tăietură
        assert segments[1].reasons
        assert any("alt număr" in reason for reason in segments[1].reasons)
        assert any("antet nou" in reason for reason in segments[1].reasons)

    def test_the_type_is_taken_from_the_first_page_of_the_segment(self) -> None:
        segments = detect([invoice_page("7001"), receipt_page("55")])

        assert segments[1].document_type == "chitanță"

    def test_the_number_is_read_from_the_header_area_only(self) -> None:
        """Si de pe paginile urmatoare, dar tot din antetul lor.

        O factura isi repeta numarul sus pe fiecare pagina, iar acolo se cauta.
        **Nu** oriunde pe pagina, si nu din prudenta abstracta: in corpul oricarei
        facturi scrie „conform facturii nr. 9999" — un numar care este al altui
        document si care ar fi devenit numarul acestuia.
        """
        pages = [
            "FACTURA" + NEWLINE + "pagina 1 din 2" + NEWLINE + "fara numar aici",
            "Factura nr. 7005   pagina 2 din 2" + NEWLINE + "continuare produse",
        ]

        segments = detect(pages)

        assert len(segments) == 1
        assert segments[0].document_number == "7005"

    def test_a_number_hidden_in_the_body_is_not_borrowed(self) -> None:
        """Consecinta regulii de mai sus, verificata direct.

        Segmentul ramane fara numar — vizibil pe ecran ca „—", ceea ce este
        adevarat — in loc sa poarte numarul altei facturi, ceea ce ar fi aratat
        la fel de convingator si ar fi fost fals.
        """
        filler = NEWLINE.join(f"detalii pozitia {i}" for i in range(1, 15))
        pages = [
            "FACTURA" + NEWLINE + "pagina 1 din 2" + NEWLINE + "fara numar in antet",
            "pagina 2 din 2" + NEWLINE + filler + NEWLINE + "conform facturii nr. 9999",
        ]

        segments = detect(pages)

        assert len(segments) == 1
        assert segments[0].document_number is None


class TestReadingASinglePage:
    def test_the_header_is_found_only_at_the_top(self) -> None:
        filler = NEWLINE.join("text oarecare" for _ in range(20))
        top = read_page(1, "FACTURA nr. 7001" + NEWLINE + filler)
        bottom = read_page(1, filler + NEWLINE + "FACTURA nr. 7001")

        assert top.header == "factură"
        assert bottom.header is None

    def test_pagination_is_read_in_its_usual_forms(self) -> None:
        for text in ("pagina 2 din 5", "pag. 2/5", "Pagina 2 / 5"):
            assert read_page(1, f"FACTURA\n{text}").pagination == (2, 5)

    def test_a_coincidence_of_numbers_is_not_pagination(self) -> None:
        """„5 din 3" nu există. Este suma sau un cod, citit greșit."""
        assert read_page(1, "FACTURA\n5 din 3").pagination is None

    def test_a_page_without_text_says_so(self) -> None:
        assert read_page(1, "   \n  ").has_text is False
