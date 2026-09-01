"""audit_logs: created_at din clock_timestamp(), nu din now()

În Postgres `now()` întoarce momentul de început al **tranzacției**. Toate intrările
de audit scrise într-o singură cerere primeau astfel aceeași valoare, iar ordinea
lor devenea arbitrară: istoricul unui document putea arăta arhivarea înaintea
încărcării.

`clock_timestamp()` este ceasul real, evaluat la fiecare rând.

Revision ID: c7f2a90d1b46
Revises: 9b3ac41d5e08
Create Date: 2026-09-01 20:10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7f2a90d1b46"
down_revision: str | None = "9b3ac41d5e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "created_at",
        server_default=sa.text("clock_timestamp()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_logs",
        "created_at",
        server_default=sa.text("now()"),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
