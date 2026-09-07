"""Onorariile cabinetului: cât ia de la fiecare client și cine a plătit

Coloana cu banii era, în fiecare cabinet, într-un Excel separat de lista de
clienți — și de aceea nu se potrivea niciodată cu ea. Aici sunt două tabele:
înțelegerea în vigoare (`client_fees`) și luna facturată, cu suma înghețată
atunci (`fee_entries`).

Nu se emit facturi. Motivele stau în `app/models/fee.py`.

Revision ID: c17b4a9e5d02
Revises: a94d3e7c2f18
Create Date: 2026-09-07 09:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c17b4a9e5d02"
down_revision: str | None = "a94d3e7c2f18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_fees",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
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
        sa.CheckConstraint("amount >= 0", name="amount_not_negative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_client_fees_client_id"),
    )
    op.create_index("ix_client_fees_organization_id", "client_fees", ["organization_id"])

    op.create_table(
        "fee_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("paid_by", sa.UUID(), nullable=True),
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
        sa.CheckConstraint("amount >= 0", name="amount_not_negative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "period", name="uq_fee_entries_client_id_period"),
    )
    op.create_index("ix_fee_entries_organization_id", "fee_entries", ["organization_id"])
    op.create_index(
        "ix_fee_entries_organization_id_period",
        "fee_entries",
        ["organization_id", "period"],
    )


def downgrade() -> None:
    op.drop_index("ix_fee_entries_organization_id_period", table_name="fee_entries")
    op.drop_index("ix_fee_entries_organization_id", table_name="fee_entries")
    op.drop_table("fee_entries")
    op.drop_index("ix_client_fees_organization_id", table_name="client_fees")
    op.drop_table("client_fees")
