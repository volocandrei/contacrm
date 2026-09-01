"""Câmpurile extrase: citire și scriere (§21, §32).

Un singur loc care știe corespondența dintre numele din API (camelCase, cele pe care
le folosește ecranul de verificare) și coloanele din `documents`. Fără el, maparea
s-ar rescrie în fiecare rută și ar diverge la prima adăugare de câmp.

Două reguli care contează pentru operator:

- o valoare corectată de om devine `MANUAL` și **pierde scorul de încredere**. Un
  câmp corectat nu trebuie să pară niciodată extras de model (§32);
- fiecare corecție se scrie în `document_field_overrides`, împreună cu încrederea pe
  care o avea valoarea în momentul respectiv — de acolo se va putea măsura unde
  greșește extracția și cât de sigură era când greșea.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.domain.enums import DOCUMENT_FIELD_NAMES, FieldSource
from app.models.document import Document, DocumentFieldOverride, DocumentType
from app.schemas.document import DocumentFieldsOut, ExtractedFieldOut


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Cum se leagă un câmp din API de o coloană și cum se convertește."""

    api_name: str
    column: str
    kind: str  # "text" | "date" | "month" | "money" | "type"


# Ordinea este cea din `DocumentFields` (frontend) și din `DOCUMENT_FIELD_NAMES`.
FIELD_SPECS: Final[tuple[FieldSpec, ...]] = (
    # `documentType` nu e o coloană de text: trimite la `document_types`.
    FieldSpec("documentType", "document_type_id", "type"),
    FieldSpec("documentDate", "document_date", "date"),
    FieldSpec("series", "series", "text"),
    FieldSpec("documentNumber", "document_number", "text"),
    FieldSpec("supplierName", "supplier_name", "text"),
    FieldSpec("supplierTaxId", "supplier_tax_id", "text"),
    FieldSpec("customerName", "customer_name", "text"),
    FieldSpec("customerTaxId", "customer_tax_id", "text"),
    FieldSpec("currency", "currency", "text"),
    FieldSpec("subtotal", "subtotal", "money"),
    FieldSpec("vatAmount", "vat_amount", "money"),
    FieldSpec("totalAmount", "total_amount", "money"),
    FieldSpec("referenceMonth", "reference_month", "month"),
)

SPEC_BY_NAME: Final[dict[str, FieldSpec]] = {spec.api_name: spec for spec in FIELD_SPECS}

# Lungimile coloanelor, ca o valoare prea lungă să fie respinsă cu un mesaj clar
# în loc să producă o eroare de bază de date.
_MAX_LENGTH: Final[dict[str, int]] = {
    "series": 32,
    "document_number": 64,
    "supplier_name": 255,
    "supplier_tax_id": 32,
    "customer_name": 255,
    "customer_tax_id": 32,
    "currency": 3,
}


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# ── Citire ───────────────────────────────────────────────────────────────────


def read_fields(document: Document) -> DocumentFieldsOut:
    """Construiește `DocumentFields` din coloane plus `field_metadata`."""
    metadata: dict[str, Any] = document.field_metadata or {}
    payload: dict[str, ExtractedFieldOut[str]] = {}

    for spec in FIELD_SPECS:
        if spec.kind == "type":
            raw: Any = document.document_type.code if document.document_type else None
        else:
            raw = getattr(document, spec.column)

        entry = metadata.get(spec.api_name) or {}
        source = FieldSource(entry.get("source", FieldSource.EMPTY.value))
        confidence = entry.get("confidence")

        value = _as_text(raw)
        if value is None:
            # Fără valoare nu există proveniență: câmpul e pur și simplu gol.
            source, confidence = FieldSource.EMPTY, None
        elif source is FieldSource.MANUAL:
            # O valoare corectată de om nu are scor de încredere (§32).
            confidence = None

        payload[spec.api_name] = ExtractedFieldOut[str](
            value=value, source=source, confidence=confidence
        )

    # `DocumentFieldsOut` are câmpuri snake_case cu alias camelCase.
    return DocumentFieldsOut.model_validate(payload)


# ── Scriere ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FieldUpdate:
    field: str
    value: str | None


@dataclass(frozen=True, slots=True)
class AppliedChange:
    field: str
    old_value: str | None
    new_value: str | None


