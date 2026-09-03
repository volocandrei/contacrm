"""Providerul care citește stratul de text al unui PDF (ADR-005, §20).

PDF-urile de aici sunt **construite în test**, cu un generator minimal scris mai
jos: niciun document contabil real nu intră în repo (§70), iar un fișier binar
comis ar fi imposibil de verificat la recenzie.

Testul cel mai important este `TestWhatItCannotRead`: un PDF scanat nu are strat de
text, iar providerul trebuie să întoarcă un rezultat gol în loc să inventeze ceva.
Un câmp gol trimite documentul la un om; un câmp inventat trece pe lângă el.
"""

from __future__ import annotations

import io
import zlib

import pytest

from app.domain.enums import FieldSource
from app.services.extraction.base import ExtractionError, ExtractionInput
from app.services.extraction.pdf_text import FIELDS, PROVIDER_NAME, PdfTextExtractionProvider

TYPES = frozenset({"FACTURA_INTRARE", "BON_FISCAL", "EXTRAS_CONT", "CHITANTA"})
SHA = "a" * 64


# ── Un generator de PDF cât să aibă strat de text ────────────────────────────


def _escape(line: str) -> str:
    return line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(lines: list[str], *, with_text: bool = True) -> bytes:
    """Un PDF valid, de o pagină, cu textul dat.

    Scris de mână pentru că alternativa — o bibliotecă de generare — ar fi o
    dependență adăugată doar ca testele să existe. `with_text=False` produce
    exact ce produce un scanner: o pagină fără niciun operator de text.

    **Limita generatorului**, ca să nu pară o limită a providerului: `ă`, `ș` și
    `ț` nu există în WinAnsi, deci nu pot fi scrise fără un font încorporat cu
    tabelă ToUnicode — prea mult pentru un ajutor de test. Reducerea diacriticelor
    este verificată direct pe text, în `test_romanian_documents.py`.
    """
    if with_text:
        # WinAnsiEncoding: fără el, diacriticele ies alt caracter la extragere.
        body = "BT /F1 12 Tf 40 780 Td 14 TL\n"
        body += "".join(f"({_escape(line)}) Tj T*\n" for line in lines)
        body += "ET"
    else:
        body = "0 0 0 rg 40 700 200 60 re f"

    stream = body.encode("latin-1", errors="replace")
    compressed = zlib.compress(stream)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed)
        + compressed
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + obj + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


def extract(
    lines: list[str],
    *,
    with_text: bool = True,
    mime_type: str = "application/pdf",
    known: frozenset[str] = TYPES,
):  # type: ignore[no-untyped-def]
    provider = PdfTextExtractionProvider(known_type_codes=known)
    return provider.extract(
        ExtractionInput(
            stream=io.BytesIO(make_pdf(lines, with_text=with_text)),
            mime_type=mime_type,
            original_filename="factura.pdf",
            sha256=SHA,
        )
    )


INVOICE = [
    "SC ALFA DISTRIBUTIE SRL",
    "Furnizor: Alfa Distributie SRL",
    "CUI: RO1234567",
    "Cumparator: Beta Service SRL",
    "CIF: RO7654321",
    "Seria FCT nr. 7001",
    "Data emiterii: 14.08.2026",
    "Baza impozabila: 1.000,00 lei",
    "TVA: 190,00 lei",
    "Total de plata: 1.190,00 lei",
]


