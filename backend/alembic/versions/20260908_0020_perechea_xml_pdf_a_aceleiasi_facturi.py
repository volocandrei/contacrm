"""Perechea XML-PDF a aceleiasi facturi

Aceeasi factura ajunge de doua ori si pe doua drumuri: XML-ul din SPV si PDF-ul
de pe email. Sunt acelasi document, nu doua — dar niciunul nu se arunca: XML-ul
este originalul fiscal, PDF-ul este ce se poate privi si tipari.

Legatura este reciproca (amandoua randurile arata unul spre celalalt), iar
`ondelete="SET NULL"` o rupe fara sa duca la pierderea vreunui document.

Scrisa de mana, a patra oara la rand — vezi motivul in migrarea `49d20fa1d6cc`.

Revision ID: d7c2a41f8b95
Revises: b4e1f2a90d37
Create Date: 2026-09-08 00:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7c2a41f8b95"
down_revision: str | None = "b4e1f2a90d37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("paired_with_id", sa.UUID(), nullable=True))
    op.add_column("documents", sa.Column("pairing_reasons", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("paired_automatically", sa.Boolean(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_paired_with_id_documents"),
        "documents",
        "documents",
        ["paired_with_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Perechea se cauta pornind de la un document; indexul o face o cautare, nu o
    # trecere prin tot tabelul.
    op.create_index("ix_documents_paired_with_id", "documents", ["paired_with_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_paired_with_id", table_name="documents")
    op.drop_constraint(
        op.f("fk_documents_paired_with_id_documents"), "documents", type_="foreignkey"
    )
    op.drop_column("documents", "paired_automatically")
    op.drop_column("documents", "pairing_reasons")
    op.drop_column("documents", "paired_with_id")
