"""Liniile facturii: descrierea produsului si cota de TVA pe fiecare

Scrisa de mana, nu lasata cum a iesit din `--autogenerate`.

Autogenerarea a propus 173 de operatii: pe langa tabelul nou, a vrut sa
„repare" zeci de coloane si indexuri care nu au nimic in neregula — indexurile de
expresie (`unaccent(...)`) pe care ORM-ul nu le poate descrie, si `server_default`
uri pe care le vede ca diferente fiindca nu sunt declarate in model. Auditul de
productie a masurat deja acele opt diferente si a stabilit ca sunt corecte asa.

O migrare care le-ar fi aplicat ar fi **sters indexuri de cautare functionale**
intr-o baza de productie, pentru a le reface identic — sau, mai rau, nu identic.

Revision ID: 49d20fa1d6cc
Revises: f3a8d21c6b70
Create Date: 2026-09-07 22:01:08.712317
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "49d20fa1d6cc"
down_revision: str | None = "f3a8d21c6b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        # Pozitia in document, de la 1 — separata de `number`, care este ce scrie
        # pe factura: unele documente numeroteaza `1.1`, `A`, sau deloc.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        # Cantitatea are patru zecimale: se factureaza si `0.125` kg.
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit_code", sa.String(length=16), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        # Cota ca numar: `21`, `11`, `0`. Cu zecimale, fiindca exista cote
        # zecimale in alte tari, iar o factura intracomunitara nu este exotica.
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("vat_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("gross_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        # Categoria UBL: `S` cota standard, `AE` taxare inversa, `E` scutit,
        # `Z` cota zero. Explica un `0` care altfel arata ca o eroare de citire.
        sa.Column("vat_category", sa.String(length=8), nullable=True),
        sa.CheckConstraint("position >= 1", name=op.f("ck_document_lines_position_positive")),
        # Cota nu poate fi negativa. Poate fi zero — scutit, taxare inversa.
        sa.CheckConstraint(
            "vat_rate IS NULL OR vat_rate >= 0",
            name=op.f("ck_document_lines_vat_rate_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_lines_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_lines")),
        sa.UniqueConstraint("document_id", "position", name="uq_document_lines_document_position"),
    )
    op.create_index(
        "ix_document_lines_document_id", "document_lines", ["document_id"], unique=False
    )
    # Pentru raportul pe cote: „cat la 21%, cat la 11%", peste o luna intreaga.
    op.create_index("ix_document_lines_vat_rate", "document_lines", ["vat_rate"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_lines_vat_rate", table_name="document_lines")
    op.drop_index("ix_document_lines_document_id", table_name="document_lines")
    op.drop_table("document_lines")
