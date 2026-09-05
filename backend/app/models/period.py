"""Perioade contabile și ce se așteaptă de la fiecare client (§18, §19).

Tabelele de aici țin **doar faptele umane**: că cineva a deschis o lună, că cineva
a închis-o, și ce tipuri de document se așteaptă de la un client anume.

Contoarele și starea lunii **nu se stochează**. Se calculează din documente, la
citire. Un status ținut într-o coloană se desincronizează de contoarele lui în
tăcere — exact ce s-a întâmplat în backendul simulat, unde perioade marcate
„complete" aveau documente obligatorii lipsă. Ce se poate deriva, se derivă
(`app/domain/periods.py`).

Închiderea este singura excepție, și tocmai de aceea se păstrează: este o decizie
contabilă, nu un calcul.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, TimestampMixin, uuid_pk


class AccountingPeriod(Base, OrganizationMixin, TimestampMixin):
    """O lună contabilă a unui client.

    Rândul există din momentul în care cineva o atinge — o deschide, o închide, sau
    primul document ajunge în ea. Absența rândului nu înseamnă că luna nu există;
    înseamnă că nu s-a întâmplat încă nimic în ea.
    """

    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "client_id", "reference_month", name="uq_period_client_month"
        ),
        CheckConstraint(
            "reference_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="reference_month_format"
        ),
        # Cine a închis luna implică și când. Invers nu: o lună poate fi închisă de
        # un utilizator care între timp a fost șters (`ON DELETE SET NULL`), iar
        # faptul închiderii nu are voie să dispară odată cu el.
        CheckConstraint("closed_by IS NULL OR closed_at IS NOT NULL", name="closed_has_moment"),
        Index(
            "ix_accounting_periods_organization_id_reference_month",
            "organization_id",
            "reference_month",
        ),
        Index("ix_accounting_periods_client_id", "client_id"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    # „YYYY-MM". Redundant cu `year`/`month`, dar este forma în care circulă prin API
    # și după care se filtrează; a o recompune la fiecare interogare ar fi cost fără
    # rost.
    reference_month: Mapped[str] = mapped_column(String(7), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    opened_at: Mapped[datetime | None] = mapped_column(default=None)
    # Închiderea: actul prin care cineva spune „luna asta este gata".
    closed_at: Mapped[datetime | None] = mapped_column(default=None)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Momentul în care checklistul a fost prima dată complet. Diferit de închidere:
    # o lună poate fi completă fără ca nimeni să o fi închis încă.
    completed_at: Mapped[datetime | None] = mapped_column(default=None)

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    def __repr__(self) -> str:
        return f"<AccountingPeriod {self.client_id} {self.reference_month}>"


class ClientExpectation(Base, OrganizationMixin, TimestampMixin):
    """Ce tipuri de document se așteaptă lunar de la un client, și câte (§19).

    Per client, nu global: un cabinet știe că de la firma X vin cinci facturi de
    intrare și un extras de cont, iar de la firma Y nu vine niciun extras. Un
    checklist identic pentru toți ar raporta lipsuri inexistente, iar un raport care
    strigă degeaba ajunge să nu mai fie citit.
    """

    __tablename__ = "client_expectations"
    __table_args__ = (
        UniqueConstraint("client_id", "document_type_id", name="uq_client_expectation_client_type"),
        CheckConstraint("expected_min_count >= 1", name="expected_min_positive"),
        Index("ix_client_expectations_client_id", "client_id"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_types.id", ondelete="CASCADE"), nullable=False
    )
    expected_min_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ClientExpectation {self.client_id} {self.document_type_id} "
            f"x{self.expected_min_count}>"
        )


class ExpectationTemplate(Base, OrganizationMixin, TimestampMixin):
    """Un profil de client, cu numele pe care i-l dă cabinetul (§19).

    **De ce există.** Fără așteptări configurate, checklistul lunii este gol,
    „Documente lipsă" nu are ce raporta, iar fiecare lună apare completă pentru
    că nu i se cere nimic. Configurarea se făcea client cu client, bifă cu bifă —
    iar un cabinet cu treizeci de clienți are, în realitate, trei-patru
    profiluri: SRL plătitor de TVA lunar, SRL neplătitor, PFA în sistem real.

    **Nu este o legătură.** Se aplică o dată, iar rezultatul rămâne al clientului:
    cine schimbă pe urmă șablonul nu rescrie tăcut ce s-a configurat manual după
    aceea. Un client care ar „moșteni" la distanță ar face ca o bifă scoasă azi să
    reapară peste o lună fără ca cineva să-i fi atins ecranul — și nimeni n-ar
    ști de ce raportul cere din nou un extras de cont care nu vine.
    """

    __tablename__ = "expectation_templates"
    __table_args__ = (
        # Două profiluri cu același nume nu se pot deosebi pe ecran, iar aplicarea
        # greșită a unuia rescrie checklistul unui client.
        UniqueConstraint("organization_id", "name", name="uq_expectation_template_name"),
        Index("ix_expectation_templates_organization_id", "organization_id"),
    )

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    def __repr__(self) -> str:
        return f"<ExpectationTemplate {self.name!r}>"


class ExpectationTemplateItem(Base, OrganizationMixin, TimestampMixin):
    """Un tip de document dintr-un șablon, cu câte bucăți se așteaptă."""

    __tablename__ = "expectation_template_items"
    __table_args__ = (
        UniqueConstraint("template_id", "document_type_id", name="uq_template_item_type"),
        CheckConstraint("expected_min_count >= 1", name="expected_min_positive"),
        Index("ix_expectation_template_items_template_id", "template_id"),
    )

    id: Mapped[uuid_pk]
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expectation_templates.id", ondelete="CASCADE"), nullable=False
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_types.id", ondelete="CASCADE"), nullable=False
    )
    expected_min_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def __repr__(self) -> str:
        return f"<ExpectationTemplateItem {self.document_type_id} x{self.expected_min_count}>"
