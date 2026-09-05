"""Termenele de depunere, per client

Aplicația avea un singur termen: ziua 25, globală, folosită de numărătoarea
inversă a lunii. Un cabinet nu trăiește așa. Un client pe TVA trimestrial depune
altcând decât unul pe lunar; salariile au termenul lor; bilanțul, cu totul altul.
Consecința unui termen ratat nu este o neplăcere de interfață — este o amendă la
client, plătită de cabinet.

Trei tabele, fiindcă sunt trei lucruri diferite: catalogul cabinetului (cum se
numește declarația și când se depune), cine ce depune, și ce s-a depus.

Termenele nu stau în cod. `obligation_types` se administrează din aplicație, ca
`document_types`: aplicația știe aritmetica unui calendar, nu legea.

Revision ID: e71c9d4a8b35
Revises: c5a8e13b7f42
Create Date: 2026-09-05 21:30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e71c9d4a8b35"
down_revision: str | None = "c5a8e13b7f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "obligation_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("months_after", sa.Integer(), nullable=False),
        sa.Column("deadline_day", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
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
        # Ziua se retează la ultima zi a lunii la calcul, deci 31 este valid;
        # 0 sau 32 nu ar fi o zi.
        sa.CheckConstraint("deadline_day BETWEEN 1 AND 31", name="deadline_day_is_a_day"),
        sa.CheckConstraint("months_after >= 0", name="months_after_not_negative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_obligation_type_code"),
    )
    op.create_index("ix_obligation_types_organization_id", "obligation_types", ["organization_id"])
    op.create_index(
        "ix_obligation_types_organization_id_is_active",
        "obligation_types",
        ["organization_id", "is_active"],
    )

    op.create_table(
        "client_obligations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("obligation_type_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["obligation_type_id"], ["obligation_types.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "obligation_type_id", name="uq_client_obligation"),
    )
    op.create_index(
        "ix_client_obligations_organization_id", "client_obligations", ["organization_id"]
    )
    op.create_index("ix_client_obligations_client_id", "client_obligations", ["client_id"])

    op.create_table(
        "obligation_filings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("obligation_type_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filed_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["obligation_type_id"], ["obligation_types.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["filed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # A doua marcare a aceleiași perioade nu are ce adăuga, iar două rânduri
        # ar face imposibil de spus cine a depus.
        sa.UniqueConstraint(
            "client_id", "obligation_type_id", "period", name="uq_obligation_filing"
        ),
    )
    op.create_index(
        "ix_obligation_filings_organization_id", "obligation_filings", ["organization_id"]
    )
    op.create_index(
        "ix_obligation_filings_organization_id_period",
        "obligation_filings",
        ["organization_id", "period"],
    )


def downgrade() -> None:
    op.drop_index("ix_obligation_filings_organization_id_period", table_name="obligation_filings")
    op.drop_index("ix_obligation_filings_organization_id", table_name="obligation_filings")
    op.drop_table("obligation_filings")
    op.drop_index("ix_client_obligations_client_id", table_name="client_obligations")
    op.drop_index("ix_client_obligations_organization_id", table_name="client_obligations")
    op.drop_table("client_obligations")
    op.drop_index("ix_obligation_types_organization_id_is_active", table_name="obligation_types")
    op.drop_index("ix_obligation_types_organization_id", table_name="obligation_types")
    op.drop_table("obligation_types")
