"""crm: clients, contacts, notes, tags, tasks

Aduce și infrastructura de căutare insensibilă la diacritice:

- extensiile `unaccent` și `pg_trgm`;
- `app_unaccent(text)`, un wrapper IMMUTABLE — `unaccent` însuși este STABLE
  (depinde de dicționarul instalat), deci nu poate apărea într-un index;
- un index GIN trigram peste forma normalizată a numelui, ca `LIKE '%...%'` să nu
  ajungă scanare secvențială pe măsură ce lista de clienți crește.

Rezultatul este comportamentul din backendul simulat: „Serban" găsește „Șerban".

Revision ID: acb7bb07feaf
Revises: 080ad92f848f
Create Date: 2026-08-31 16:06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "acb7bb07feaf"
down_revision: str | None = "080ad92f848f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

CLIENT_STATUSES = ("ACTIVE", "INACTIVE", "PROSPECT", "SUSPENDED")
TASK_STATUSES = ("TODO", "IN_PROGRESS", "BLOCKED", "DONE")
TASK_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")


def _timestamps() -> list[sa.Column]:
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


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    # ── Căutare fără diacritice ─────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # `unaccent(text)` este STABLE, nu IMMUTABLE, deci Postgres refuză să-l indexeze.
    # Wrapper-ul fixează dicționarul explicit, ceea ce îl face determinist.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_unaccent(value text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, value) $$
        """
    )

    # ── tags ────────────────────────────────────────────────────────────────
    op.create_table(
        "tags",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("color", sa.String(16), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_tags_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("organization_id", "name", name="uq_tags_organization_id_name"),
    )
    op.create_index("ix_tags_organization_id", "tags", ["organization_id"])

    # ── clients ─────────────────────────────────────────────────────────────
    op.create_table(
        "clients",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tax_id", sa.String(32), nullable=True),
        sa.Column("registration_number", sa.String(64), nullable=True),
        sa.Column("address", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="PROSPECT", nullable=False),
        sa.Column("assigned_accountant_id", UUID, nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_clients_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # SET NULL: plecarea unui contabil nu șterge clientul, îl lasă neatribuit.
        sa.ForeignKeyConstraint(
            ["assigned_accountant_id"],
            ["users.id"],
            name="fk_clients_assigned_accountant_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clients"),
        # Convenția de denumire adaugă prefixul `ck_clients_`.
        sa.CheckConstraint(_in_list("status", CLIENT_STATUSES), name="status"),
    )
    op.create_index("ix_clients_organization_id", "clients", ["organization_id"])
    op.create_index("ix_clients_deleted_at", "clients", ["deleted_at"])
    op.create_index("ix_clients_organization_id_status", "clients", ["organization_id", "status"])
    op.create_index("ix_clients_assigned_accountant_id", "clients", ["assigned_accountant_id"])
    # CUI unic per organizație, dar doar printre clienții activi: un client șters
    # nu trebuie să blocheze reînregistrarea aceleiași firme.
    op.create_index(
        "uq_clients_organization_id_tax_id",
        "clients",
        ["organization_id", "tax_id"],
        unique=True,
        postgresql_where=sa.text("tax_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_clients_name_trgm",
        "clients",
        [sa.text("app_unaccent(lower(name)) gin_trgm_ops")],
        postgresql_using="gin",
    )

    op.create_table(
        "client_tags",
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("tag_id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_client_tags_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name="fk_client_tags_tag_id_tags", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("client_id", "tag_id", name="pk_client_tags"),
    )

    # ── contacts ────────────────────────────────────────────────────────────
    op.create_table(
        "contacts",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(128), server_default="", nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("whatsapp_number", sa.String(32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name="fk_contacts_client_id_clients", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
    )
    op.create_index("ix_contacts_client_id", "contacts", ["client_id"])
    op.create_index("ix_contacts_deleted_at", "contacts", ["deleted_at"])
    # Intake-ul caută invers: de la adresa expeditorului la client (§8).
    op.create_index("ix_contacts_email", "contacts", ["email"])
    op.create_index("ix_contacts_whatsapp_number", "contacts", ["whatsapp_number"])

    # ── client_notes ────────────────────────────────────────────────────────
    op.create_table(
        "client_notes",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=True),
        sa.Column("author_name", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_client_notes_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_client_notes_author_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_client_notes"),
    )
    op.create_index(
        "ix_client_notes_client_id_created_at", "client_notes", ["client_id", "created_at"]
    )

    # ── tasks ───────────────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("assigned_to_id", UUID, nullable=True),
        sa.Column("priority", sa.String(16), server_default="NORMAL", nullable=False),
        sa.Column("status", sa.String(16), server_default="TODO", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_tasks_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name="fk_tasks_client_id_clients", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            name="fk_tasks_assigned_to_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        sa.CheckConstraint(_in_list("status", TASK_STATUSES), name="status"),
        sa.CheckConstraint(_in_list("priority", TASK_PRIORITIES), name="priority"),
        # Invariant: o sarcină e gata dacă și numai dacă are dată de finalizare.
        sa.CheckConstraint("(status = 'DONE') = (completed_at IS NOT NULL)", name="completed_at"),
    )
    op.create_index("ix_tasks_organization_id", "tasks", ["organization_id"])
    op.create_index("ix_tasks_deleted_at", "tasks", ["deleted_at"])
    op.create_index("ix_tasks_organization_id_status", "tasks", ["organization_id", "status"])
    op.create_index("ix_tasks_assigned_to_id", "tasks", ["assigned_to_id"])
    op.create_index("ix_tasks_client_id", "tasks", ["client_id"])
    op.create_index("ix_tasks_due_date", "tasks", ["due_date"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("client_notes")
    op.drop_table("contacts")
    op.drop_table("client_tags")
    op.drop_index("ix_clients_name_trgm", table_name="clients")
    op.drop_table("clients")
    op.drop_table("tags")
    op.execute("DROP FUNCTION IF EXISTS app_unaccent(text)")
    # Extensiile rămân: pot fi folosite de altceva în aceeași bază.
