"""accounting_periods și client_expectations

Scrisă de mână, nu autogenerată. Autogenerarea voia să elimine indexurile trigram și
indexurile unice parțiale, pentru că ele există doar în migrări, nu în modele —
aplicate ca atare, ar fi rupt căutarea insensibilă la diacritice și unicitatea CUI.
Tot ce urmează sunt strict tabelele noi.

Ce **nu** conțin tabelele: contoare și status. Acelea se derivă din documente la
citire (`app/domain/periods.py`). Un status ținut într-o coloană se desincronizează
tăcut de contoarele lui; singurul fapt păstrat este închiderea lunii, pentru că
aceea este o decizie umană, nu un calcul.

Revision ID: 433f61f9245e
Revises: c7f2a90d1b46
Create Date: 2026-09-01 18:45
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "433f61f9245e"
down_revision: str | None = "c7f2a90d1b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "accounting_periods",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("reference_month", sa.String(7), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", UUID, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_accounting_periods"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_accounting_periods_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_accounting_periods_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"],
            ["users.id"],
            name="fk_accounting_periods_closed_by_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "organization_id", "client_id", "reference_month", name="uq_period_client_month"
        ),
        sa.CheckConstraint(
            "reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="reference_month_format"
        ),
        sa.CheckConstraint("closed_by IS NULL OR closed_at IS NOT NULL", name="closed_has_moment"),
    )
    op.create_index(
        "ix_accounting_periods_organization_id", "accounting_periods", ["organization_id"]
    )
    op.create_index("ix_accounting_periods_client_id", "accounting_periods", ["client_id"])
    op.create_index(
        "ix_accounting_periods_organization_id_reference_month",
        "accounting_periods",
        ["organization_id", "reference_month"],
    )

    op.create_table(
        "client_expectations",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("document_type_id", UUID, nullable=False),
        sa.Column("expected_min_count", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_client_expectations"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_client_expectations_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_client_expectations_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name="fk_client_expectations_document_type_id_document_types",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "client_id", "document_type_id", name="uq_client_expectation_client_type"
        ),
        sa.CheckConstraint("expected_min_count >= 1", name="expected_min_positive"),
    )
    op.create_index(
        "ix_client_expectations_organization_id", "client_expectations", ["organization_id"]
    )
    op.create_index("ix_client_expectations_client_id", "client_expectations", ["client_id"])


def downgrade() -> None:
    op.drop_table("client_expectations")
    op.drop_table("accounting_periods")
