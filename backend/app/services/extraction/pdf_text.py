"""Extracție din stratul de text al unui PDF (ADR-005, §20, §21).

Primul provider care citește documentul real, nu unul simulat.

**Ce face.** Scoate textul pe care PDF-ul îl poartă deja — cel pus acolo de
programul care l-a generat — și lasă `app/domain/romanian_documents.py` să
recunoască în el ce poate fi recunoscut cu certitudine. Asta acoperă cazul
covârșitor din contabilitate: facturi emise de un ERP, extrase de cont, chitanțe
tipărite în PDF.

**Ce nu face, și de ce contează să fie spus.** Nu este OCR. Un document **scanat**
sau fotografiat nu are strat de text: acolo nu are ce citi, și atunci nu inventează
nimic — întoarce un rezultat gol, iar documentul ajunge la verificare umană cu
toate câmpurile libere. La fel pentru imagini (`jpg`, `png`, `webp`), care sunt
tipuri acceptate la încărcare și pentru care providerul ăsta nu are ce oferi.

Un rezultat gol **nu este o eroare**: documentul a fost primit corect și stocat
corect, doar că mașina nu a putut citi din el. `ExtractionError` este pentru
altceva — un fișier stricat, care chiar nu se poate deschide.

**Nimic nu părăsește mașina** (R2). Nicio cerere de rețea, niciun serviciu extern,
nicio cheie de API. Din punct de vedere GDPR, este același lucru cu `mock`, doar
că rezultatul este adevărat.
"""

from __future__ import annotations

import time
from typing import Final

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.logging import get_logger
from app.domain import romanian_documents as ro
from app.domain.enums import FieldSource
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)

logger = get_logger(__name__)

PROVIDER_NAME: Final = "pdf_text"

# Câte pagini se citesc. Un extras de cont poate avea sute; câmpurile pe care le
# căutăm stau pe primele. Restul ar costa timp fără să adauge nimic.
MAX_PAGES: Final = 20

# Câte caractere din text se păstrează în `ocr_text`. Coloana este indexată pentru
# căutare, iar un extras de cont întreg ar umple baza fără folos.
MAX_TEXT_CHARS: Final = 100_000

# Toate câmpurile pe care ecranul de verificare le așteaptă. Cele pe care nu le
# găsim trebuie raportate explicit ca goale, nu omise: `EMPTY` spune „am căutat și
# nu am găsit", iar absența din dicționar ar spune „nici nu am încercat".
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


def _empty() -> ExtractedValue:
    return ExtractedValue(value=None, confidence=None, source=FieldSource.EMPTY)


def _from(found: ro.Found | None) -> ExtractedValue:
    if found is None:
        return _empty()
    # `OCR` înseamnă „citit de pe document", spre deosebire de `AI` (propus de un
    # model) și `DERIVED` (calculat de o regulă). Nimic de aici nu a fost ghicit.
    return ExtractedValue(value=found.value, confidence=found.confidence, source=FieldSource.OCR)


