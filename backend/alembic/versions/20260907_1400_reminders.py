"""Reminderele trimise clienților: urma că aplicația a scris singură

Cabinetul a hotărât că aplicația are voie să scrie clienților. Tabelul acesta
este ce face hotărârea suportabilă: fără el, o rulare de cron dublată ar trimite
de două ori în aceeași dimineață, iar al treilea mesaj dintr-o lună ar pleca fără
ca nimeni să-l fi numărat.

Revision ID: e5b1c07d9a34
Revises: c17b4a9e5d02
Create Date: 2026-09-07 14:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5b1c07d9a34"
down_revision: str | None = "c17b4a9e5d02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_reminders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("reference_month", sa.String(length=7), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_to", sa.String(length=320), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("link_id", sa.UUID(), nullable=True),
        sa.Column("sent_by_id", sa.UUID(), nullable=True),
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
        # Drumul se poate închide; faptul că am reamintit nu se închide odată cu el.
        sa.ForeignKeyConstraint(["link_id"], ["client_upload_links.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_reminders_organization_id", "client_reminders", ["organization_id"])
    op.create_index(
        "ix_client_reminders_client_id_period",
        "client_reminders",
        ["client_id", "reference_month"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_reminders_client_id_period", table_name="client_reminders")
    op.drop_index("ix_client_reminders_organization_id", table_name="client_reminders")
    op.drop_table("client_reminders")
