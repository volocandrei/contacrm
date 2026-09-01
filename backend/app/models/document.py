"""Documente: tipuri, intake, document, versiuni, corecții manuale (§4, §7).

Separarea responsabilităților cerută de arhitectură — fiecare tabel are exact o
treabă, iar amestecarea lor a fost explicit evitată:

- `document_intakes`  — „am primit acest atașament din acest mesaj". Există și când
  fișierul se dovedește nevalid sau duplicat, deci nu produce niciun document.
- `documents`         — documentul contabil: valorile curente ale câmpurilor,
  starea de procesare și starea de verificare.
- `document_versions` — fiecare fișier care a existat vreodată pentru document.
  Originalul nu se suprascrie niciodată (R8).
- `document_field_overrides` — istoricul corecțiilor făcute de oameni.

Proveniența per câmp (AI / OCR / MANUAL / EMPTY) plus scorul de încredere stau în
`documents.field_metadata`, pentru că se citesc la fiecare deschidere a ecranului de
verificare; răspunsul brut al providerului va sta separat, în `document_extractions`
(M5.5), unde se citește rar și se păstrează pentru audit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import DocumentErrorCode, DocumentSource, DocumentStatus, IntakeStatus
from app.models.base import (
    Base,
    EnumString,
    OrganizationMixin,
    SoftDeleteMixin,
    TimestampMixin,
    uuid_pk,
)


class DocumentType(Base, OrganizationMixin, TimestampMixin):
    """Tip de document, administrabil (§6).

    Tabel, nu enum: tipurile se adaugă din administrare, fără deploy. Este legat de
    organizație pentru că un cabinet poate avea tipuri proprii.
    """

    __tablename__ = "document_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_document_types_organization_id_code"),
    )

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Câmpurile fără de care documentul nu poate fi aprobat (§17). Listă de nume din
    # `DOCUMENT_FIELD_NAMES` — validate la scriere, nu doar prin convenție.
    required_fields: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # Reguli suplimentare de validare, per tip. Gol în M5; umplut de M5.5.
    validation_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<DocumentType {self.code}>"


class DocumentIntake(Base, OrganizationMixin, TimestampMixin):
    """Un atașament primit, înainte de a fi (sau a nu fi) un document contabil (§5).

    Idempotența intrărilor externe se rezolvă aici: același mesaj livrat de două ori
    de Microsoft Graph sau de un webhook WhatsApp nu trebuie să producă două
    documente. Cheia este `(source, external_message_id, external_attachment_id)`,
    unică parțial — se aplică doar când id-urile externe există (upload-ul manual nu
    are așa ceva, iar acolo idempotența se face pe SHA-256).
    """

    __tablename__ = "document_intakes"
    __table_args__ = (
        CheckConstraint("source IN ('EMAIL', 'WHATSAPP', 'UPLOAD', 'API')", name="source"),
        CheckConstraint(
            "status IN ('RECEIVED', 'ACCEPTED', 'REJECTED', 'DUPLICATE')", name="status"
        ),
        Index("ix_document_intakes_organization_id_received_at", "organization_id", "received_at"),
        Index("ix_document_intakes_document_id", "document_id"),
    )

    id: Mapped[uuid_pk]
    source: Mapped[DocumentSource] = mapped_column(EnumString(DocumentSource, 16), nullable=False)
    status: Mapped[IntakeStatus] = mapped_column(
        EnumString(IntakeStatus, 16), default=IntakeStatus.RECEIVED, nullable=False
    )
    external_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    external_attachment_id: Mapped[str | None] = mapped_column(String(255), default=None)
    sender: Mapped[str | None] = mapped_column(String(320), default=None)
    recipient: Mapped[str | None] = mapped_column(String(320), default=None)
    subject: Mapped[str | None] = mapped_column(String(512), default=None)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    # Payload-ul brut al furnizorului, pentru diagnostic. Fără conținut de document.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(255), default=None)

    def __repr__(self) -> str:
        return f"<DocumentIntake {self.source} {self.original_filename!r}>"


class Document(Base, OrganizationMixin, TimestampMixin, SoftDeleteMixin):
    """Documentul contabil.

    Coloanele plate (`document_date`, `series`, …) sunt valorile **curente**: după
    ele se filtrează, se sortează și se caută. Proveniența și încrederea fiecăreia
    stau în `field_metadata`.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSING', 'REVIEW_REQUIRED', 'APPROVED', "
            "'ARCHIVED', 'ERROR', 'DUPLICATE', 'REJECTED', 'UNMATCHED')",
            name="status",
        ),
        CheckConstraint(
            "source IN ('EMAIL', 'WHATSAPP', 'UPLOAD', 'API')",
            name="source",
        ),
        CheckConstraint("file_size > 0", name="file_size_positive"),
        # SHA-256 în hex: exact 64 de caractere. O valoare scurtă înseamnă un hash
        # calculat greșit, iar detecția duplicatelor s-ar baza pe el.
        CheckConstraint("char_length(sha256_hash) = 64", name="sha256_length"),
        # „YYYY-MM", nu o dată completă: luna contabilă nu se deduce din `document_date`.
        CheckConstraint(
            "reference_month IS NULL OR reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
            name="reference_month_format",
        ),
        # Un document arhivat trebuie să aibă tot ce înseamnă „arhivat": momentul,
        # numele standardizat, calea logică și copia din stocare. Altfel arhiva ar
        # avea o intrare care nu duce nicăieri.
        CheckConstraint(
            "(status <> 'ARCHIVED') OR ("
            "archived_at IS NOT NULL AND stored_filename IS NOT NULL "
            "AND archive_path IS NOT NULL AND archive_key IS NOT NULL)",
            name="archived_has_filename",
        ),
        # Un duplicat trebuie să spună al cui duplicat este.
        CheckConstraint(
            "(is_duplicate = false) OR (duplicate_of_id IS NOT NULL)",
            name="duplicate_has_origin",
        ),
        # Un document nu poate fi propriul duplicat.
        CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id <> id", name="duplicate_not_self"
        ),
        Index("ix_documents_organization_id_deleted_at", "organization_id", "deleted_at"),
        Index("ix_documents_organization_id_status", "organization_id", "status"),
        Index("ix_documents_sha256_hash", "sha256_hash"),
        Index("ix_documents_client_id_reference_month", "client_id", "reference_month"),
        Index("ix_documents_document_date", "document_date"),
        Index("ix_documents_received_at", "received_at"),
        Index("ix_documents_supplier_tax_id_document_number", "supplier_tax_id", "document_number"),
        Index("ix_documents_document_type_id", "document_type_id"),
        # Două documente nu pot ajunge cu același nume în același dosar de arhivă.
        # Sufixul anti-coliziune se calculează în cod, dar garanția stă aici: două
        # arhivări simultane nu pot alege același nume, oricât de bine ar căuta.
        Index(
            "uq_documents_archive_location",
            "organization_id",
            "archive_path",
            "stored_filename",
            unique=True,
            postgresql_where=text("archive_path IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid_pk]

    # ── Apartenență ─────────────────────────────────────────────────────────
    # CASCADE ar șterge documentele odată cu clientul; RESTRICT nu ar permite
    # ștergerea clientului. SET NULL păstrează documentul ca „neatribuit", ceea ce
    # este exact starea UNMATCHED — probele contabile nu dispar cu clientul.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), default=None
    )
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_types.id", ondelete="RESTRICT"), default=None
    )
    # Legătura către atașamentul din care a venit. Lipsește la upload manual.
    intake_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_intakes.id", ondelete="SET NULL"), default=None
    )

    # ── Stare ───────────────────────────────────────────────────────────────
    status: Mapped[DocumentStatus] = mapped_column(
        EnumString(DocumentStatus, 24), default=DocumentStatus.RECEIVED, nullable=False
    )
    source: Mapped[DocumentSource] = mapped_column(EnumString(DocumentSource, 16), nullable=False)
    review_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_duplicate: Mapped[bool] = mapped_column(default=False, nullable=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    error_code: Mapped[DocumentErrorCode | None] = mapped_column(
        EnumString(DocumentErrorCode, 32), default=None
    )
    error_detail: Mapped[str | None] = mapped_column(String(512), default=None)
    # De câte ori a fost procesat (§55). Crește la fiecare reprocesare.
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Motivele pentru care documentul a ajuns la verificare (§17).
    validation_issues: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # ── Fișier ──────────────────────────────────────────────────────────────
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Numele standardizat, generat la arhivare. Null până atunci.
    stored_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    # Cheie abstractă în StorageProvider, NU o cale de filesystem (§74).
    # Nu se expune niciodată prin API (§73).
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    archive_key: Mapped[str | None] = mapped_column(String(1024), default=None)
    # Calea logică din arhivă, lizibilă pentru om: `/ARHIVA/{an}/{lună}/{client}/`.
    # Nu este o cale de filesystem și nu se folosește ca atare (§74) — este locul
    # documentului în structura pe care o vede contabilul, și domeniul în care
    # numele trebuie să fie unic.
    archive_path: Mapped[str | None] = mapped_column(String(512), default=None)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── Câmpuri extrase ─────────────────────────────────────────────────────
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    document_date: Mapped[date | None] = mapped_column(default=None)
    # „YYYY-MM". Luna contabilă, diferită de `document_date` (§18).
    # TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: regula de derivare.
    reference_month: Mapped[str | None] = mapped_column(String(7), default=None)
    series: Mapped[str | None] = mapped_column(String(32), default=None)
    document_number: Mapped[str | None] = mapped_column(String(64), default=None)
    supplier_name: Mapped[str | None] = mapped_column(String(255), default=None)
    supplier_tax_id: Mapped[str | None] = mapped_column(String(32), default=None)
    customer_name: Mapped[str | None] = mapped_column(String(255), default=None)
    customer_tax_id: Mapped[str | None] = mapped_column(String(32), default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    # NUMERIC, niciodată float (§72).
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), default=None)
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), default=None)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), default=None)

    # Proveniența și încrederea per câmp: {"documentDate": {"source": "AI",
    # "confidence": 0.83}, …}. Citită la fiecare deschidere a ecranului de verificare.
    field_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # ── OCR / AI ────────────────────────────────────────────────────────────
    ocr_provider: Mapped[str | None] = mapped_column(String(64), default=None)
    ocr_confidence: Mapped[float | None] = mapped_column(default=None)
    # Textul OCR poate fi mare: nu se selectează în listă (§64).
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None, deferred=True)
    ai_provider: Mapped[str | None] = mapped_column(String(64), default=None)
    ai_model: Mapped[str | None] = mapped_column(String(128), default=None)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(32), default=None)
    ai_classification_confidence: Mapped[float | None] = mapped_column(default=None)
    ai_extraction_confidence: Mapped[float | None] = mapped_column(default=None)
    extraction_duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    # ── Verificare și aprobare ──────────────────────────────────────────────
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    rejected_reason: Mapped[str | None] = mapped_column(String(512), default=None)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)

    document_type: Mapped[DocumentType | None] = relationship(lazy="joined")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )

    @property
    def confidence(self) -> float | None:
        """Încrederea agregată afișată în listă.

        Cea a extracției, dacă există; altfel a OCR-ului. Un document corectat
        manual nu are încredere agregată — vezi `field_metadata`.
        """
        return (
            self.ai_extraction_confidence
            if self.ai_extraction_confidence is not None
            else self.ocr_confidence
        )

    def __repr__(self) -> str:
        return f"<Document {self.original_filename!r} {self.status}>"


