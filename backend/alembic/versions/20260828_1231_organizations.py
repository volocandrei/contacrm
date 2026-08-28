"""organizations — rădăcina multi-tenancy-ului (§33)

Prima migrare. Creează tabelul la care va referi `organization_id` din restul
schemei și activează `pgcrypto`, ca baza să poată genera ea însăși UUID-uri când
o inserare nu vine prin ORM.

Revision ID: 538bf7ca1e6b
Revises:
Create Date: 2026-08-28 12:31:53.973605
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "538bf7ca1e6b"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tax_id", sa.String(length=32), nullable=True),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # Timpul este întotdeauna cu fus orar (§71).
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
        # Ștergerea este logică — organizația poate avea documente contabile (R8).
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )

    # CUI-ul este unic doar acolo unde există; mai multe organizații fără CUI sunt permise.
    op.create_index(
        "uq_organizations_tax_id",
        "organizations",
        ["tax_id"],
        unique=True,
        postgresql_where=sa.text("tax_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_organizations_deleted_at", "organizations", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_organizations_deleted_at", table_name="organizations")
    op.drop_index("uq_organizations_tax_id", table_name="organizations")
    op.drop_table("organizations")
    # `pgcrypto` nu se șterge: alte obiecte din bază pot depinde de ea.
