"""Linkul de trimitere știe pentru ce lună a fost deschis

Un cabinet cere documentele a treizeci de clienți în aceeași săptămână. Fără o
urmă, peste trei zile nu mai știe pe cine a întrebat: îi cere de două ori unuia
și îl uită complet pe altul. Nu este o pierdere de timp, este o lună întârziată.

Urma există deja — linkul deschis când s-a compus cererea, cu ora lui și cu
contorul de documente sosite prin el. Îi lipsea doar **pentru ce lună**, singura
informație care leagă un link de o cerere anume.

Rămâne nulă pentru linkurile deschise din fișa clientului: acelea nu sunt cereri,
ci un drum lăsat deschis. Diferența se vede exact în coloana asta.

Revision ID: 9d4f7a2c81e6
Revises: 6b2e8f41d9c3
Create Date: 2026-09-05 17:20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d4f7a2c81e6"
down_revision: str | None = "6b2e8f41d9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "client_upload_links",
        sa.Column("reference_month", sa.String(length=7), nullable=True),
    )
    # Căutarea este întotdeauna „cererile organizației pentru luna X": un index
    # pe lună singură ar fi inutil, fiindcă filtrul pe organizație vine oricum.
    op.create_index(
        "ix_client_upload_links_org_month",
        "client_upload_links",
        ["organization_id", "reference_month"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_upload_links_org_month", table_name="client_upload_links")
    op.drop_column("client_upload_links", "reference_month")
