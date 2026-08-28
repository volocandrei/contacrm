"""Baza ORM și mixin-urile comune.

Deciziile care se aplică fiecărui tabel, luate o singură dată aici:

- cheile primare sunt UUID, nu întregi secvențiali — id-urile ajung în URL-uri și
  în nume de fișiere, iar un id ghicibil expune volumul de business;
- timpul este întotdeauna `timestamptz`, niciodată naiv (§71);
- banii sunt `NUMERIC(18, 2)`, niciodată float (§72);
- entitățile de business poartă `organization_id` de la început (§33, R10), chiar
  dacă v1 rulează cu o singură organizație — adăugarea ulterioară ar fi o migrare
  riscantă peste date reale;
- entitățile de business se șterg logic (`deleted_at`), nu fizic (R8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convenție de denumire explicită: fără ea, Alembic generează nume de constrângeri
# diferite de la o rulare la alta și migrările devin imposibil de dat înapoi.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]
money = Annotated[Decimal, mapped_column(Numeric(18, 2))]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        # Fără maparea asta `Mapped[datetime]` devine `DateTime` FĂRĂ fus orar, deși
        # migrările creează `timestamptz`: ORM-ul ar citi datetime-uri naive, iar orice
        # comparație cu `datetime.now(UTC)` ar arunca TypeError abia la runtime.
        datetime: DateTime(timezone=True),
        uuid.UUID: postgresql.UUID(as_uuid=True),
        Decimal: Numeric(18, 2),
    }


class TimestampMixin:
    """`created_at` / `updated_at` calculate de baza de date, nu de aplicație."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Ștergerea marchează, nu distruge — documentele contabile sunt probe (R8)."""

    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class OrganizationMixin:
    """Discriminatorul de tenant. Filtrarea se face în repository, nu în endpoint."""

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
