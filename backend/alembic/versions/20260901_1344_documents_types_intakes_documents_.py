"""documents: types, intakes, documents, versions, field_overrides

`documents` și `document_intakes` se referă reciproc, deci una dintre chei se
adaugă după crearea ambelor tabele.

Indexurile trigram refolosesc `app_unaccent`, funcția IMMUTABLE introdusă de
migrarea CRM — căutarea documentelor trebuie să se comporte ca cea de clienți:
„distributie" găsește „Distribuție".

Revision ID: b8ab4b1e400c
Revises: acb7bb07feaf
Create Date: 2026-09-01 13:44
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8ab4b1e400c"
down_revision: str | None = "acb7bb07feaf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())

DOCUMENT_STATUSES = (
    "RECEIVED",
    "PROCESSING",
    "REVIEW_REQUIRED",
    "APPROVED",
    "ARCHIVED",
    "ERROR",
    "DUPLICATE",
    "REJECTED",
    "UNMATCHED",
)
DOCUMENT_SOURCES = ("EMAIL", "WHATSAPP", "UPLOAD", "API")
INTAKE_STATUSES = ("RECEIVED", "ACCEPTED", "REJECTED", "DUPLICATE")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # ── document_types ──────────────────────────────────────────────────────
    op.create_table(
        "document_types",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("required_fields", JSONB, server_default="[]", nullable=False),
        sa.Column("validation_rules", JSONB, server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_document_types_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_types"),
        sa.UniqueConstraint(
            "organization_id", "code", name="uq_document_types_organization_id_code"
        ),
    )
    op.create_index("ix_document_types_organization_id", "document_types", ["organization_id"])

    # ── document_intakes ────────────────────────────────────────────────────
    # `document_id` se adaugă mai jos, după crearea tabelei `documents`.
    op.create_table(
        "document_intakes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="RECEIVED", nullable=False),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("external_attachment_id", sa.String(255), nullable=True),
        sa.Column("sender", sa.String(320), nullable=True),
        sa.Column("recipient", sa.String(320), nullable=True),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", JSONB, nullable=True),
        sa.Column("document_id", UUID, nullable=True),
        sa.Column("rejection_reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_document_intakes_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_intakes"),
        sa.CheckConstraint(_in_list("source", DOCUMENT_SOURCES), name="source"),
        sa.CheckConstraint(_in_list("status", INTAKE_STATUSES), name="status"),
    )
    op.create_index("ix_document_intakes_organization_id", "document_intakes", ["organization_id"])
    op.create_index(
        "ix_document_intakes_organization_id_received_at",
        "document_intakes",
        ["organization_id", "received_at"],
    )
    op.create_index("ix_document_intakes_document_id", "document_intakes", ["document_id"])
    # Idempotența intrărilor externe (§6): același mesaj livrat de două ori nu
    # produce două documente. Parțial, pentru că upload-ul manual nu are id-uri
    # externe — acolo idempotența se face pe SHA-256.
    op.create_index(
        "uq_document_intakes_external_ref",
        "document_intakes",
        ["organization_id", "source", "external_message_id", "external_attachment_id"],
        unique=True,
        postgresql_where=sa.text(
            "external_message_id IS NOT NULL AND external_attachment_id IS NOT NULL"
        ),
    )

    # ── documents ───────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("document_type_id", UUID, nullable=True),
        sa.Column("intake_id", UUID, nullable=True),
        # Stare
        sa.Column("status", sa.String(24), server_default="RECEIVED", nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("review_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_duplicate", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("duplicate_of_id", UUID, nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_detail", sa.String(512), nullable=True),
        sa.Column("processing_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("validation_issues", JSONB, server_default="[]", nullable=False),
        # Fișier
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("archive_key", sa.String(1024), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        # Câmpuri extrase
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("reference_month", sa.String(7), nullable=True),
        sa.Column("series", sa.String(32), nullable=True),
        sa.Column("document_number", sa.String(64), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("supplier_tax_id", sa.String(32), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_tax_id", sa.String(32), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=True),
        sa.Column("vat_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("field_metadata", JSONB, server_default="{}", nullable=False),
        # OCR / AI
        sa.Column("ocr_provider", sa.String(64), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("ai_provider", sa.String(64), nullable=True),
        sa.Column("ai_model", sa.String(128), nullable=True),
        sa.Column("ai_prompt_version", sa.String(32), nullable=True),
        sa.Column("ai_classification_confidence", sa.Float(), nullable=True),
        sa.Column("ai_extraction_confidence", sa.Float(), nullable=True),
        sa.Column("extraction_duration_ms", sa.Integer(), nullable=True),
        # Verificare / aprobare
        sa.Column("reviewed_by", UUID, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", UUID, nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.String(512), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_documents_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # SET NULL: probele contabile nu dispar odată cu clientul; documentul rămâne
        # neatribuit, ceea ce este exact starea UNMATCHED.
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_documents_client_id_clients",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name="fk_documents_document_type_id_document_types",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["document_intakes.id"],
            name="fk_documents_intake_id_document_intakes",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["documents.id"],
            name="fk_documents_duplicate_of_id_documents",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_documents_reviewed_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_documents_approved_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.CheckConstraint(_in_list("status", DOCUMENT_STATUSES), name="status"),
        sa.CheckConstraint(_in_list("source", DOCUMENT_SOURCES), name="source"),
        sa.CheckConstraint("file_size > 0", name="file_size_positive"),
        # Un hash de altă lungime înseamnă că nu e SHA-256 — iar detecția
        # duplicatelor se bazează pe el.
        sa.CheckConstraint("char_length(sha256_hash) = 64", name="sha256_length"),
        sa.CheckConstraint(
            "reference_month IS NULL OR reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
            name="reference_month_format",
        ),
        sa.CheckConstraint(
            "(status <> 'ARCHIVED') OR (archived_at IS NOT NULL AND stored_filename IS NOT NULL)",
            name="archived_has_filename",
        ),
        sa.CheckConstraint(
            "(is_duplicate = false) OR (duplicate_of_id IS NOT NULL)", name="duplicate_has_origin"
        ),
        sa.CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id <> id", name="duplicate_not_self"
        ),
    )
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"])
    op.create_index(
        "ix_documents_organization_id_deleted_at", "documents", ["organization_id", "deleted_at"]
    )
    op.create_index(
        "ix_documents_organization_id_status", "documents", ["organization_id", "status"]
    )
    op.create_index("ix_documents_sha256_hash", "documents", ["sha256_hash"])
    op.create_index(
        "ix_documents_client_id_reference_month", "documents", ["client_id", "reference_month"]
    )
    op.create_index("ix_documents_document_date", "documents", ["document_date"])
    op.create_index("ix_documents_received_at", "documents", ["received_at"])
    op.create_index(
        "ix_documents_supplier_tax_id_document_number",
        "documents",
        ["supplier_tax_id", "document_number"],
    )
    op.create_index("ix_documents_document_type_id", "documents", ["document_type_id"])
    # Căutare fără diacritice, ca la clienți: „distributie" găsește „Distribuție".
    for column in ("supplier_name", "original_filename", "document_number"):
        op.create_index(
            f"ix_documents_{column}_trgm",
            "documents",
            [sa.text(f"app_unaccent(lower({column})) gin_trgm_ops")],
            postgresql_using="gin",
        )

    # Cheia care închide ciclul dintre cele două tabele.
    op.create_foreign_key(
        "fk_document_intakes_document_id_documents",
        "document_intakes",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── document_versions ───────────────────────────────────────────────────
    op.create_table(
        "document_versions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), server_default="original", nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("uploaded_by", UUID, nullable=True),
        sa.Column("reason", sa.String(255), server_default="", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_versions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_document_versions_uploaded_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_id_version_number"
        ),
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
        sa.CheckConstraint("char_length(sha256_hash) = 64", name="sha256_length"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    # ── document_field_overrides ────────────────────────────────────────────
    op.create_table(
        "document_field_overrides",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("previous_confidence", sa.Float(), nullable=True),
        sa.Column("previous_source", sa.String(16), nullable=True),
        sa.Column("changed_by", UUID, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_field_overrides_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_document_field_overrides_changed_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_field_overrides"),
    )
    op.create_index(
        "ix_document_field_overrides_document_id", "document_field_overrides", ["document_id"]
    )
    op.create_index(
        "ix_document_field_overrides_field_name", "document_field_overrides", ["field_name"]
    )


def downgrade() -> None:
    op.drop_table("document_field_overrides")
    op.drop_table("document_versions")
    op.drop_constraint(
        "fk_document_intakes_document_id_documents", "document_intakes", type_="foreignkey"
    )
    for column in ("supplier_name", "original_filename", "document_number"):
        op.drop_index(f"ix_documents_{column}_trgm", table_name="documents")
    op.drop_table("documents")
    op.drop_index("uq_document_intakes_external_ref", table_name="document_intakes")
    op.drop_table("document_intakes")
    op.drop_table("document_types")
