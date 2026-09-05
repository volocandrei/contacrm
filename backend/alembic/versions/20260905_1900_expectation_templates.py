"""Șabloane de așteptări: profilurile de client ale cabinetului

Fără așteptări configurate, checklistul lunii este gol, „Documente lipsă" nu are
ce raporta, iar fiecare lună apare completă pentru că nu i se cere nimic. Adică
tot ce s-a construit în jurul colectării — cererea, linkul, urma — nu pornește.

Configurarea se făcea client cu client, bifă cu bifă. Un cabinet cu treizeci de
clienți are, în realitate, trei-patru profiluri: SRL plătitor de TVA lunar, SRL
neplătitor, PFA în sistem real. Șablonul este numele pe care cabinetul îl dă
profilului, iar aplicarea lui pe doisprezece clienți deodată este diferența
dintre o după-amiază și un minut.

**Șablonul nu este o legătură.** Se aplică o dată și rezultatul rămâne al
clientului: cine schimbă pe urmă șablonul nu rescrie tăcut ce s-a configurat
manual după aceea. Un client care „moștenește" la distanță ar face ca o bifă
scoasă azi să reapară peste o lună fără ca cineva să fi atins ecranul lui.

Revision ID: c5a8e13b7f42
Revises: 9d4f7a2c81e6
Create Date: 2026-09-05 19:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a8e13b7f42"
down_revision: str | None = "9d4f7a2c81e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expectation_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        # Două profiluri cu același nume nu se pot deosebi pe ecran, iar aplicarea
        # greșită a unuia rescrie tăcut checklistul unui client.
        sa.UniqueConstraint("organization_id", "name", name="uq_expectation_template_name"),
    )
    op.create_index(
        "ix_expectation_templates_organization_id", "expectation_templates", ["organization_id"]
    )

    op.create_table(
        "expectation_template_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("document_type_id", sa.UUID(), nullable=False),
        sa.Column("expected_min_count", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("expected_min_count >= 1", name="expected_min_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["expectation_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_type_id"], ["document_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "document_type_id", name="uq_template_item_type"),
    )
    op.create_index(
        "ix_expectation_template_items_organization_id",
        "expectation_template_items",
        ["organization_id"],
    )
    op.create_index(
        "ix_expectation_template_items_template_id", "expectation_template_items", ["template_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expectation_template_items_template_id", table_name="expectation_template_items"
    )
    op.drop_index(
        "ix_expectation_template_items_organization_id", table_name="expectation_template_items"
    )
    op.drop_table("expectation_template_items")
    op.drop_index("ix_expectation_templates_organization_id", table_name="expectation_templates")
    op.drop_table("expectation_templates")
