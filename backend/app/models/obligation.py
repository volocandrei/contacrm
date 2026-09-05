"""Obligațiile de depunere și ce s-a depus (§18).

**De ce trei tabele și nu unul.**

`obligation_types` este catalogul cabinetului: cum se numește declarația, cât de
des se depune, la câte luni după perioadă și în ce zi. Se administrează din
aplicație, ca `document_types` — termenele nu au voie să stea în cod, fiindcă nu
aplicația știe legea.

`client_obligations` spune **cine ce depune**. Doi clienți identici pe hârtie au,
în realitate, seturi diferite: unul are salariați, altul nu; unul e pe TVA lunar,
altul trimestrial.

`obligation_filings` ține **faptul uman**: cineva a marcat perioada aceasta ca
depusă, când, și cine. Nimic altceva nu se stochează. Dacă o depunere „este la
termen" sau „este întârziată" se calculează la citire, din dată — un status ținut
într-o coloană se desincronizează în tăcere de ceea ce descrie.

Un rând lipsă din `obligation_filings` înseamnă „nedepus". Nu există stare
„în lucru": o declarație ori a plecat, ori nu.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import ObligationFrequency
from app.models.base import Base, EnumString, OrganizationMixin, TimestampMixin, uuid_pk


class ObligationType(Base, OrganizationMixin, TimestampMixin):
    """O declarație pe care cabinetul o depune, cu termenul ei."""

    __tablename__ = "obligation_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_obligation_type_code"),
        # Ziua se retează la ultima zi a lunii la calcul, deci 31 este valid;
        # 0 sau 32 nu ar fi o zi.
        CheckConstraint("deadline_day BETWEEN 1 AND 31", name="deadline_day_is_a_day"),
        # Un termen înainte de sfârșitul perioadei pe care o acoperă nu ar avea
        # ce declara. Zero este permis: există obligații cu termen în chiar luna
        # perioadei.
        CheckConstraint("months_after >= 0", name="months_after_not_negative"),
        Index("ix_obligation_types_organization_id_is_active", "organization_id", "is_active"),
    )

    id: Mapped[uuid_pk]
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    frequency: Mapped[ObligationFrequency] = mapped_column(
        EnumString(ObligationFrequency, 16), nullable=False
    )
    months_after: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deadline_day: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<ObligationType {self.code!r}>"


class ClientObligation(Base, OrganizationMixin, TimestampMixin):
    """Clientul acesta depune declarația aceasta."""

    __tablename__ = "client_obligations"
    __table_args__ = (
        UniqueConstraint("client_id", "obligation_type_id", name="uq_client_obligation"),
        Index("ix_client_obligations_organization_id", "organization_id"),
        Index("ix_client_obligations_client_id", "client_id"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    obligation_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("obligation_types.id", ondelete="CASCADE"), nullable=False
    )


class ObligationFiling(Base, OrganizationMixin, TimestampMixin):
    """Cineva a marcat perioada aceasta ca depusă."""

    __tablename__ = "obligation_filings"
    __table_args__ = (
        # A doua marcare a aceleiași perioade nu are ce adăuga, iar două rânduri
        # ar face imposibil de spus cine a depus.
        UniqueConstraint("client_id", "obligation_type_id", "period", name="uq_obligation_filing"),
        Index("ix_obligation_filings_organization_id_period", "organization_id", "period"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    obligation_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("obligation_types.id", ondelete="CASCADE"), nullable=False
    )
    #: Luna în care se **încheie** perioada acoperită, `YYYY-MM`.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(nullable=False)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(String(255), default=None)


__all__ = ["ClientObligation", "ObligationFiling", "ObligationType"]
