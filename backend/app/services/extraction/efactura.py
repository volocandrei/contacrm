"""Providerul care citește facturi electronice (e-Factura, UBL 2.1).

Spre deosebire de `pdf_text`, aici nu se caută nimic: fiecare valoare stă într-un
element cu nume. Regula „nu ghici" rămâne, dar nu mai are ce să respingă — un
document structurat ori are câmpul, ori nu îl are.

Consecința practică este că **direcția facturii se poate spune**. Un text nu
trimite pe nimeni la stânga sau la dreapta, dar o factură electronică declară
explicit cine este furnizorul și cine cumpărătorul, cu codurile lor fiscale. Care
dintre ei este clientul cabinetului rămâne o întrebare la care răspunde
`client_matching`, cu datele de aici — care sunt sigure, nu presupuse.
"""

from __future__ import annotations

import time
from typing import Final

from app.core.logging import get_logger
from app.domain import efactura as ef
from app.domain.enums import FieldSource
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)

logger = get_logger(__name__)

PROVIDER_NAME: Final = "efactura"

# Tipurile MIME sub care ajunge un XML la noi.
XML_MIME_TYPES: Final = frozenset({"application/xml", "text/xml"})

# Cât se citește din fișier. O factură electronică are zeci de kilooctet, nu
# megaocteți; limita de încărcare rămâne oricum autoritatea.
MAX_BYTES: Final = 8 * 1024 * 1024

# Toate câmpurile pe care ecranul de verificare le așteaptă. Cele negăsite se
# raportează explicit ca goale: `EMPTY` spune „am căutat și nu am găsit".
FIELDS: Final = (
    "documentDate",
    "series",
    "documentNumber",
    "supplierName",
    "supplierTaxId",
    "customerName",
    "customerTaxId",
    "currency",
    "subtotal",
    "vatAmount",
    "totalAmount",
    "referenceMonth",
)

# Perechea între care stă o factură. Care dintre ele se alege depinde de partea pe
# care apare clientul cabinetului — decizie care nu aparține unui cititor de XML.
INVOICE_CODES: Final = ("FACTURA_INTRARE", "FACTURA_IESIRE")


def _empty() -> ExtractedValue:
    return ExtractedValue(value=None, confidence=None, source=FieldSource.EMPTY)


def _read(value: str | None) -> ExtractedValue:
    """O valoare citită dintr-un câmp cu nume.

    `OCR` înseamnă aici, ca peste tot, „citit de pe document" — spre deosebire de
    `AI` (propus de un model) și `DERIVED` (calculat de o regulă). Încrederea este
    întreagă pentru că într-un document structurat nu există altceva: elementul
    fie e acolo, fie nu e.
    """
    if value is None or value == "":
        return _empty()
    return ExtractedValue(value=value, confidence=ef.CERTAIN, source=FieldSource.OCR)


class EFacturaExtractionProvider:
    """Citește o factură electronică. Local, fără rețea, fără ANAF (R2)."""

    def __init__(self, *, known_type_codes: frozenset[str] = frozenset()) -> None:
        self._known_type_codes = known_type_codes

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def handles(self, mime_type: str) -> bool:
        return mime_type in XML_MIME_TYPES

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        started = time.perf_counter()

        if not self.handles(source.mime_type):
            logger.info("extraction_skipped", reason="not_xml", mime_type=source.mime_type)
            return self._nothing_found(self._elapsed(started))

        content = source.stream.read(MAX_BYTES)
        try:
            invoice = ef.parse(content)
        except ef.EFacturaError as exc:
            # Fișierul a trecut de validarea de tip la încărcare, deci este XML —
            # dar nu o factură pe care o putem citi. O a doua încercare va găsi
            # aceiași octeți, deci nu se reia.
            raise ExtractionError(str(exc), retryable=False) from exc

        return self._to_result(invoice, self._elapsed(started))

    @staticmethod
    def _elapsed(started: float) -> int:
        return max(1, int((time.perf_counter() - started) * 1000))

    def _nothing_found(self, duration_ms: int) -> ExtractionResult:
        return ExtractionResult(
            provider=PROVIDER_NAME,
            duration_ms=duration_ms,
            ocr_text=None,
            ocr_confidence=None,
            fields={name: _empty() for name in FIELDS},
        )

    def _to_result(self, invoice: ef.EInvoice, duration_ms: int) -> ExtractionResult:
        fields = {name: _empty() for name in FIELDS}
        fields["documentDate"] = _read(invoice.issue_date)
        fields["series"] = _read(invoice.series)
        fields["documentNumber"] = _read(invoice.number)
        fields["supplierName"] = _read(invoice.supplier.name)
        fields["supplierTaxId"] = _read(invoice.supplier.tax_id)
        fields["customerName"] = _read(invoice.customer.name)
        fields["customerTaxId"] = _read(invoice.customer.tax_id)
        fields["currency"] = _read(invoice.currency)
        fields["subtotal"] = _read(invoice.subtotal)
        fields["vatAmount"] = _read(invoice.vat_amount)
        fields["totalAmount"] = _read(invoice.total)
        # `referenceMonth` rămâne gol: luna contabilă o derivă sistemul din dată,
        # nu documentul (ADR-008).

        # O notă de credit este tot o factură, dar cu semn invers. Nu avem un tip
        # separat pentru storno, iar a o trece drept factură obișnuită ar ascunde
        # exact ce contează: rămâne fără clasificare, adică se uită un om la ea.
        candidates = (
            ()
            if invoice.is_credit_note
            else tuple(code for code in INVOICE_CODES if code in self._known_type_codes)
        )

        return ExtractionResult(
            provider=PROVIDER_NAME,
            duration_ms=duration_ms,
            # Rezumatul ține locul facsimilului: un XML nu se poate privi, dar se
            # poate citi. Merge și în căutarea după conținut.
            ocr_text=invoice.summary,
            ocr_confidence=None,
            document_type_code=None,
            classification_confidence=None,
            classification_source=FieldSource.OCR,
            # Doar când amândouă codurile există: altfel rezolvarea de mai târziu
            # ar putea alege unul pe care scrierea îl refuză.
            document_type_candidates=candidates if len(candidates) == len(INVOICE_CODES) else (),
            fields=fields,
        )


__all__ = [
    "FIELDS",
    "MAX_BYTES",
    "PROVIDER_NAME",
    "XML_MIME_TYPES",
    "EFacturaExtractionProvider",
]
