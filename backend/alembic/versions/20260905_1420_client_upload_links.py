"""Linkul prin care clientul își trimite singur documentele

Partea cea mai grea a muncii unui cabinet nu este procesarea documentelor, ci
adunarea lor: clientul trebuie să scaneze, să atașeze, să nu uite jumătate.
Linkul mută efortul de unde este scump la unde este ieftin.

`token_hash` unic, nu tokenul: o bază de date citită de altcineva nu trebuie să
dea linkuri funcționale. Aceeași regulă ca la refresh tokenuri.

`expires_at` este obligatoriu, nu opțional. Un link trimis într-un email rămâne
în inbox-ul acelui email pentru totdeauna; trebuie să existe un moment în care
încetează, iar o coloană care se poate lăsa goală devine, în practică, goală.

Revision ID: 6b2e8f41d9c3
Revises: 3a91c4d7e5b8
Create Date: 2026-09-05 14:20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b2e8f41d9c3"
down_revision: str | None = "3a91c4d7e5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tabelele care poartă `source` cu aceeași listă de valori.
SOURCE_TABLES = ("documents", "document_intakes")

OLD_SOURCES = ("EMAIL", "WHATSAPP", "UPLOAD", "API", "ONEDRIVE", "EFACTURA")
NEW_SOURCES = (*OLD_SOURCES, "PORTAL")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def _rewrite_source_constraints(values: tuple[str, ...]) -> None:
    for table in SOURCE_TABLES:
        # Numele scurt, nu cel din bază: convenția de denumire îi pune singură
        # prefixul `ck_<tabel>_`.
        op.drop_constraint("source", table, type_="check")
        op.create_check_constraint("source", table, _in_list("source", values))


def upgrade() -> None:
    # Sursa nouă, înaintea tabelului: un document venit prin portal poartă
    # `PORTAL`, iar constrângerea trebuie să îl accepte de la prima cerere.
    _rewrite_source_constraints(NEW_SOURCES)
    op.create_table(
        "client_upload_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("upload_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_upload_links_organization_id", "client_upload_links", ["organization_id"]
    )
    op.create_index("ix_client_upload_links_client_id", "client_upload_links", ["client_id"])
    op.create_index(
        "ix_client_upload_links_token_hash", "client_upload_links", ["token_hash"], unique=True
    )


def downgrade() -> None:
    # Documentele deja sosite prin portal nu se pot pierde. Devin `API`, care este
    # tot „a intrat de undeva, nu l-a urcat un om" — cea mai apropiată valoare
    # rămasă. Aceeași soluție ca la coborârea sursei `EFACTURA`.
    for table in SOURCE_TABLES:
        op.execute(f"UPDATE {table} SET source = 'API' WHERE source = 'PORTAL'")
    _rewrite_source_constraints(OLD_SOURCES)
    op.drop_index("ix_client_upload_links_token_hash", table_name="client_upload_links")
    op.drop_index("ix_client_upload_links_client_id", table_name="client_upload_links")
    op.drop_index("ix_client_upload_links_organization_id", table_name="client_upload_links")
    op.drop_table("client_upload_links")
