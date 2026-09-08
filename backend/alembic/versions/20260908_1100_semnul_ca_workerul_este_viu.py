"""Semnul ca workerul este viu

Un worker mort nu se vedea nicaieri. Documentele intrau, ramaneau in `PENDING`,
iar ecranul nu arata nicio eroare — fiindca nu era niciuna. Singurul semn era o
coada care crestea si pe care nu o privea nimeni.

Un rand in baza de date, nu un fisier: procesul care raspunde la
`/health/workers` este altul decat workerul, adesea pe alta masina. Singurul
lucru pe care il impart este baza.

`beat_at` se scrie cu ceasul **bazei** (`now()`), nu al procesului: doua masini cu
ceasuri diferite ar fi produs o vechime negativa sau una uriasa, iar alarma ar fi
sunat din cauza NTP-ului, nu a workerului.

Scrisa de mana, a cincea oara la rand — vezi motivul in migrarea `49d20fa1d6cc`.

Revision ID: a1c8f30d5e72
Revises: d7c2a41f8b95
Create Date: 2026-09-08 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c8f30d5e72"
down_revision: str | None = "d7c2a41f8b95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_heartbeats")),
        # Un rand pe worker, actualizat — nu un jurnal care creste la nesfarsit.
        sa.UniqueConstraint("name", name=op.f("uq_worker_heartbeats_name")),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
