"""Ce a învățat sistemul despre cine trimite ce

Un document ajunge `UNMATCHED` când clientul nu se poate deduce din codurile
fiscale: un extras de cont nu are CUI, o poză de bon nu are text, iar OCR-ul
citește uneori greșit. Un om îl atribuie. Luna viitoare vine altul, de la aceeași
adresă, și sistemul îl lasă iar `UNMATCHED` — aceeași muncă, la nesfârșit.

Tabelul reține legătura dintre **expeditor** și client, dar numai când decizia a
fost a unui om. O potrivire automată nu scrie niciodată aici: altfel sistemul
și-ar amplifica propriile greșeli, iar prima potrivire greșită s-ar transforma
într-o regulă.

Cheia unică pe `(organization_id, kind, value)` este partea care contează:
o adresă duce la **un** client. Fără ea, două rânduri pentru aceeași adresă ar
face potrivirea să depindă de ordinea în care sunt citite — adică de nimic.
Atribuirea nouă mută rândul, nu adaugă unul: ultima decizie a unui om câștigă.

`ON DELETE CASCADE` pe client: aliasurile unui client șters nu au ce recunoaște.
`ON DELETE SET NULL` pe autor: plecarea unui coleg nu șterge ce a învățat
sistemul de la el.

Revision ID: 3a91c4d7e5b8
Revises: 8f3d61c47a92
Create Date: 2026-09-05 11:50
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3a91c4d7e5b8"
down_revision: str | None = "8f3d61c47a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=320), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.CheckConstraint("kind IN ('SENDER')", name="kind"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "kind", "value", name="uq_client_aliases_value"),
    )
    op.create_index("ix_client_aliases_organization_id", "client_aliases", ["organization_id"])
    op.create_index("ix_client_aliases_client_id", "client_aliases", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_client_aliases_client_id", table_name="client_aliases")
    op.drop_index("ix_client_aliases_organization_id", table_name="client_aliases")
    op.drop_table("client_aliases")