class DocumentFieldWriter:
    """Aplică modificările de câmpuri, cu urmă completă."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def apply(
        self,
        document: Document,
        updates: list[FieldUpdate],
        *,
        changed_by: uuid.UUID | None,
        document_types: dict[str, DocumentType],
    ) -> list[AppliedChange]:
        """Scrie valorile noi și întoarce doar ce s-a schimbat efectiv.

        Un câmp trimis cu aceeași valoare nu produce nici override, nici audit — un
        „salvează" fără modificări nu trebuie să umple istoricul.
        """
        metadata: dict[str, Any] = dict(document.field_metadata or {})
        changes: list[AppliedChange] = []
        now = datetime.now(UTC)

        for update in updates:
            spec = SPEC_BY_NAME.get(update.field)
            if spec is None:
                raise ValidationError(
                    "Câmp necunoscut.", {"updates": [f"Câmp inexistent: {update.field}"]}
                )

            old_text = self._current_text(document, spec)
            new_text = (update.value or "").strip() or None
            if old_text == new_text:
                continue

            previous = metadata.get(spec.api_name) or {}
            self._write(document, spec, new_text, document_types)

            self.session.add(
                DocumentFieldOverride(
                    document_id=document.id,
                    field_name=spec.api_name,
                    old_value=old_text,
                    new_value=new_text,
                    previous_confidence=previous.get("confidence"),
                    previous_source=previous.get("source"),
                    changed_by=changed_by,
                    changed_at=now,
                )
            )

            metadata[spec.api_name] = (
                {"source": FieldSource.MANUAL.value, "confidence": None}
                if new_text is not None
                else {"source": FieldSource.EMPTY.value, "confidence": None}
            )
            changes.append(
                AppliedChange(field=spec.api_name, old_value=old_text, new_value=new_text)
            )

        if changes:
            document.field_metadata = metadata
        return changes

    # ── Conversii ───────────────────────────────────────────────────────────

    def _current_text(self, document: Document, spec: FieldSpec) -> str | None:
        if spec.kind == "type":
            return document.document_type.code if document.document_type else None
        return _as_text(getattr(document, spec.column))

    def _write(
        self,
        document: Document,
        spec: FieldSpec,
        value: str | None,
        document_types: dict[str, DocumentType],
    ) -> None:
        if spec.kind == "type":
            if value is None:
                document.document_type_id = None
                document.document_type = None
                return
            document_type = document_types.get(value)
            if document_type is None:
                raise ValidationError(
                    "Tip de document necunoscut.",
                    {"documentType": [f"Tipul {value} nu există sau nu este activ."]},
                )
            document.document_type_id = document_type.id
            document.document_type = document_type
            return

        if value is None:
            setattr(document, spec.column, None)
            return

        if spec.kind == "date":
            setattr(document, spec.column, self._parse_date(spec, value))
        elif spec.kind == "month":
            setattr(document, spec.column, self._parse_month(spec, value))
        elif spec.kind == "money":
            setattr(document, spec.column, self._parse_money(spec, value))
        else:
            limit = _MAX_LENGTH.get(spec.column)
            if limit is not None and len(value) > limit:
                raise ValidationError(
                    "Valoare prea lungă.",
                    {spec.api_name: [f"Maximum {limit} caractere."]},
                )
            setattr(document, spec.column, value)

    def _parse_date(self, spec: FieldSpec, value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(
                "Dată invalidă.", {spec.api_name: ["Format așteptat: AAAA-LL-ZZ."]}
            ) from exc

    def _parse_month(self, spec: FieldSpec, value: str) -> str:
        # „YYYY-MM". Luna contabilă nu se deduce din `document_date` (§18).
        parts = value.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValidationError(
                "Perioadă invalidă.", {spec.api_name: ["Format așteptat: AAAA-LL."]}
            )
        try:
            year, month = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValidationError(
                "Perioadă invalidă.", {spec.api_name: ["Format așteptat: AAAA-LL."]}
            ) from exc
        if not (1 <= month <= 12) or not (1900 <= year <= 2200):
            raise ValidationError(
                "Perioadă invalidă.", {spec.api_name: ["Lună sau an în afara intervalului."]}
            )
        return f"{year:04d}-{month:02d}"

    def _parse_money(self, spec: FieldSpec, value: str) -> Decimal:
        try:
            amount = Decimal(value.replace(",", "."))
        except InvalidOperation as exc:
            raise ValidationError(
                "Sumă invalidă.", {spec.api_name: ["Se aștepta un număr."]}
            ) from exc
        if amount.is_nan() or amount.is_infinite():
            raise ValidationError("Sumă invalidă.", {spec.api_name: ["Se aștepta un număr."]})
        # NUMERIC(18, 2): 16 cifre înainte de virgulă.
        if abs(amount) >= Decimal("1e16"):
            raise ValidationError("Sumă prea mare.", {spec.api_name: ["Valoare în afara limitei."]})
        return amount.quantize(Decimal("0.01"))


# ── Validare pentru aprobare ─────────────────────────────────────────────────


def missing_required_fields(document: Document) -> list[str]:
    """Câmpurile cerute de tipul documentului care încă lipsesc (§17, §22).

    Fără tip nu se poate valida nimic: tipul însuși devine cerința.
    """
    if document.document_type is None:
        return ["documentType"]

    required: list[str] = list(document.document_type.required_fields or [])
    missing: list[str] = []
    for name in required:
        spec = SPEC_BY_NAME.get(name)
        if spec is None:  # pragma: no cover — configurare greșită a tipului
            continue
        if spec.kind == "type":
            if document.document_type is None:
                missing.append(name)
        elif getattr(document, spec.column) is None:
            missing.append(name)
    return missing


__all__ = [
    "DOCUMENT_FIELD_NAMES",
    "FIELD_SPECS",
    "SPEC_BY_NAME",
    "AppliedChange",
    "DocumentFieldWriter",
    "FieldUpdate",
    "missing_required_fields",
    "read_fields",
]
