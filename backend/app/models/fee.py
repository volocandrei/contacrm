"""Onorariile cabinetului: cine cât plătește și cine a plătit.

**Ce este.** Registrul propriu al cabinetului. Un contabil știe pe de rost ce are
de depus pentru fiecare client, dar ține în alt Excel cine i-a plătit luna
trecută. Aplicația are deja lista de clienți, lunile și cine e activ — nu îi mai
lipsea decât suma și data plății.

**Ce nu este.** Nu emite facturi. Nu are serie, număr, TVA sau e-Factura, și nu
va avea aici: o factură este un document cu regim legal, iar un registru care se
preface că emite facturi produce hârtii fără valoare și o falsă liniște. Ce se
ține aici este ce ținea Excelul: sumă, lună, plătit sau nu.

**Două tabele, din același motiv ca la declarații.**

`client_fees` este înțelegerea în vigoare: cât plătește clientul acesta, de când.
Se schimbă când se renegociază.

`fee_entries` este luna facturată, cu **suma înghețată la generare**. Dacă
onorariul crește în martie, ianuarie rămâne cât a fost — altfel istoricul s-ar
rescrie singur la fiecare renegociere, iar un registru care își schimbă trecutul
nu este un registru.

Un rând fără `paid_on` înseamnă „neîncasat". Nu există stare „în curs": banii ori
au intrat, ori nu.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, TimestampMixin, money, uuid_pk

#: Moneda implicită. Cabinetele încasează în lei; restul se scrie explicit.
DEFAULT_CURRENCY = "RON"


class ClientFee(Base, OrganizationMixin, TimestampMixin):
    """Onorariul lunar convenit cu un client."""

    __tablename__ = "client_fees"
    __table_args__ = (
        # Un singur onorariu în vigoare per client: două rânduri ar face
        # imposibil de spus care este cel valabil.
        UniqueConstraint("client_id", name="uq_client_fees_client_id"),
        # Zero este permis — există clienți serviți gratuit, iar un onorariu de 0
        # scris explicit spune altceva decât unul lipsă. Negativ nu înseamnă
        # nimic.
        CheckConstraint("amount >= 0", name="amount_not_negative"),
        # Indexul pe `organization_id` vine din `OrganizationMixin`; declarat încă
        # o dată aici, ar fi produs două intrări cu același nume.
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[money] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)
    #: Prima lună pentru care se facturează. Aplicația nu inventează restanțe pe
    #: lunile de dinaintea contractului — aceeași regulă ca la termene.
    starts_on: Mapped[date] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), default=None)

    def __repr__(self) -> str:
        return f"<ClientFee {self.client_id} {self.amount}>"


class FeeEntry(Base, OrganizationMixin, TimestampMixin):
    """Luna facturată unui client, cu suma de atunci."""

    __tablename__ = "fee_entries"
    __table_args__ = (
        UniqueConstraint("client_id", "period", name="uq_fee_entries_client_id_period"),
        CheckConstraint("amount >= 0", name="amount_not_negative"),
        Index("ix_fee_entries_organization_id_period", "organization_id", "period"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    #: Luna facturată, `YYYY-MM`.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    amount: Mapped[money] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)
    #: Ziua încasării. Lipsa ei **este** starea „neîncasat": un status ținut
    #: separat s-ar desincroniza în tăcere de data pe care o descrie.
    paid_on: Mapped[date | None] = mapped_column(default=None)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(String(255), default=None)

    @property
    def is_paid(self) -> bool:
        return self.paid_on is not None

    def __repr__(self) -> str:
        return f"<FeeEntry {self.client_id} {self.period}>"


__all__ = ["DEFAULT_CURRENCY", "ClientFee", "FeeEntry"]
