"""Ce a învățat sistemul despre cine trimite ce (§8).

**Problema.** Un document ajunge `UNMATCHED` pentru că nu i se poate deduce
clientul din codurile fiscale: un extras de cont nu are CUI, o poză de bon nu are
text, iar OCR-ul citește uneori greșit. Un om îl atribuie. Luna viitoare vine
altul, de la aceeași adresă, și sistemul îl lasă iar `UNMATCHED`. Aceeași muncă,
în fiecare lună, la nesfârșit.

**Ce reține.** Doar ce a decis un **om**, și doar de la o cheie care identifică
expeditorul, nu documentul: adresa de email de la care a sosit. O potrivire
automată nu produce niciodată un alias — altfel sistemul și-ar amplifica propriile
greșeli, iar prima potrivire greșită s-ar transforma într-o regulă.

**De ce nu învață din codurile fiscale de pe document.** Pe o factură de intrare
apar două coduri: al furnizorului și al clientului nostru. Cel al furnizorului
aparține unui terț care vinde la zeci de firme — legat de un client, ar trimite
toate facturile acelui furnizor la clientul greșit. Iar care dintre cele două este
al clientului nu se știe atâta timp cât tipul documentului nu este stabilit, ceea
ce la `UNMATCHED` este exact cazul. Ce nu se poate ști sigur nu se învață.

**Se poate desface.** Un alias greșit ar trimite tăcut documente la clientul
nepotrivit, lună de lună. De aceea se vede pe fișa clientului și se șterge de
acolo, iar o atribuire nouă de la aceeași adresă îl mută la clientul nou: ultima
decizie a unui om câștigă.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    EnumString,
    OrganizationMixin,
    TimestampMixin,
    enum_check,
    uuid_pk,
)


class AliasKind(StrEnum):
    """După ce se recunoaște expeditorul.

    Un singur fel, deocamdată. Enumerarea există pentru că a doua cheie — numărul
    de WhatsApp — vine odată cu Faza 2, iar coloana trebuie să știe de pe acum că
    valoarea are un înțeles, nu este „un text oarecare".
    """

    SENDER = "SENDER"


class ClientAlias(Base, OrganizationMixin, TimestampMixin):
    """„De la adresa asta vin documentele clientului X."""

    __tablename__ = "client_aliases"
    __table_args__ = (
        CheckConstraint(enum_check("kind", AliasKind), name="kind"),
        # O cheie duce la un singur client. O atribuire nouă o mută, nu o dublează:
        # două rânduri pentru aceeași adresă ar face potrivirea să depindă de
        # ordinea în care sunt citite.
        UniqueConstraint("organization_id", "kind", "value", name="uq_client_aliases_value"),
        Index("ix_client_aliases_client_id", "client_id"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AliasKind] = mapped_column(EnumString(AliasKind, 16), nullable=False)
    #: Normalizat la scriere: adresele se compară fără majuscule și fără spații.
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Cine a decis. Un alias este o urmă a unei decizii umane, nu o observație.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Câte documente a potrivit de când există. Spune dacă a fost o decizie utilă
    #: sau una care nu s-a mai repetat niciodată.
    matched_count: Mapped[int] = mapped_column(default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<ClientAlias {self.kind}:{self.value!r} → {self.client_id}>"
