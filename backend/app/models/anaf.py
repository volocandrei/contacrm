"""Legătura cu Spațiul Privat Virtual al ANAF (M11).

Două tabele, cu roluri despărțite exact ca la Microsoft, dar din alt motiv:

`anaf_connections` — **certificatul** prin care întrebăm. Unul singur activ per
organizație, pentru că un cabinet are un singur certificat digital calificat
înrolat în SPV, iar tot ce vede acolo vede prin el.

`anaf_mandates` — **împuternicirile**. Aici este diferența de fond față de
OneDrive: certificatul singur nu deschide nimic. Pentru fiecare client, ANAF cere
o împuternicire depusă în SPV (formularul 150) prin care clientul dă dreptul
deținătorului certificatului să îi vadă mesajele. Fără ea, interogarea pe CUI-ul
lui întoarce gol — nu o eroare, ci pur și simplu nimic, care este forma cea mai
neplăcută de refuz.

Un rând aici înseamnă deci **două** lucruri, și amândouă trebuie să fie
adevărate: clientul a semnat împuternicirea la ANAF, iar noi știm ce CUI să
interogăm pentru el.

**De ce CUI-ul stă și aici, deși îl are și clientul.** Pentru că este cheia
cererii către ANAF, iar cheia unei cereri externe nu are voie să se schimbe tăcut
sub noi: cineva corectează CUI-ul unui client în CRM, iar sincronizarea ar începe
să interogheze altă firmă. Aici stă forma normalizată (fără prefixul `RO`), cea
pe care o acceptă API-ul, și se schimbă numai când cineva schimbă împuternicirea.

`synced_through` este echivalentul tokenului delta de la Microsoft: până când
anume am citit lista de mesaje. ANAF nu dă tokenuri, dă ferestre de timp — deci
îl ținem noi, și îl mutăm **abia după** ce facturile din fereastră au intrat.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrganizationMixin, TimestampMixin, uuid_pk


class AnafConnection(Base, OrganizationMixin, TimestampMixin):
    """Certificatul digital prin care cabinetul interoghează SPV-ul."""

    __tablename__ = "anaf_connections"
    __table_args__ = (
        # `prod` și `test` sunt baze separate la ANAF. O conexiune de test care ar
        # trece drept producție ar raporta „nicio factură" la nesfârșit.
        CheckConstraint("environment IN ('prod', 'test')", name="environment"),
        # O singură conexiune activă per organizație. Index **parțial**: o
        # conexiune veche, dezactivată, nu blochează reconectarea de anul viitor.
        Index(
            "uq_anaf_connections_active",
            "organization_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid_pk]
    environment: Mapped[str] = mapped_column(String(16), default="prod", nullable=False)
    #: Criptat cu `DRIVE_TOKEN_KEY`, ca tokenul Microsoft. Nu iese niciodată prin
    #: API, nici întreg, nici trunchiat (§73).
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    #: Cine a autorizat, așa cum îl declară tokenul ANAF. Se afișează pe ecran ca
    #: administratorul să recunoască certificatul folosit; nu participă la nicio
    #: decizie.
    certificate_holder: Mapped[str | None] = mapped_column(String(255), default=None)
    #: Când expiră refresh tokenul. ANAF îl dă valabil un an, iar reînnoirea cere
    #: din nou certificatul în browser — deci trebuie anunțat un om **înainte**,
    #: nu descoperit după ce preluarea s-a oprit.
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    connected_at: Mapped[datetime] = mapped_column(nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Ultima eroare care privește **conexiunea**, nu un client anume: token
    #: expirat, cheie de criptare schimbată, ANAF picat.
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    mandates: Mapped[list[AnafMandate]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AnafConnection {self.environment} {self.certificate_holder!r}>"


class AnafMandate(Base, OrganizationMixin, TimestampMixin):
    """Împuternicirea depusă de un client, plus starea preluării lui."""

    __tablename__ = "anaf_mandates"
    __table_args__ = (
        # Același CUI nu se interoghează de două ori: ar produce două documente
        # pentru fiecare factură, iar ANAF ar primi dublul cererilor degeaba.
        UniqueConstraint("organization_id", "tax_id", name="uq_anaf_mandates_tax_id"),
        # Un client are un singur CUI, deci o singură împuternicire.
        UniqueConstraint("organization_id", "client_id", name="uq_anaf_mandates_client"),
        CheckConstraint("char_length(tax_id) BETWEEN 2 AND 32", name="tax_id_present"),
        CheckConstraint("invoices_ingested >= 0", name="invoices_ingested_positive"),
        Index("ix_anaf_mandates_connection_id", "connection_id"),
    )

    id: Mapped[uuid_pk]
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("anaf_connections.id", ondelete="CASCADE"), nullable=False
    )
    #: Clientul ale cărui facturi le preluăm. Obligatoriu: o împuternicire fără
    #: client nu are ce să însemne — spre deosebire de un dosar din OneDrive,
    #: care poate exista nemapat, aici CUI-ul *este* clientul.
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    #: CUI-ul în forma pe care o cere API-ul: doar cifre, fără `RO`, fără spații.
    #: Vezi `app.domain.romanian_documents.normalize_tax_id`.
    tax_id: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Până când am citit lista de mesaje. `NULL` = împuternicire nouă, prima
    #: citire pleacă de la `ANAF_LOOKBACK_DAYS` în urmă.
    synced_through: Mapped[datetime | None] = mapped_column(default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Ultima eroare care privește **acest client**: împuternicire lipsă sau
    #: expirată, CUI respins de ANAF. Se arată pe rândul lui, nu pe conexiune.
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    #: Câte facturi au intrat de aici. Un contor, nu o sursă de adevăr.
    invoices_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connection: Mapped[AnafConnection] = relationship(back_populates="mandates")

    def __repr__(self) -> str:
        return f"<AnafMandate {self.tax_id}>"
