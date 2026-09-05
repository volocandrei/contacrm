"""Linkul prin care clientul își trimite singur documentele (§5).

**Problema pe care o rezolvă.** Partea cea mai grea a muncii unui cabinet nu este
procesarea documentelor, ci **adunarea** lor. Clientul trebuie să se apuce: să
scaneze, să atașeze la un email, să nu depășească limita de mărime, să nu uite
jumătate. Fiecare pas în plus de partea lui înseamnă o lună întârziată de partea
voastră.

Linkul mută efortul de unde e scump la unde e ieftin: clientul deschide o adresă,
trage fișierele, gata. Fără cont, fără parolă, fără aplicație de instalat.
Documentele ajung direct la clientul potrivit — apartenența vine din link, nu din
ghicit, ca la e-Factura.

**Ce înseamnă că este public.** Este singurul loc din aplicație care acceptă o
scriere fără sesiune. De aceea:

- **Tokenul se păstrează ca hash**, ca refresh tokenurile: o bază de date citită
  de altcineva nu trebuie să dea linkuri funcționale.
- **Nu se poate citi nimic prin el.** Nu listează, nu descarcă, nu spune ce s-a
  trimis deja. Cine are linkul poate doar să adauge.
- **Expiră și se poate revoca.** Un link trimis într-un email rămâne în inbox-ul
  acelui email pentru totdeauna; trebuie să existe un moment în care încetează.
- **Numele clientului nu apare pe pagină.** Un link ajuns din greșeală la altcineva
  n-are voie să spună cine este clientul cabinetului.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, TimestampMixin, uuid_pk


class ClientUploadLink(Base, OrganizationMixin, TimestampMixin):
    """Un drum de trimitere, deschis pentru un client."""

    __tablename__ = "client_upload_links"
    __table_args__ = (
        Index("ix_client_upload_links_client_id", "client_id"),
        # „Cererile cabinetului pentru luna X": filtrul pe lună nu vine niciodată
        # singur, deci indexul începe cu organizația.
        Index("ix_client_upload_links_org_month", "organization_id", "reference_month"),
        # Căutarea se face **numai** după hash: tokenul brut nu este stocat nicăieri.
        Index("ix_client_upload_links_token_hash", "token_hash", unique=True),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    #: SHA-256 al tokenului. Tokenul brut se arată **o singură dată**, la creare.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: După ce dată nu mai primește nimic. Un link fără sfârșit rămâne valabil în
    #: inbox-ul cuiva ani de zile.
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Oprit înainte de expirare, de un om.
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Luna pentru care s-a cerut, când linkul s-a deschis dintr-o solicitare.
    #:
    #: **Nulă pentru linkurile deschise din fișa clientului.** Acelea nu sunt
    #: cereri, ci un drum lăsat deschis; diferența se vede exact aici. Cu ea,
    #: rândul devine urma întrebării: cui i s-a cerut, pentru ce lună, când, și
    #: dacă a trimis ceva pe drumul acela.
    reference_month: Mapped[str | None] = mapped_column(String(7), default=None)
    #: Câte documente au intrat pe aici. Spune dacă drumul chiar este folosit.
    upload_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)

    def __repr__(self) -> str:
        return f"<ClientUploadLink client={self.client_id} used={self.upload_count}>"
