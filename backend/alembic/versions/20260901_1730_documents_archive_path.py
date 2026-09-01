"""documents: calea de arhivă și unicitatea numelui în dosar

Arhivarea (§10, §11) are nevoie de două lucruri pe care schema nu le avea:

1. `archive_path` — locul documentului în structura pe care o vede contabilul,
   `/ARHIVA/{an}/{lună}/{client}/`. Nu este o cale de filesystem: cheia de stocare
   rămâne una generată (§74).
2. Un index unic parțial pe `(organization_id, archive_path, stored_filename)`.
   Sufixul anti-coliziune se calculează în cod, dar garanția stă aici: două
   arhivări simultane nu pot alege același nume, oricât de bine ar căuta fiecare
   înainte.

Constrângerea `archived_has_filename` se întărește odată cu ele: un document
`ARCHIVED` trebuie să aibă tot ce înseamnă „arhivat", nu doar un nume.

Revision ID: 4c1d9f0b2e77
Revises: 6a1fb31f88e0
Create Date: 2026-09-01 17:30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c1d9f0b2e77"
down_revision: str | None = "6a1fb31f88e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ARCHIVED_CHECK = (
    "(status <> 'ARCHIVED') OR (archived_at IS NOT NULL AND stored_filename IS NOT NULL)"
)
NEW_ARCHIVED_CHECK = (
    "(status <> 'ARCHIVED') OR ("
    "archived_at IS NOT NULL AND stored_filename IS NOT NULL "
    "AND archive_path IS NOT NULL AND archive_key IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column("documents", sa.Column("archive_path", sa.String(512), nullable=True))

    op.drop_constraint("archived_has_filename", "documents", type_="check")
    op.create_check_constraint("archived_has_filename", "documents", NEW_ARCHIVED_CHECK)

    op.create_index(
        "uq_documents_archive_location",
        "documents",
        ["organization_id", "archive_path", "stored_filename"],
        unique=True,
        postgresql_where=sa.text("archive_path IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_documents_archive_location", table_name="documents")

    op.drop_constraint("archived_has_filename", "documents", type_="check")
    op.create_check_constraint("archived_has_filename", "documents", OLD_ARCHIVED_CHECK)

    op.drop_column("documents", "archive_path")
