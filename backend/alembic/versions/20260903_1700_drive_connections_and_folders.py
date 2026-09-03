"""Intake din OneDrive/SharePoint: conexiuni, dosare urmărite, sursa ONEDRIVE

Cererea cabinetului: „să îmi preia automat ce documente trimit clienții, să nu
mai stau eu să le descarc și să le numesc manual". Dosarele există deja, unul per
client. Migrarea asta le dă un loc în care să fie ținute minte.

Constrângerea `source` de pe `documents` și `document_intakes` se lărgește cu
`ONEDRIVE`. Se face prin drop + create, nu prin `ALTER ... ADD`: o constrângere
CHECK nu se modifică în loc, iar numele trebuie să rămână același ca modelele să
se potrivească cu schema.

Revision ID: 7d2e5a91c0b4
Revises: 433f61f9245e
Create Date: 2026-09-03 17:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7d2e5a91c0b4"
down_revision: str | None = "433f61f9245e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = ("EMAIL", "WHATSAPP", "UPLOAD", "API")
NEW_SOURCES = (*OLD_SOURCES, "ONEDRIVE")

# Tabelele care poartă constrângerea, cu numele ei exact.
SOURCE_TABLES = ("documents", "document_intakes")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


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


def _rewrite_source_constraints(values: tuple[str, ...]) -> None:
    for table in SOURCE_TABLES:
        # Numele scurt, nu cel din bază: convenția de denumire îi pune singură
        # prefixul `ck_<tabel>_`. Trecut întreg, ar deveni `ck_documents_ck_documents_source`.
        op.drop_constraint("source", table, type_="check")
        op.create_check_constraint("source", table, _in_list("source", values))


def upgrade() -> None:
    _rewrite_source_constraints(NEW_SOURCES)

    op.create_table(
        "drive_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_email", sa.String(320), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=True),
        # Criptat cu `DRIVE_TOKEN_KEY` înainte de a ajunge aici. Un dump de bază de
        # date nu are voie să dea acces la OneDrive-ul cabinetului.
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_drive_connections_organization_id_organizations",
            # RESTRICT, ca peste tot: ștergerea unei organizații nu are voie să ia
            # tăcut cu ea documentele și legăturile ei.
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by"],
            ["users.id"],
            name="fk_drive_connections_connected_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drive_connections"),
        sa.CheckConstraint(_in_list("provider", ("microsoft",)), name="provider"),
    )
    op.create_index(
        "ix_drive_connections_organization_id", "drive_connections", ["organization_id"]
    )
    # Parțial: o conexiune dezactivată nu blochează reconectarea.
    op.create_index(
        "uq_drive_connections_active",
        "drive_connections",
        ["organization_id", "provider"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "drive_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("drive_id", sa.String(255), nullable=False),
        sa.Column("item_id", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("delta_token", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("files_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_drive_folders_organization_id_organizations",
            # RESTRICT, ca peste tot: ștergerea unei organizații nu are voie să ia
            # tăcut cu ea documentele și legăturile ei.
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["drive_connections.id"],
            name="fk_drive_folders_connection_id_drive_connections",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_drive_folders_client_id_clients",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drive_folders"),
        # Același dosar urmărit de două ori ar produce două intake-uri per fișier.
        sa.UniqueConstraint("organization_id", "drive_id", "item_id", name="uq_drive_folders_item"),
    )
    op.create_index("ix_drive_folders_organization_id", "drive_folders", ["organization_id"])
    op.create_index("ix_drive_folders_connection_id", "drive_folders", ["connection_id"])
    op.create_index("ix_drive_folders_client_id", "drive_folders", ["client_id"])


def downgrade() -> None:
    op.drop_table("drive_folders")
    op.drop_table("drive_connections")

    # Documentele venite din OneDrive nu mai au o sursă validă după restrângere.
    # Se mută pe `API` — este adevărat în litera ei (au intrat programatic) și
    # păstrează documentele, care sunt probe contabile (R8): o migrare inversă nu
    # are voie să le șteargă.
    for table in SOURCE_TABLES:
        op.execute(f"UPDATE {table} SET source = 'API' WHERE source = 'ONEDRIVE'")
    _rewrite_source_constraints(OLD_SOURCES)