class DocumentVersion(Base, TimestampMixin):
    """Fiecare fișier care a existat pentru un document (§17, R8).

    Originalul rămâne recuperabil oricât de multe reprocesări sau reîncărcări ar
    urma. Nu se șterge fizic nimic de aici.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_id_version_number"
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("char_length(sha256_hash) = 64", name="sha256_length"),
        Index("ix_document_versions_document_id", "document_id"),
    )

    id: Mapped[uuid_pk]
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # `original` pentru fișierul primit, `archive` pentru cel standardizat.
    kind: Mapped[str] = mapped_column(String(16), default="original", nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")

    def __repr__(self) -> str:
        return f"<DocumentVersion {self.document_id} v{self.version_number} {self.kind}>"


class DocumentFieldOverride(Base):
    """O corecție făcută de un om asupra unui câmp extras (§32).

    Se păstrează separat de audit: auditul spune „cineva a modificat documentul",
    iar tabelul ăsta spune exact ce câmp, de la ce valoare la ce valoare — datele
    de aici alimentează măsurarea calității extracției.
    """

    __tablename__ = "document_field_overrides"
    __table_args__ = (
        Index("ix_document_field_overrides_document_id", "document_id"),
        Index("ix_document_field_overrides_field_name", "field_name"),
    )

    id: Mapped[uuid_pk]
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, default=None)
    new_value: Mapped[str | None] = mapped_column(Text, default=None)
    # Ce încredere avea valoarea în momentul corecției — arată cât de sigur era
    # modelul când a greșit.
    previous_confidence: Mapped[float | None] = mapped_column(default=None)
    previous_source: Mapped[str | None] = mapped_column(String(16), default=None)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    changed_at: Mapped[datetime] = mapped_column(nullable=False)

    def __repr__(self) -> str:
        return f"<DocumentFieldOverride {self.field_name} doc={self.document_id}>"


class DocumentProcessingJob(Base, TimestampMixin):
    """O încercare de procesare (§39, §55).

    Există pentru trei întrebări la care `processing_attempts` nu răspunde: de ce a
    eșuat a doua încercare, cât a durat, și dacă cererea curentă nu cumva a mai fost
    tratată o dată.

    `idempotency_key` este ce oprește dubla procesare: două livrări ale aceleiași
    cereri produc aceeași cheie, iar unicitatea o respinge pe a doua.
    """

    __tablename__ = "document_processing_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_document_processing_jobs_idempotency_key"),
        CheckConstraint("status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')", name="status"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        Index("ix_document_processing_jobs_document_id", "document_id"),
        Index("ix_document_processing_jobs_status", "status"),
    )

    id: Mapped[uuid_pk]
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(32), default="EXTRACTION", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Ce s-a întâmplat, structurat. Fără traceback (§53).
    error_code: Mapped[str | None] = mapped_column(String(32), default=None)
    error_detail: Mapped[str | None] = mapped_column(String(512), default=None)
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    def __repr__(self) -> str:
        return f"<DocumentProcessingJob {self.document_id} #{self.attempt} {self.status}>"
