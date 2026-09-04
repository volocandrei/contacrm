"""Preluarea facturilor din SPV: conexiunea ANAF, împuternicirile, sursa EFACTURA

De la 1 iulie 2024 factura electronică este obligatorie între firme, deci partea
covârșitoare a facturilor unui cabinet nu mai vine pe email, ci stă în SPV-ul
fiecărui client. Migrarea asta dă un loc celor două lucruri de care are nevoie
preluarea automată: **certificatul** prin care întrebăm (`anaf_connections`) și
**împuternicirile** care ne dau dreptul să întrebăm pentru fiecare client
(`anaf_mandates`).

Constrângerea `source` de pe `documents` și `document_intakes` se lărgește cu
`EFACTURA`, prin drop + create ca la `ONEDRIVE`: o constrângere CHECK nu se
modifică în loc, iar numele trebuie să rămână același ca modelele să se
potrivească cu schema.

Revision ID: 5c4a1f8e2b73
Revises: 3e91b7c05a42
Create Date: 2026-09-04 11:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c4a1f8e2b73"
down_revision: str | None = "3e91b7c05a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = ("EMAIL", "WHATSAPP", "UPLOAD", "API", "ONEDRIVE")
NEW_SOURCES = (*OLD_SOURCES, "EFACTURA")

SOURCE_TABLES = ("documents", "document_intakes")

CONNECTIONS = "anaf_connections"
MANDATES = "anaf_mandates"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def _rewrite_source_constraints(values: tuple[str, ...]) -> None:
    for table in SOURCE_TABLES:
        # Numele scurt, nu cel din bază: convenția de denumire îi pune singură
        # prefixul `ck_<tabel>_`.
        op.drop_constraint("source", table, type_="check")
        op.create_check_constraint("source", table, _in_list("source", values))


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    _rewrite_source_constraints(NEW_SOURCES)

    op.create_table(
        CONNECTIONS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False, server_default="prod"),
        # Criptat cu `DRIVE_TOKEN_KEY` înainte de a ajunge aici. Un dump de bază
        # de date nu are voie să dea acces la facturile clienților.
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("certificate_holder", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=f"fk_{CONNECTIONS}_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"],
            ["users.id"],
            name=f"fk_{CONNECTIONS}_connected_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{CONNECTIONS}"),
        # Numele scurt: convenția de denumire pune singură prefixul `ck_<tabel>_`.
        sa.CheckConstraint("environment IN ('prod', 'test')", name="environment"),
    )
    op.create_index(f"ix_{CONNECTIONS}_organization_id", CONNECTIONS, ["organization_id"])
    # O singură conexiune activă per organizație. Parțial, ca o conexiune veche
    # dezactivată să nu blocheze reautorizarea de anul viitor.
    op.create_index(
        "uq_anaf_connections_active",
        CONNECTIONS,
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        MANDATES,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Forma normalizată, cea pe care o cere API-ul: doar cifre, fără `RO`.
        sa.Column("tax_id", sa.String(32), nullable=False),
        sa.Column("synced_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("invoices_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=f"fk_{MANDATES}_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            [f"{CONNECTIONS}.id"],
            name=f"fk_{MANDATES}_connection_id_{CONNECTIONS}",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=f"fk_{MANDATES}_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{MANDATES}"),
        # Același CUI interogat de două ori ar produce două documente pentru
        # fiecare factură, și dublul cererilor către ANAF.
        sa.UniqueConstraint("organization_id", "tax_id", name="uq_anaf_mandates_tax_id"),
        sa.UniqueConstraint("organization_id", "client_id", name="uq_anaf_mandates_client"),
        sa.CheckConstraint("char_length(tax_id) BETWEEN 2 AND 32", name="tax_id_present"),
        sa.CheckConstraint("invoices_ingested >= 0", name="invoices_ingested_positive"),
    )
    op.create_index(f"ix_{MANDATES}_organization_id", MANDATES, ["organization_id"])
    op.create_index(f"ix_{MANDATES}_connection_id", MANDATES, ["connection_id"])


def downgrade() -> None:
    op.drop_table(MANDATES)
    op.drop_table(CONNECTIONS)

    # Facturile venite din SPV nu mai au o sursă validă după restrângere. Se mută
    # pe `API` — adevărat în litera ei, au intrat programatic — și se păstrează:
    # sunt probe contabile (R8), iar o migrare inversă nu are voie să le șteargă.
    for table in SOURCE_TABLES:
        op.execute(f"UPDATE {table} SET source = 'API' WHERE source = 'EFACTURA'")
    _rewrite_source_constraints(OLD_SOURCES)
