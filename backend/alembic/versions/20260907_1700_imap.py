"""Cutia poștală obișnuită, citită prin IMAP

Preluarea din email exista de la M10, dar numai prin Microsoft Graph — adică
numai pentru cabinetele care sunt pe Microsoft 365. În România, cabinetul mic are
cutia la Gmail, la Yahoo sau la găzduirea unde îi stă și site-ul.

Motivele pentru fiecare coloană stau în `app/models/imap.py`.

Revision ID: f3a8d21c6b70
Revises: e5b1c07d9a34
Create Date: 2026-09-07 17:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a8d21c6b70"
down_revision: str | None = "e5b1c07d9a34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imap_mailboxes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("use_ssl", sa.Boolean(), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        # Criptată cu DRIVE_TOKEN_KEY. Nu iese niciodată prin API.
        sa.Column("password", sa.String(length=1024), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False),
        sa.Column("uid_validity", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("files_ingested", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "username", "folder", name="uq_imap_mailboxes_account"
        ),
    )
    op.create_index("ix_imap_mailboxes_organization_id", "imap_mailboxes", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_imap_mailboxes_organization_id", table_name="imap_mailboxes")
    op.drop_table("imap_mailboxes")
