"""Schemele pentru documente.

Forma exactă a tipurilor `DocumentListItem`, `DocumentDetail`, `DocumentFields` și
`ExtractedField` din `frontend/src/types/domain.ts`.

O abatere deliberată de la contractul actual al frontend-ului: `storagePath` **nu**
se returnează. Câmpul există în tipul TypeScript, dar nu este citit de niciun
component — iar o cale internă de stocare nu are ce căuta într-un răspuns API (§73).
Tipul din frontend se curăță odată cu M5.3.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_serializer, field_validator

from app.domain.document_actions import DocumentAction
from app.domain.enums import (
    DOCUMENT_FIELD_NAMES,
    DocumentErrorCode,
    DocumentSource,
    DocumentStatus,
    FieldSource,
)
from app.schemas.common import ApiModel

# Sumele circulă ca `string` prin API (§72): un Decimal serializat ca număr JSON ar
# trece printr-un float în JavaScript și ar pierde precizie.
MoneyStr = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$")]


class ExtractedFieldOut[T](ApiModel):
    """Valoarea unui câmp plus de unde vine (§22)."""

    value: T | None
    source: FieldSource
    # `null` pentru valori introduse manual sau lipsă — o valoare corectată de om
    # nu are scor de încredere.
    confidence: float | None = None


class DocumentFieldsOut(ApiModel):
    """Toate câmpurile extrase, în ordinea de citire a unei facturi."""

    document_type: ExtractedFieldOut[str]
    document_date: ExtractedFieldOut[str]
    series: ExtractedFieldOut[str]
    document_number: ExtractedFieldOut[str]
    supplier_name: ExtractedFieldOut[str]
    supplier_tax_id: ExtractedFieldOut[str]
    customer_name: ExtractedFieldOut[str]
    customer_tax_id: ExtractedFieldOut[str]
    currency: ExtractedFieldOut[str]
    subtotal: ExtractedFieldOut[str]
    vat_amount: ExtractedFieldOut[str]
    total_amount: ExtractedFieldOut[str]
    reference_month: ExtractedFieldOut[str]


class DocumentTypeOut(ApiModel):
    code: str
    label: str
    is_active: bool
    required_fields: list[str]


class DocumentListItemOut(ApiModel):
    """Rândul din listă. Deliberat ușor: fără OCR, fără câmpuri, fără istoric (§64)."""

    id: uuid.UUID
    original_filename: str
    stored_filename: str | None
    client_id: uuid.UUID | None
    client_name: str | None
    document_type_code: str | None
    document_type_label: str | None
    source: DocumentSource
    received_at: datetime
    document_date: date | None
    reference_month: str | None
    supplier_name: str | None
    document_number: str | None
    total_amount: MoneyStr | None
    currency: str | None
    status: DocumentStatus
    confidence: float | None
    is_duplicate: bool
    review_required: bool

    @field_serializer("total_amount")
    def _serialise_amount(self, value: str | Decimal | None) -> str | None:
        return None if value is None else f"{Decimal(value):.2f}"


class DocumentOcrOut(ApiModel):
    provider: str | None
    confidence: float | None
    # Doar un fragment: textul complet nu se trimite la fiecare deschidere.
    text_preview: str | None


class DocumentExtractionOut(ApiModel):
    provider: str | None
    model: str | None
    prompt_version: str | None
    duration_ms: int | None


class DocumentHistoryEntryOut(ApiModel):
    id: uuid.UUID
    at: datetime
    actor: str
    action: str
    detail: str | None


class DocumentDetailOut(DocumentListItemOut):
    mime_type: str
    file_size: int
    sha256: str
    duplicate_of_id: uuid.UUID | None
    error_code: DocumentErrorCode | None
    processing_attempts: int
    fields: DocumentFieldsOut
    ocr: DocumentOcrOut
    extraction: DocumentExtractionOut
    validation_issues: list[str]
    # Ce poate face **utilizatorul curent** cu documentul, în starea lui de acum.
    # Doar ergonomie de interfață: fiecare rută reverifică (§31).
    available_actions: list[DocumentAction]
    # Ce mai lipsește pentru aprobare — aceeași listă pe care ar returna-o un 422.
    approval_blockers: list[str]
    # `null` când reprocesarea este posibilă; altfel motivul, în cuvintele rutei.
    reprocess_blocked_reason: str | None
    history: list[DocumentHistoryEntryOut]


# ── Filtre și sortare ────────────────────────────────────────────────────────

# Whitelist de sortare (§67): numele vin din exterior și ajung într-un ORDER BY,
# deci nu pot fi concatenate. Cheia este numele din API, valoarea coloana reală.
SORTABLE_FIELDS: dict[str, str] = {
    "receivedAt": "received_at",
    "documentDate": "document_date",
    "status": "status",
    "totalAmount": "total_amount",
    "supplierName": "supplier_name",
    "originalFilename": "original_filename",
    "createdAt": "created_at",
}
SortField = Literal[
    "receivedAt",
    "documentDate",
    "status",
    "totalAmount",
    "supplierName",
    "originalFilename",
    "createdAt",
]


class DocumentFilters(ApiModel):
    """Filtrele pe care le trimite ecranul de documente."""

    q: str | None = Field(default=None, max_length=200)
    client_id: uuid.UUID | None = None
    # Mai multe statusuri deodată: inbox-ul cere „tot ce nu e arhivat".
    # Clientul HTTP serializează listele separate prin virgulă (`value.join(",")`
    # în `api/client.ts`), deci acceptăm ambele forme.
    status: list[DocumentStatus] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            parts: list[str] = []
            for entry in value:
                if isinstance(entry, str):
                    parts.extend(p.strip() for p in entry.split(",") if p.strip())
                else:  # pragma: no cover — deja un membru de enum
                    parts.append(entry)
            return parts
        return value

    source: DocumentSource | None = None
    document_type: str | None = Field(default=None, max_length=64)
    reference_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    year: int | None = Field(default=None, ge=1900, le=2200)
    date_from: date | None = None
    date_to: date | None = None
    review_required: bool | None = None
    is_duplicate: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    sort: SortField = "receivedAt"
    order: Literal["asc", "desc"] = "desc"


__all__ = [
    "DOCUMENT_FIELD_NAMES",
    "SORTABLE_FIELDS",
    "DocumentAction",
    "DocumentDetailOut",
    "DocumentExtractionOut",
    "DocumentFieldsOut",
    "DocumentFilters",
    "DocumentHistoryEntryOut",
    "DocumentListItemOut",
    "DocumentOcrOut",
    "DocumentTypeOut",
    "ExtractedFieldOut",
    "SortField",
]
