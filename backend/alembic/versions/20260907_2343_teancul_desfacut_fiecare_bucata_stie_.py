"""Teancul desfacut: fiecare bucata stie din ce si de la ce pagina

Scrisa de mana, a treia oara la rand. `--autogenerate` a propus din nou zeci de
`alter_column` si stergeri de indexuri de expresie (`unaccent`, `trgm`) pe care
ORM-ul nu le poate descrie — vezi motivul intreg in migrarea `49d20fa1d6cc`.

Ce se adauga aici sunt patru coloane si o cheie straina catre acelasi tabel:
teancul din care a iesit documentul, paginile pe care le acopera, si — pe teanc —
cand a fost desfacut.

`ondelete="SET NULL"`, nu `CASCADE`: stergerea logica a unui teanc nu are voie sa
duca la disparitia facturilor iesite din el. Proveninenta se pierde, documentele
raman — invers ar fi fost o pierdere de probe contabile.

Revision ID: b4e1f2a90d37
Revises: c9334e45b970
Create Date: 2026-09-07 23:43:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4e1f2a90d37"
down_revision: str | None = "c9334e45b970"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Vocabularul starilor, inainte si dupa. Constrangerea din baza trebuie sa
#: enumere exact ce enumera `DocumentStatus` — `tests/test_migrations.py` compara
#: cele doua liste si cade la orice abatere.
_STATUSES = (
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
OLD_STATUS = "status IN (" + ", ".join(f"'{value}'" for value in _STATUSES) + ")"
NEW_STATUS = "status IN (" + ", ".join(f"'{value}'" for value in (*_STATUSES, "SPLIT")) + ")"


def upgrade() -> None:
    op.drop_constraint("status", "documents", type_="check")
    op.create_check_constraint("status", "documents", NEW_STATUS)

    op.add_column("documents", sa.Column("split_from_id", sa.UUID(), nullable=True))
    op.add_column("documents", sa.Column("page_from", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("page_to", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("split_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_split_from_id_documents"),
        "documents",
        "documents",
        ["split_from_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Teancurile desfacute ar bloca constrangerea veche. Nu sunt o eroare, dar
    # nici nu au unde sa se intoarca: le tratam ca documente de verificat, adica
    # exact starea din care le-a scos desfacerea.
    op.execute("UPDATE documents SET status = 'REVIEW_REQUIRED' WHERE status = 'SPLIT'")
    op.drop_constraint("status", "documents", type_="check")
    op.create_check_constraint("status", "documents", OLD_STATUS)

    op.drop_constraint(
        op.f("fk_documents_split_from_id_documents"), "documents", type_="foreignkey"
    )
    op.drop_column("documents", "split_at")
    op.drop_column("documents", "page_to")
    op.drop_column("documents", "page_from")
    op.drop_column("documents", "split_from_id")
