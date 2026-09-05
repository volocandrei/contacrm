"""Local întâi, model doar când nu e nimic de citit (ADR-005).

**Ordinea nu este o optimizare, este o politică.** Un PDF emis de un ERP poartă
textul în el: se citește pe mașina cabinetului, fără rețea, fără cheie, fără ca
documentul să părăsească sediul (R2). Ar fi absurd — și scump, și mai puțin
sigur — să trimitem la un model exterior un document pe care îl putem citi exact
aici.

Modelul intră doar acolo unde local-ul întoarce gol: **poze și scanuri**. Adică
exact ce trimit clienții prin linkul de încărcare, și exact ce ajungea la
verificare cu toate câmpurile libere.

**Ce înseamnă „gol".** Nu „a citit puțin", ci „nu a citit nimic": fără text și
fără niciun câmp completat. Un PDF din care s-au scos două câmpuri din cinci nu
se retrimite nicăieri — restul le completează omul, iar documentul a rămas în
cabinet.
"""

from __future__ import annotations

from typing import Final

from app.core.logging import get_logger
from app.services.extraction.base import (
    DocumentExtractionProvider,
    ExtractionInput,
    ExtractionResult,
)

logger = get_logger(__name__)

PROVIDER_NAME: Final = "hybrid"


def read_nothing(result: ExtractionResult) -> bool:
    """A ieșit ceva din document, orice?

    Textul singur nu este de ajuns ca răspuns: un PDF poate purta un antet și
    nimic altceva. Dar un câmp completat înseamnă că providerul chiar a înțeles
    documentul, iar atunci nu are rost să-l mai trimitem nicăieri.
    """
    if result.ocr_text and result.ocr_text.strip():
        return False
    return not any(value.is_present for value in result.fields.values())


class HybridExtractionProvider:
    """Citește local; cheamă modelul doar pentru ce nu are strat de text."""

    def __init__(
        self,
        *,
        local: DocumentExtractionProvider,
        vision: DocumentExtractionProvider,
    ) -> None:
        self._local = local
        self._vision = vision

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def extract(self, source: ExtractionInput) -> ExtractionResult:
        local = self._local.extract(source)
        if not read_nothing(local):
            return local

        # Fluxul se poate consuma o singură dată, iar providerul local tocmai
        # l-a citit până la capăt.
        source.stream.seek(0)
        logger.info("hybrid_falling_back_to_model", mime_type=source.mime_type)
        return self._vision.extract(source)


__all__ = ["PROVIDER_NAME", "HybridExtractionProvider", "read_nothing"]
