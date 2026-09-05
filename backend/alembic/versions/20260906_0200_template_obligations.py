"""Profilul de client cuprinde și declarațiile

Șablonul acoperea documentele așteptate lunar, dar nu și ce depune clientul. La
instalare, asta însemna că jumătate din configurare se face pe profil, dintr-un
clic, iar cealaltă jumătate client cu client, de treizeci de ori.

Un profil de cabinet — „SRL plătitor de TVA lunar" — este un singur lucru, nu
două: spune și ce se așteaptă de la client, și ce se depune pentru el.

Tabelul păstrează numele vechi al șablonului. Redenumirea ar fi fost cosmetică și
ar fi rupt migrările existente pentru un câștig de vocabular.

Revision ID: a94d3e7c2f18
Revises: f83a25c6d194
Create Date: 2026-09-06 02:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a94d3e7c2f18"
down_revision: str | None = "f83a25c6d194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expectation_template_obligations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["template_id"], ["expectation_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["obligation_type_id"], ["obligation_types.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "obligation_type_id", name="uq_template_obligation"),
    )
    op.create_index(
        "ix_expectation_template_obligations_organization_id",
        "expectation_template_obligations",
        ["organization_id"],
    )
    op.create_index(
        "ix_expectation_template_obligations_template_id",
        "expectation_template_obligations",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expectation_template_obligations_template_id",
        table_name="expectation_template_obligations",
    )
    op.drop_index(
        "ix_expectation_template_obligations_organization_id",
        table_name="expectation_template_obligations",
    )
    op.drop_table("expectation_template_obligations")
