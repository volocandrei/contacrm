"""Cititorul local: alege după ce este documentul, nu după configurare.

Un cabinet primește în aceeași zi facturi electronice (XML), PDF-uri digitale și
poze de bonuri. `OCR_PROVIDER` este o singură valoare pentru tot procesul, deci
alegerea nu se poate face acolo: ar însemna ca un cabinet să poată citi ori
XML-urile, ori PDF-urile, dar nu pe amândouă.

Ruta corectă este conținutul. Fiecare cititor spune singur ce tipuri înțelege, iar
primul care recunoaște documentul îl ia. Ce nu recunoaște nimeni întoarce un
rezultat gol — nu o eroare: o poză de bon fiscal este un document valid, doar că
fără text de citit.

Providerul care răspunde apare cu numele lui în `ExtractionResult.provider`, deci
în interfață și în audit se vede cine a citit documentul, nu un „local" generic.
"""

from __future__ import annotations

from typing import Final

from app.services.extraction.base import (
    DocumentExtractionProvider,
    ExtractionInput,
    ExtractionResult,
)
from app.services.extraction.efactura import XML_MIME_TYPES, EFacturaExtractionProvider
from app.services.extraction.pdf_text import PdfTextExtractionProvider

PROVIDER_NAME: Final = "local"

PDF_MIME_TYPES: Final = frozenset({"application/pdf"})


class LocalExtractionProvider:
    """Facturi electronice și PDF-uri, pe aceeași mașină, fără rețea (R2)."""

    def __init__(self, *, known_type_codes: frozenset[str] = frozenset()) -> None:
        self._efactura = EFacturaExtractionProvider(known_type_codes=known_type_codes)
        self._pdf = PdfTextExtractionProvider(known_type_codes=known_type_codes)

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def _reader_for(self, mime_type: str) -> DocumentExtractionProvider:
        if mime_type in XML_MIME_TYPES:
            return self._efactura
        # PDF-ul este și ruta implicită: providerul lui raportează cinstit „nimic
        # de citit" pentru o imagine, ceea ce este exact răspunsul corect acolo.
        return self._pdf

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        return self._reader_for(source.mime_type).extract(source)


__all__ = ["PDF_MIME_TYPES", "PROVIDER_NAME", "LocalExtractionProvider"]
