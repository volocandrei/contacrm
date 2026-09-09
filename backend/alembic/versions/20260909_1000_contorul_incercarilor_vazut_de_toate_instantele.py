"""Contorul incercarilor, vazut de toate instantele

Contorul de incercari esuate statea in memoria procesului de API. Pe un server
cu un singur container asta functioneaza. Pe o platforma serverless — adica fix
tinta de deploy — fiecare cerere poate nimeri alta instanta, iar platforma
porneste instante noi tocmai cand creste traficul: exact ce face un atac prin
incercarea parolelor. Protectia slabea singura, in clipa in care era nevoie de ea.

Un rand in baza de date, nu Redis: fereastra este de un minut, cheile sunt
putine, iar scrierea se face numai la esec. Baza este oricum singurul lucru pe
care instantele il impart.

`window_started_at` se scrie cu ceasul bazei (`now()`), nu al procesului: doua
instante cu ceasuri diferite ar fi deschis ferestre diferite pentru aceeasi cheie.

Scrisa de mana — vezi motivul in migrarea `49d20fa1d6cc`.

Revision ID: c4e9b21a7f38
Revises: a1c8f30d5e72
Create Date: 2026-09-09 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e9b21a7f38"
down_revision: str | None = "a1c8f30d5e72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_windows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    # Curatenia sterge ferestrele vechi; fara indice ar fi o scanare completa la
    # fiecare tur de worker.
    op.create_index(
        "ix_rate_limit_windows_window_started_at",
        "rate_limit_windows",
        ["window_started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_windows_window_started_at", table_name="rate_limit_windows")
    op.drop_table("rate_limit_windows")
