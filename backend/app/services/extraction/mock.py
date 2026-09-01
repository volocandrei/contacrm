"""Provider de extracție simulat (ADR-005, §20).

Produce date sintetice plauzibile, **deterministe pe conținutul fișierului**: același
document dă mereu același rezultat, deci testele sunt reproductibile și o reprocesare
nu schimbă valorile de la sine.

Nimic din ce iese de aici nu are valoare contabilă. Sumele sunt inventate pornind de
la hash, iar TVA-ul este calculat cu o cotă fixă **doar ca cifrele să fie coerente
între ele** — sistemul real nu calculează niciodată TVA, îl extrage din document.
TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from app.domain.enums import FieldSource
from app.services.extraction.base import (
    ExtractedValue,
    ExtractionError,
    ExtractionInput,
    ExtractionResult,
)

PROVIDER_NAME: Final = "mock"
PROMPT_VERSION: Final = "v1"

# Cotă folosită DOAR ca subtotal + TVA = total în datele sintetice.
_MOCK_VAT_RATE: Final = Decimal("0.19")

_SUPPLIERS: Final = (
    "Distribuție Rapidă SRL",
    "Șerban Market SRL",
    "Alfa Furnizor SRL",
    "Transport Model SRL",
    "Catering Sintetic SRL",
)
_SERIES: Final = ("FCT", "BX", "AV", "TM")
_CURRENCIES: Final = ("RON", "RON", "RON", "EUR")

# Ce tip se propune, în funcție de un octet din hash. Ordinea nu are semnificație.
_TYPES: Final = (
    "FACTURA_INTRARE",
    "FACTURA_INTRARE",
    "FACTURA_IESIRE",
    "BON_FISCAL",
    "EXTRAS_CONT",
    "CHITANTA",
)


class MockDocumentExtractionProvider:
    """Extracție simulată. Nu iese nimic din mașină (R2)."""

    def __init__(self, *, base_confidence: float | None = None) -> None:
        # Permite testelor să forțeze un scor, fără să atingă restul logicii.
        self._forced_confidence = base_confidence

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        started = time.perf_counter()

        digest = source.sha256
        if len(digest) < 32:
            raise ExtractionError("Hash invalid pentru extracție.", retryable=False)

        seed = [int(digest[i : i + 2], 16) for i in range(0, 32, 2)]

        # Un document imposibil de citit: 1 din 32, ca fluxul de eroare să fie
        # exersat de setul de date sintetice.
        if seed[0] % 32 == 0:
            raise ExtractionError("OCR eșuat: imagine neclară.")

        confidence = self._forced_confidence
        type_code = _TYPES[seed[1] % len(_TYPES)]
        supplier = _SUPPLIERS[seed[2] % len(_SUPPLIERS)]
        series = _SERIES[seed[3] % len(_SERIES)]
        number = str(1000 + seed[4] * 7 + seed[5])
        document_day = date(2026, 1, 1) + timedelta(days=seed[6] % 240)

        subtotal_cents = 5_000 + seed[7] * 1_337
        subtotal = (Decimal(subtotal_cents) / 100).quantize(Decimal("0.01"))
        vat = (subtotal * _MOCK_VAT_RATE).quantize(Decimal("0.01"))
        total = subtotal + vat

        def scored(value: str | None, offset: int) -> ExtractedValue:
            if value is None:
                return ExtractedValue(value=None, confidence=None, source=FieldSource.EMPTY)
            score = (
                confidence
                if confidence is not None
                # 0.55 … 0.99, distribuit pe octeții hash-ului.
                else round(0.55 + (seed[offset % len(seed)] % 45) / 100, 2)
            )
            return ExtractedValue(value=value, confidence=score, source=FieldSource.AI)

        # Bonurile fiscale și extrasele nu au serie sau cumpărător: providerul nu
        # inventează câmpuri care nu există pe hârtie.
        has_series = type_code in {"FACTURA_INTRARE", "FACTURA_IESIRE"}
        has_customer = type_code == "FACTURA_IESIRE"

        fields = {
            "documentDate": scored(document_day.isoformat(), 8),
            "series": scored(series if has_series else None, 9),
            "documentNumber": scored(number, 10),
            "supplierName": scored(supplier, 11),
            "supplierTaxId": scored(f"RO{10_000_000 + seed[12] * 131}", 12),
            "customerName": scored("Client Sintetic SRL" if has_customer else None, 13),
            "customerTaxId": scored(None, 14),
            "currency": scored(_CURRENCIES[seed[14] % len(_CURRENCIES)], 14),
            "subtotal": scored(f"{subtotal:.2f}", 15),
            "vatAmount": scored(f"{vat:.2f}", 15),
            "totalAmount": scored(f"{total:.2f}", 15),
            # Luna contabilă nu se deduce din dată fără o regulă configurată (§18):
            # providerul o propune doar dacă documentul o poartă explicit — ceea ce
            # în datele sintetice nu se întâmplă.
            "referenceMonth": ExtractedValue(value=None, source=FieldSource.EMPTY),
        }

        ocr_text = (
            f"{type_code.replace('_', ' ')}\n"
            f"Furnizor: {supplier}\n"
            f"Seria {series} nr. {number}\n"
            f"Data: {document_day.isoformat()}\n"
            f"Total de plata: {total} RON\n"
            "— text simulat, fara valoare contabila —"
        )

        return ExtractionResult(
            provider=PROVIDER_NAME,
            model="mock-1",
            prompt_version=PROMPT_VERSION,
            duration_ms=max(1, int((time.perf_counter() - started) * 1000)),
            ocr_text=ocr_text,
            ocr_confidence=round(0.70 + (seed[0] % 30) / 100, 2),
            document_type_code=type_code,
            classification_confidence=round(0.60 + (seed[1] % 40) / 100, 2),
            fields=fields,
        )
