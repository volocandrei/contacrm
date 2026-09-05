"""Linkul știe dacă mesajul chiar a plecat

Ecranul scria „Pregătit" și avea dreptate: aplicația compunea textul, iar
contabilul îl trimitea din clientul lui de email. Tot ce știa sigur aplicația era
că cererea fusese compusă.

Din momentul în care poate trimite ea, „Trimis" devine o afirmație verificabilă —
dar numai dacă există unde să scrie că a trimis. Coloanele astea sunt acel loc, și
rămân nule exact atunci când mesajul a fost doar copiat.

Revision ID: f83a25c6d194
Revises: e71c9d4a8b35
Create Date: 2026-09-06 00:30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f83a25c6d194"
down_revision: str | None = "e71c9d4a8b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "client_upload_links",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "client_upload_links",
        sa.Column("notified_to", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_upload_links", "notified_to")
    op.drop_column("client_upload_links", "notified_at")
