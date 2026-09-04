"""Despachetarea arhivei ANAF.

Trei lucruri se apără aici, în ordinea în care fac rău dacă lipsesc:

1. **Factura se găsește după conținut, nu după nume.** Convenția de numire a
   ANAF-ului este o convenție; parsarea este singurul criteriu care decide.
2. **O descărcare care nu conține o factură iese ca eroare explicită**, cu
   motivul. Cazul real este factura respinsă, pentru care ANAF pune în arhivă un
   raport de erori — dacă ar ieși ca „XML invalid", cineva ar căuta un defect la
   noi.
3. **O arhivă ostilă este refuzată, nu curățată.** Nu scriem niciun membru pe
   disc, dar o arhivă mică se poate desface în gigabaiți.

Toate arhivele sunt sintetice (§70).
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services.anaf import archive as arch
from tests.anaf_fake import PDF, anaf_zip, invoice_xml, signature_xml


class TestFindingTheInvoice:
    def test_the_invoice_comes_out_of_the_archive(self) -> None:
        unpacked = arch.unpack(anaf_zip("3001", invoice=invoice_xml(number="FCT 118")))

        assert unpacked.invoice is not None
        assert unpacked.invoice.number == "118"
        assert unpacked.invoice.series == "FCT"
        assert unpacked.invoice_name == "3001.xml"

    def test_the_bytes_are_the_ones_from_the_archive(self) -> None:
        """Nu o reserializare: XML-ul stocat trebuie să fie cel primit (§16)."""
        original = invoice_xml()

        assert arch.unpack(anaf_zip("3001", invoice=original)).invoice_xml == original

    def test_the_seal_is_reported_but_not_taken_for_the_invoice(self) -> None:
        unpacked = arch.unpack(anaf_zip("3001", invoice=invoice_xml()))

        assert unpacked.signature_name == "semnatura_3001.xml"

    def test_an_invoice_without_a_seal_still_comes_through(self) -> None:
        """O factură încă nesigilată există și trebuie văzută de contabil."""
        unpacked = arch.unpack(anaf_zip("3001", invoice=invoice_xml(), with_signature=False))

        assert unpacked.signature_name is None
        assert unpacked.invoice is not None

    def test_a_renamed_seal_does_not_hide_the_invoice(self) -> None:
        """Dacă ANAF ar schimba convenția de numire, factura tot se găsește."""
        payload = anaf_zip(
            "3001",
            invoice=None,
            with_signature=False,
            extra={"altceva.xml": signature_xml("3001"), "si-mai-altceva.xml": invoice_xml()},
        )

        assert arch.unpack(payload).invoice is not None


class TestWhatIsNotAnInvoice:
    def test_an_error_report_says_what_it_is(self) -> None:
        """Cazul real: factura a fost respinsă, iar arhiva poartă raportul."""
        payload = anaf_zip(
            "3001",
            invoice=None,
            with_signature=False,
            extra={"3001.xml": b'<?xml version="1.0"?><Erori><Eroare>CIF invalid</Eroare></Erori>'},
        )

        with pytest.raises(arch.AnafArchiveError) as caught:
            arch.unpack(payload)

        assert "nu conține o factură" in str(caught.value)

    def test_an_empty_archive_is_refused(self) -> None:
        with pytest.raises(arch.AnafArchiveError, match="goală"):
            arch.unpack(anaf_zip("3001", invoice=None, with_signature=False))

    def test_something_that_is_not_a_zip_is_refused(self) -> None:
        with pytest.raises(arch.AnafArchiveError, match="ZIP"):
            arch.unpack(PDF)

    def test_a_pdf_inside_the_archive_is_not_mistaken_for_the_invoice(self) -> None:
        payload = anaf_zip("3001", invoice=None, with_signature=False, extra={"3001.pdf": PDF})

        with pytest.raises(arch.AnafArchiveError):
            arch.unpack(payload)


class TestHostileArchives:
    def test_too_many_members_are_refused(self) -> None:
        extra = {f"fisier-{index}.xml": b"<a/>" for index in range(arch.MAX_MEMBERS + 2)}
        payload = anaf_zip("3001", invoice=invoice_xml(), extra=extra)

        with pytest.raises(arch.AnafArchiveError, match="peste limita"):
            arch.unpack(payload)

    def test_a_member_that_unpacks_to_too_much_is_refused(self) -> None:
        """O bombă zip: câțiva kiloocteți care se desfac în zeci de megaocteți."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as writer:
            writer.writestr("3001.xml", b"\0" * (arch.MAX_TOTAL_BYTES + 1))

        with pytest.raises(arch.AnafArchiveError, match="prea mulți octeți"):
            arch.unpack(buffer.getvalue())

    def test_a_single_oversized_member_is_refused_at_read_time(self) -> None:
        """Sub pragul pe arhivă, peste cel pe fișier: se oprește la citire."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as writer:
            writer.writestr("3001.xml", b"x" * (arch.MAX_MEMBER_BYTES + 1024))

        with pytest.raises(arch.AnafArchiveError, match="depășește limita"):
            arch.unpack(buffer.getvalue())
