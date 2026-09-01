"""document_processing_jobs: starea SKIPPED

Tabelul devine outbox-ul cererilor de procesare (§38, §43): rândul se scrie în
aceeași tranzacție cu documentul, iar workerul îl revendică. Asta face necesară o
a cincea stare: „documentul a mers între timp în altă parte, nu mai e nimic de
făcut". Nu este o eroare — a o înregistra ca `FAILED` ar umple raportul de eșecuri
cu lucruri care au mers exact cum trebuia.

Revision ID: 9b3ac41d5e08
Revises: 4c1d9f0b2e77
Create Date: 2026-09-01 19:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9b3ac41d5e08"
down_revision: str | None = "4c1d9f0b2e77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')"
NEW = "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')"


def upgrade() -> None:
    op.drop_constraint("status", "document_processing_jobs", type_="check")
    op.create_check_constraint("status", "document_processing_jobs", NEW)


def downgrade() -> None:
    # Rândurile `SKIPPED` ar bloca constrângerea veche; nu sunt un eșec, dar nici
    # nu au cum să rămână — le tratăm ca reușite fără efect.
    op.execute("UPDATE document_processing_jobs SET status = 'SUCCEEDED' WHERE status = 'SKIPPED'")
    op.drop_constraint("status", "document_processing_jobs", type_="check")
    op.create_check_constraint("status", "document_processing_jobs", OLD)