class PdfTextExtractionProvider:
    """Citește stratul de text al PDF-ului. Nu iese nimic din mașină (R2)."""

    def __init__(self, *, known_type_codes: frozenset[str] = frozenset()) -> None:
        # Tipurile configurate ale organizației (§6): nu propunem un cod pe care
        # cabinetul nu îl are definit.
        self._known_type_codes = known_type_codes

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        started = time.perf_counter()

        def finished() -> int:
            return max(1, int((time.perf_counter() - started) * 1000))

        if source.mime_type != "application/pdf":
            # O imagine este un document valid, doar că fără text de citit. Nu este
            # o eroare a documentului, ci o limită a providerului — și se spune.
            logger.info("extraction_skipped", reason="not_pdf", mime_type=source.mime_type)
            return self._nothing_found(finished())

        text = self._read_text(source)
        if len(text.strip()) < ro.MIN_TEXT_LENGTH:
            # PDF fără strat de text: scanat sau fotografiat. Aici ar începe OCR-ul
            # propriu-zis, care este altă decizie (§4.3, implicații GDPR).
            logger.info("extraction_empty", reason="no_text_layer", sha256=source.sha256[:12])
            return self._nothing_found(finished())

        return self._read_fields(text, finished())

    # ── Citirea PDF-ului ────────────────────────────────────────────────────

    def _read_text(self, source: ExtractionInput) -> str:
        try:
            reader = PdfReader(source.stream)
            if reader.is_encrypted:
                # Se încearcă parola goală, care deblochează PDF-urile protejate
                # doar la editare. Dacă nu merge, chiar nu putem citi.
                try:
                    reader.decrypt("")
                # Orice eșec aici înseamnă același lucru: nu putem citi.
                except Exception:
                    logger.info("extraction_encrypted", sha256=source.sha256[:12])
                    return ""

            pages = reader.pages[:MAX_PAGES]
            return "\n".join(page.extract_text() or "" for page in pages)[:MAX_TEXT_CHARS]
        except PyPdfError as exc:
            # Fișierul nu se poate deschide. Asta **este** o eroare: a trecut de
            # validarea de tip la încărcare, deci ar trebui să fie un PDF valid.
            # Nu se reia: o a doua încercare va găsi aceiași octeți.
            raise ExtractionError(f"PDF ilizibil: {type(exc).__name__}", retryable=False) from exc

    # ── Rezultate ───────────────────────────────────────────────────────────

    def _nothing_found(self, duration_ms: int) -> ExtractionResult:
        """Am citit ce se putea și nu era nimic. Toate câmpurile sunt goale."""
        return ExtractionResult(
            provider=PROVIDER_NAME,
            model=None,
            prompt_version=None,
            duration_ms=duration_ms,
            ocr_text=None,
            # Fără text nu există nici încredere în text. `0.0` ar fi însemnat
            # „am citit foarte prost", ceea ce este altceva decât „nu am citit".
            ocr_confidence=None,
            document_type_code=None,
            classification_confidence=None,
            fields={name: _empty() for name in FIELDS},
        )

    def _read_fields(self, text: str, duration_ms: int) -> ExtractionResult:
        supplier_tax_id, customer_tax_id = ro.find_tax_ids(text)
        series, number = ro.find_series_and_number(text)
        amounts = ro.find_amounts(text)
        document_type = ro.classify(text, known_codes=self._known_type_codes)
        candidates = ro.invoice_candidates(text, known_codes=self._known_type_codes)

        fields = {name: _empty() for name in FIELDS}
        fields["documentDate"] = _from(ro.find_document_date(text))
        fields["series"] = _from(series)
        fields["documentNumber"] = _from(number)
        fields["supplierTaxId"] = _from(supplier_tax_id)
        fields["customerTaxId"] = _from(customer_tax_id)
        fields["currency"] = _from(ro.find_currency(text))
        for name in ("subtotal", "vatAmount", "totalAmount"):
            fields[name] = _from(amounts.get(name))

        # `supplierName`, `customerName` și `referenceMonth` rămân goale deliberat:
        # primele două nu se pot citi fără să ghicim dintr-un bloc de adresă, iar
        # luna contabilă o derivă sistemul din dată, nu documentul (ADR-008).

        return ExtractionResult(
            provider=PROVIDER_NAME,
            model=None,
            prompt_version=None,
            duration_ms=duration_ms,
            ocr_text=text,
            # Textul nu a fost recunoscut, ci citit: nu există incertitudine de
            # recunoaștere. Încrederea pe fiecare câmp spune tot ce e de spus.
            ocr_confidence=None,
            document_type_code=document_type.value if document_type else None,
            classification_confidence=document_type.confidence if document_type else None,
            classification_source=FieldSource.OCR,
            document_type_candidates=candidates,
            fields=fields,
        )


__all__ = ["FIELDS", "MAX_PAGES", "MAX_TEXT_CHARS", "PROVIDER_NAME", "PdfTextExtractionProvider"]
