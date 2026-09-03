"""Contractul de extracție (ADR-005, §20, §21).

`DocumentProcessingService` nu știe niciodată dacă în spate stă Tesseract, Google
Document AI sau un model de limbaj — vorbește doar cu interfața asta. Providerul
real se adaugă fără să atingă pipeline-ul.

Rezultatul este **tipizat**, nu un dicționar arbitrar: fiecare câmp vine cu propriul
scor de încredere, pentru că ecranul de verificare colorează fiecare câmp separat.
Un total extras cu 95% și o dată extrasă cu 40% nu au ce căuta sub același număr.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol, runtime_checkable

from app.domain.enums import FieldSource


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    """O valoare propusă de provider, cu cât de sigur este pe ea."""

    value: str | None
    confidence: float | None = None
    source: FieldSource = FieldSource.AI

    @property
    def is_present(self) -> bool:
        return self.value is not None and self.value != ""


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    """Ce primește providerul. Deliberat minim: conținutul și tipul lui."""

    stream: BinaryIO
    mime_type: str
    original_filename: str
    # Indiciu de conținut: `sha256` face providerul mock determinist, iar unul real
    # îl poate folosi pentru cache.
    sha256: str


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Tot ce a produs providerul dintr-un document."""

    provider: str
    duration_ms: int
    model: str | None = None
    prompt_version: str | None = None

    # OCR
    ocr_text: str | None = None
    ocr_confidence: float | None = None

    # Clasificare
    document_type_code: str | None = None
    classification_confidence: float | None = None
    # De unde vine tipul propus. Implicit `AI`, pentru că așa a fost singurul
    # provider multă vreme; unul bazat pe reguli spune `OCR` — citit de pe
    # document. Badge-ul „AI 95%" pe o valoare pe care niciun model nu a
    # produs-o este exact minciuna pe care ecranul de verificare promite să nu
    # o spună (§22).
    classification_source: FieldSource = FieldSource.AI
    # Coduri între care documentul sigur se află, dar pe care providerul nu le
    # poate separa singur. O factură își spune numele, nu și direcția: aceea
    # depinde de care parte de pe document este clientul cabinetului, iar asta
    # providerul nu are de unde să știe. Cine poate decide o face mai târziu.
    document_type_candidates: tuple[str, ...] = ()

    # Câmpuri, cheiate pe numele din API (`documentDate`, `totalAmount`, …).
    fields: Mapping[str, ExtractedValue] = field(default_factory=dict)

    @property
    def extraction_confidence(self) -> float | None:
        """Media încrederilor pe câmpurile care au primit o valoare.

        Câmpurile lipsă nu trag media în jos: absența unei serii pe un bon fiscal
        nu înseamnă că extracția a mers prost.
        """
        scores = [
            value.confidence
            for value in self.fields.values()
            if value.is_present and value.confidence is not None
        ]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 4)


class ExtractionError(Exception):
    """Providerul nu a putut produce un rezultat. Poartă un cod structurat (§53)."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class DocumentExtractionProvider(Protocol):
    """Ce trebuie să știe orice provider de OCR/extracție."""

    @property
    def name(self) -> str: ...

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        """Citește documentul și propune valori.

        Aruncă `ExtractionError` dacă nu poate. Nu are voie să modifice nimic în
        baza de date: decizia asupra rezultatului aparține pipeline-ului.
        """
        ...
