"""Intake din email; conexiunea devine „cont Microsoft", nu „drive"

Două schimbări legate:

**Redenumire.** `drive_connections` ținea deja un cont Microsoft, nu un drive:
același token deschide și OneDrive, și cutia poștală. Numele devenea o minciună
în momentul în care emailul se adaugă pe aceeași conexiune, iar un nume care
minte costă mai mult peste șase luni decât o migrare acum, cât nu există date de
producție.

**`mail_folders`.** Oglinda lui `drive_folders`, pentru cutia poștală: ce dosare
de email se citesc și de la ce token de sincronizare se continuă. Diferența de
fond este cine dă clientul — la drive, dosarul; la email, **expeditorul**, potrivit
pe adresele de contact ale clienților.

Revision ID: 3e91b7c05a42
Revises: 7d2e5a91c0b4
Create Date: 2026-09-03 21:30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3e91b7c05a42"
down_revision: str | None = "7d2e5a91c0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "drive_connections"
NEW = "microsoft_connections"

# Numele generate de convenția din `models/base.py` poartă numele tabelei, deci se
# redenumesc odată cu ea. Altfel testul de derapaj modele↔migrări cade — și are
# dreptate: schema chiar ar diferi de ce descriu modelele.
CONSTRAINTS = (
    ("pk", f"pk_{OLD}", f"pk_{NEW}"),
    ("ck", f"ck_{OLD}_provider", f"ck_{NEW}_provider"),
    (
        "fk",
        f"fk_{OLD}_organization_id_organizations",
        f"fk_{NEW}_organization_id_organizations",
    ),
    ("fk", f"fk_{OLD}_connected_by_users", f"fk_{NEW}_connected_by_users"),
)

INDEXES = (
    (f"ix_{OLD}_organization_id", f"ix_{NEW}_organization_id"),
    ("uq_drive_connections_active", "uq_microsoft_connections_active"),
)


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


def _rename(source: str, target: str, constraints, indexes) -> None:
    op.rename_table(source, target)
    for kind, old_name, new_name in constraints:
        del kind
        op.execute(f'ALTER TABLE {target} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')
    for old_name, new_name in indexes:
        op.execute(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"')


def upgrade() -> None:
    _rename(OLD, NEW, CONSTRAINTS, INDEXES)
    # Cheia străină din `drive_folders` arată acum către tabela redenumită; numele
    # ei rămâne, pentru că numele tabelei **sursă** nu s-a schimbat.
    op.execute(
        "ALTER TABLE drive_folders RENAME CONSTRAINT "
        '"fk_drive_folders_connection_id_drive_connections" TO '
        '"fk_drive_folders_connection_id_microsoft_connections"'
    )

    op.create_table(
        "mail_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Identificatorul dosarului din cutia poștală. `inbox` este un nume
        # rezervat pe care Graph îl acceptă direct.
        sa.Column("folder_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("delta_token", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("files_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_mail_folders_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            [f"{NEW}.id"],
            name="fk_mail_folders_connection_id_microsoft_connections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mail_folders"),
        # Același dosar citit de două ori ar produce două intake-uri per atașament.
        sa.UniqueConstraint("organization_id", "folder_id", name="uq_mail_folders_folder"),
    )
    op.create_index("ix_mail_folders_organization_id", "mail_folders", ["organization_id"])
    op.create_index("ix_mail_folders_connection_id", "mail_folders", ["connection_id"])


def downgrade() -> None:
    op.drop_table("mail_folders")

    op.execute(
        "ALTER TABLE drive_folders RENAME CONSTRAINT "
        '"fk_drive_folders_connection_id_microsoft_connections" TO '
        '"fk_drive_folders_connection_id_drive_connections"'
    )
    _rename(
        NEW,
        OLD,
        tuple((kind, new, old) for kind, old, new in CONSTRAINTS),
        tuple((new, old) for old, new in INDEXES),
    )
