"""Validarea unui document extras (§22, §23).

Nu toate câmpurile sunt obligatorii, și nu pe toate tipurile. Un bon fiscal nu are
furnizor cu CUI, un contract nu are total. Cerințele vin din `document_types`, deci
se administrează fără deploy — nu sunt scrise aici.

Pragurile de încredere vin din configurare (§23), nu din cod și cu atât mai puțin
din frontend.

**Nicio regulă fiscală nu este implementată aici.** Singura verificare numerică este
identitatea aritmetică `subtotal + TVA = total`, care nu depinde de nicio cotă și nu
presupune nimic despre regimul de taxare. Sistemul nu calculează niciodată TVA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.core.config import settings
from app.models.document import Document
from app.services.document_fields import missing_required_fields


class ValidationLevel(StrEnum):
    """Cât de departe este documentul de a putea fi aprobat."""

    # Nimic de semnalat.
    VALID = "VALID"
    # Se poate aproba, dar un om ar trebui să se uite.
    WARNING = "WARNING"
    # Nu poate fi aprobat așa cum este.
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    level: ValidationLevel
    issues: list[str] = field(default_factory=list)

    @property
    def blocks_approval(self) -> bool:
        return self.level is ValidationLevel.INVALID


class DocumentValidationService:
    """Decide dacă un document este gata și dacă are nevoie de ochi omenești."""

    def __init__(
        self,
        *,
        auto_threshold: float | None = None,
        review_threshold: float | None = None,
    ) -> None:
        self.auto_threshold = (
            settings.confidence_auto_threshold if auto_threshold is None else auto_threshold
        )
        self.review_threshold = (
            settings.confidence_review_threshold if review_threshold is None else review_threshold
        )

    # ── Validare ────────────────────────────────────────────────────────────

    def validate(self, document: Document) -> ValidationOutcome:
        issues: list[str] = []
        level = ValidationLevel.VALID

        missing = missing_required_fields(document)
        if missing:
            issues.append("Câmpuri obligatorii lipsă: " + ", ".join(missing))
            level = ValidationLevel.INVALID

        confidence = document.ai_extraction_confidence
        if confidence is not None:
            if confidence < self.review_threshold:
                issues.append(f"Încredere scăzută la extracție ({round(confidence * 100)}%).")
                level = max(level, ValidationLevel.WARNING, key=_severity)
            elif confidence < self.auto_threshold:
                issues.append(f"Încredere sub pragul automat ({round(confidence * 100)}%).")
                level = max(level, ValidationLevel.WARNING, key=_severity)

        arithmetic = self._check_amounts(document)
        if arithmetic is not None:
            issues.append(arithmetic)
            level = max(level, ValidationLevel.WARNING, key=_severity)

        if document.client_id is None:
            issues.append("Clientul nu a fost identificat.")
            level = max(level, ValidationLevel.WARNING, key=_severity)

        return ValidationOutcome(level=level, issues=issues)

    def _check_amounts(self, document: Document) -> str | None:
        """`subtotal + TVA = total`.

        Aritmetică pură: nu presupune nicio cotă și nu calculează TVA. Dacă cele trei
        valori sunt prezente și nu se potrivesc, cel puțin una a fost citită greșit.
        """
        subtotal, vat, total = document.subtotal, document.vat_amount, document.total_amount
        if subtotal is None or vat is None or total is None:
            return None
        # Toleranță de un ban, pentru rotunjirile de pe document.
        if abs((subtotal + vat) - total) > Decimal("0.01"):
            return (
                f"Sumele nu se potrivesc: {subtotal} + {vat} ≠ {total}. Verifică valorile citite."
            )
        return None

    # ── Decizia de verificare (§23) ─────────────────────────────────────────

    def needs_review(self, document: Document, outcome: ValidationOutcome) -> bool:
        """Trebuie să se uite un om înainte de aprobare?

        Da, în toate cazurile în afară de: încredere peste pragul automat, validare
        curată, client identificat — **și** aprobarea automată explicit activată.
        """
        if outcome.level is not ValidationLevel.VALID:
            return True
        if document.client_id is None:
            return True
        confidence = document.ai_extraction_confidence
        if confidence is None or confidence < self.auto_threshold:
            return True
        return not settings.auto_approve_enabled


def _severity(level: ValidationLevel) -> int:
    return {ValidationLevel.VALID: 0, ValidationLevel.WARNING: 1, ValidationLevel.INVALID: 2}[level]
