"""Legătura cu contul Microsoft al cabinetului (M9, M10).

Două tabele, cu roluri clar despărțite:

`microsoft_connections` — **contul** prin care citim. Unul singur activ per
organizație: cabinetul se conectează cu contul lui Microsoft, iar de acolo vede
tot ce vede și în browser — dosarele partajate de clienți **și** cutia poștală.
Un singur consimțământ, două surse de documente.

`drive_folders` — **dosarele urmărite**, fiecare legat de un client. Asta este
piesa care rezolvă cererea: contabilul are deja un dosar per client, iar
maparea aceea devine identificarea automată a clientului. Un fișier apărut în
dosarul „Alfa Conta SRL" aparține lui Alfa Conta SRL, fără să fie nevoie să se
citească vreun CUI de pe el.

`delta_token` este cum aflăm ce s-a schimbat fără să recitim tot dosarul: Graph
întoarce un token la fiecare listare, iar următoarea cerere cu el întoarce doar
diferența. Fără el, un dosar cu un an de facturi s-ar reciti la fiecare tur.
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


class MicrosoftConnection(Base, OrganizationMixin, TimestampMixin):
    """Contul Microsoft prin care cabinetul citește dosarele și emailurile."""

    __tablename__ = "microsoft_connections"
    __table_args__ = (
        CheckConstraint("provider IN ('microsoft')", name="provider"),
        # O singură conexiune activă per organizație și provider. Index **parțial**:
        # o conexiune veche, dezactivată, nu trebuie să blocheze reconectarea.
        Index(
            "uq_microsoft_connections_active",
            "organization_id",
            "provider",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid_pk]
    provider: Mapped[str] = mapped_column(String(32), default="microsoft", nullable=False)
    #: Contul cu care s-a dat consimțământul — se afișează, ca administratorul să
    #: știe cine este conectat. Nu este un secret.
    account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), default=None)
    #: Refresh tokenul, **criptat** (`app/core/crypto.py`). Nu iese niciodată
    #: printr-un răspuns HTTP (§73) — nici măcar trunchiat.
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ce am cerut la consimțământ. Util când Microsoft schimbă cerințele și un
    #: scope lipsă explică un 403 care altfel ar părea o eroare de cod.
    scopes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    connected_at: Mapped[datetime] = mapped_column(nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Ultima eroare, în cuvinte. Un token expirat trebuie să se vadă pe ecran, nu
    #: doar în loguri: altfel documentele pur și simplu nu mai vin și nimeni nu știe.
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    folders: Mapped[list[DriveFolder]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    mail_folders: Mapped[list[MailFolder]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<MicrosoftConnection {self.provider} {self.account_email!r}>"


class DriveFolder(Base, OrganizationMixin, TimestampMixin):
    """Un dosar urmărit, legat de clientul căruia îi aparțin documentele."""

    __tablename__ = "drive_folders"
    __table_args__ = (
        # Același dosar nu se urmărește de două ori: al doilea rând ar produce
        # două intake-uri pentru fiecare fișier.
        UniqueConstraint("organization_id", "drive_id", "item_id", name="uq_drive_folders_item"),
        Index("ix_drive_folders_connection_id", "connection_id"),
        Index("ix_drive_folders_client_id", "client_id"),
    )

    id: Mapped[uuid_pk]
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("microsoft_connections.id", ondelete="CASCADE"), nullable=False
    )
    #: Clientul căruia îi aparțin documentele din dosar. `NULL` înseamnă „încă
    #: nemapat": fișierele intră, dar rămân `UNMATCHED` și așteaptă un om — la fel
    #: ca înainte. Nu presupunem nimic dintr-un dosar fără client.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), default=None
    )
    #: Identificatorii Microsoft. `drive_id` distinge OneDrive-ul personal de o
    #: bibliotecă SharePoint; `item_id` este dosarul propriu-zis.
    drive_id: Mapped[str] = mapped_column(String(255), nullable=False)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Calea lizibilă, pentru ecran. Nu se folosește la citire — Graph lucrează pe
    #: id-uri, iar o cale se schimbă când cineva redenumește un dosar.
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: Tokenul de la ultima listare. `NULL` = dosar nou, se citește de la început.
    delta_token: Mapped[str | None] = mapped_column(Text, default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    #: Câte fișiere au intrat de aici. Un contor, nu o sursă de adevăr: numărul
    #: real de documente se numără oricând din `documents`.
    files_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connection: Mapped[MicrosoftConnection] = relationship(back_populates="folders")

    def __repr__(self) -> str:
        return f"<DriveFolder {self.path!r}>"


class MailFolder(Base, OrganizationMixin, TimestampMixin):
    """Un dosar din cutia poștală, din ale cărui mesaje luăm atașamentele.

    **Diferența de fond față de `DriveFolder`: cine dă clientul.** La drive,
    dosarul — contabilul l-a mapat o dată și gata. La email, dosarul nu spune
    nimic: într-o cutie poștală intră toți clienții deodată. Clientul îl dă
    **expeditorul**, potrivit pe adresele de contact din CRM (`contacts.email`).

    Consecința practică: aici nu există `client_id`. Un mesaj de la o adresă
    necunoscută intră oricum, dar rămâne neatribuit și așteaptă un om — mai bine
    decât să nu intre deloc, pentru că atunci nimeni nu ar ști că a venit.
    """

    __tablename__ = "mail_folders"
    __table_args__ = (
        # Același dosar citit de două ori ar produce două intake-uri per atașament.
        UniqueConstraint("organization_id", "folder_id", name="uq_mail_folders_folder"),
        Index("ix_mail_folders_connection_id", "connection_id"),
    )

    id: Mapped[uuid_pk]
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("microsoft_connections.id", ondelete="CASCADE"), nullable=False
    )
    #: Identificatorul dosarului la Graph. `inbox` este un nume rezervat pe care
    #: îl acceptă direct, deci merge și fără să răsfoim întâi.
    folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    delta_token: Mapped[str | None] = mapped_column(Text, default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    files_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connection: Mapped[MicrosoftConnection] = relationship(back_populates="mail_folders")

    def __repr__(self) -> str:
        return f"<MailFolder {self.display_name!r}>"
