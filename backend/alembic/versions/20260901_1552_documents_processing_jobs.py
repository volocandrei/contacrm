"""documents: processing jobs

`idempotency_key` este unic la nivel de tabel, nu per document: cheia conține deja
id-ul documentului, iar unicitatea globală face ca o cerere relivrată să fie
respinsă de baza de date, nu doar de o verificare în cod (§39).

Revision ID: 6a1fb31f88e0
Revises: b8ab4b1e400c
Create Date: 2026-09-01 15:52
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6a1fb31f88e0"
down_revision: str | None = "b8ab4b1e400c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

JOB_STATUSES = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED")


def upgrade() -> None:
    op.create_table(
        "document_processing_jobs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("job_type", sa.String(32), server_default="EXTRACTION", nullable=False),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_detail", sa.String(512), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_processing_jobs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_processing_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_document_processing_jobs_idempotency_key"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in JOB_STATUSES) + ")", name="status"
        ),
        sa.CheckConstraint("attempt >= 1", name="attempt_positive"),
    )
    op.create_index(
        "ix_document_processing_jobs_document_id", "document_processing_jobs", ["document_id"]
    )
    op.create_index("ix_document_processing_jobs_status", "document_processing_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("document_processing_jobs")