class TestReadingADigitalPdf:
    def test_the_text_of_the_document_is_kept(self) -> None:
        """`ocr_text` devine textul real, nu unul sintetic — asta alimentează căutarea."""
        result = extract(INVOICE)

        assert result.provider == PROVIDER_NAME
        assert result.ocr_text is not None
        assert "Total de plata" in result.ocr_text

    def test_the_labelled_fields_are_read(self) -> None:
        fields = extract(INVOICE).fields

        assert fields["documentDate"].value == "2026-08-14"
        assert fields["series"].value == "FCT"
        assert fields["documentNumber"].value == "7001"
        assert fields["supplierTaxId"].value == "1234567"
        assert fields["customerTaxId"].value == "7654321"
        assert fields["totalAmount"].value == "1190.00"
        assert fields["vatAmount"].value == "190.00"
        assert fields["subtotal"].value == "1000.00"
        assert fields["currency"].value == "RON"

    def test_values_are_marked_as_read_not_as_proposed(self) -> None:
        """`OCR` = citit de pe document. `AI` ar fi însemnat că le-a propus un model.

        Badge-ul din ecranul de verificare arată diferența, deci proveniența
        trebuie să spună adevărul (§22).
        """
        fields = extract(INVOICE).fields
        assert fields["totalAmount"].source is FieldSource.OCR
        assert fields["documentDate"].source is FieldSource.OCR

    def test_nothing_is_reported_as_produced_by_a_model(self) -> None:
        result = extract(INVOICE)
        assert result.model is None
        assert result.prompt_version is None
        assert all(value.source is not FieldSource.AI for value in result.fields.values())

    def test_every_field_is_accounted_for(self) -> None:
        """Câmpurile negăsite sunt raportate goale, nu omise.

        `EMPTY` spune „am căutat și nu am găsit"; absența din dicționar ar spune
        „nici nu am încercat", ceea ce nu este același lucru.
        """
        fields = extract(INVOICE).fields
        assert set(fields) == set(FIELDS)

    def test_the_supplier_name_is_left_to_a_human(self) -> None:
        """Pe hârtie numele stă într-un bloc de adresă, fără etichetă.

        Orice regulă ar prinde la fel de des antetul tipografiei.
        """
        fields = extract(INVOICE).fields
        assert fields["supplierName"].source is FieldSource.EMPTY
        assert fields["customerName"].source is FieldSource.EMPTY

    def test_the_accounting_month_is_not_read_from_paper(self) -> None:
        """Se derivă din dată printr-o regulă a sistemului (ADR-008)."""
        assert extract(INVOICE).fields["referenceMonth"].source is FieldSource.EMPTY

    def test_an_invoice_is_not_classified(self) -> None:
        """Direcția depinde de al cui este cabinetul; providerul nu știe."""
        assert extract(INVOICE).document_type_code is None

    def test_an_unambiguous_title_is_classified(self) -> None:
        result = extract(["BON FISCAL", "Total de plata: 25,00 lei"])
        assert result.document_type_code == "BON_FISCAL"
        assert result.classification_source is FieldSource.OCR


class TestWhatItCannotRead:
    """Un rezultat gol nu este o eroare — este răspunsul corect."""

    def test_a_scanned_pdf_yields_nothing_instead_of_guesses(self) -> None:
        """Fără strat de text nu există nimic de citit. Aici ar începe OCR-ul real."""
        result = extract([], with_text=False)

        assert result.ocr_text is None
        assert result.document_type_code is None
        assert all(value.source is FieldSource.EMPTY for value in result.fields.values())

    def test_an_image_is_not_an_error_either(self) -> None:
        """`jpg`/`png` sunt tipuri acceptate la încărcare; providerul n-are ce oferi."""
        result = extract(INVOICE, mime_type="image/jpeg")

        assert result.ocr_text is None
        assert all(value.source is FieldSource.EMPTY for value in result.fields.values())

    def test_an_empty_result_carries_no_confidence(self) -> None:
        """`0.0` ar fi însemnat „am citit foarte prost", altceva decât „nu am citit"."""
        result = extract([], with_text=False)
        assert result.ocr_confidence is None
        assert result.extraction_confidence is None

    def test_a_broken_file_is_an_error_and_is_not_retried(self) -> None:
        """A trecut de validarea de tip la încărcare, deci ar fi trebuit să fie un PDF.

        O a doua încercare ar găsi aceiași octeți, deci nu se reia.
        """
        provider = PdfTextExtractionProvider(known_type_codes=TYPES)
        source = ExtractionInput(
            stream=io.BytesIO(b"%PDF-1.7\nnu este un pdf"),
            mime_type="application/pdf",
            original_filename="stricat.pdf",
            sha256=SHA,
        )
        with pytest.raises(ExtractionError) as caught:
            provider.extract(source)
        assert caught.value.retryable is False


class TestNotProposingUnknownTypes:
    def test_a_type_the_office_does_not_have_is_never_proposed(self) -> None:
        """§6 — scrierea ar respinge codul cu `ValidationError` și ar opri procesarea."""
        result = extract(["BON FISCAL", "Total 25,00 lei"], known=frozenset({"FACTURA_INTRARE"}))
        assert result.document_type_code is None


class TestNothingLeavesTheMachine:
    def test_the_provider_makes_no_network_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """R2 — din punct de vedere GDPR trebuie să fie identic cu `mock`."""
        import socket

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("providerul nu are voie să deschidă o conexiune")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)

        assert extract(INVOICE).fields["totalAmount"].value == "1190.00"
