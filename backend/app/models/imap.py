"""Cutia poștală obișnuită, citită prin IMAP.

**Golul pe care îl umple.** Preluarea din email exista de la M10, dar numai prin
Microsoft Graph — adică numai pentru cabinetele care sunt pe Microsoft 365. În
România, cabinetul mic are cutia la Gmail, la Yahoo sau la găzduirea unde îi stă
și site-ul. Pentru toate acelea, „documentele intră singure din email" era o
propoziție adevărată despre alt cabinet.

**De ce alt tabel, și nu o coloană în `microsoft_connections`.** Nu au nimic
comun: acolo un token OAuth reînnoit automat și un id de dosar de la Graph, aici
un server, un port, un utilizator și o parolă. Turnate în același tabel, jumătate
din coloane ar fi fost mereu nule, iar cine citește schema n-ar mai fi știut care
combinație este validă.

**Parola stă criptată**, cu aceeași cheie ca tokenurile Microsoft
(`DRIVE_TOKEN_KEY`), și nu iese niciodată prin API — nici întreagă, nici
trunchiată (§73). Fără cheia de criptare, conectarea este refuzată din capul
locului: mai bine decât să scriem o parolă în clar „doar de data asta".

**Citim, nu scriem.** Dosarul se deschide în mod read-only: aplicația nu marchează
mesajele ca citite și nu le mută. Cutia poștală este a cabinetului, iar un
program care umblă prin ea își pierde dreptul de a mai fi lăsat acolo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, TimestampMixin, uuid_pk

#: Portul obișnuit pentru IMAP peste TLS. Cel fără criptare (143) nu se propune.
DEFAULT_IMAP_PORT = 993

#: Dosarul din care se citește, dacă nu se spune altul. Numele este standard.
DEFAULT_FOLDER = "INBOX"


class ImapMailbox(Base, OrganizationMixin, TimestampMixin):
    """O cutie poștală citită prin IMAP."""

    __tablename__ = "imap_mailboxes"
    __table_args__ = (
        # Aceeași cutie și același dosar, adăugate de două ori, ar produce două
        # intake-uri pentru fiecare atașament.
        UniqueConstraint("organization_id", "username", "folder", name="uq_imap_mailboxes_account"),
    )

    id: Mapped[uuid_pk]
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(default=DEFAULT_IMAP_PORT, nullable=False)
    #: Aproape întotdeauna adevărat. Există ca să se poată conecta un server de
    #: test în rețeaua locală, nu ca opțiune de recomandat.
    use_ssl: Mapped[bool] = mapped_column(default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Criptată cu `DRIVE_TOKEN_KEY`. Nu iese niciodată prin API (§73).
    #:
    #: La Gmail și la Microsoft trebuie să fie o **parolă de aplicație**, nu
    #: parola contului: cele două servicii resping de mult IMAP cu parola
    #: obișnuită, iar mesajul lor de eroare nu spune asta.
    password: Mapped[str] = mapped_column(String(1024), nullable=False)
    folder: Mapped[str] = mapped_column(String(255), default=DEFAULT_FOLDER, nullable=False)

    #: Ultimul UID citit. Preluarea continuă de la el, nu de la început.
    last_uid: Mapped[int] = mapped_column(default=0, nullable=False)
    #: `UIDVALIDITY` al dosarului la ultima citire.
    #:
    #: **De ce se ține minte.** UID-urile sunt unice doar cât timp valoarea asta
    #: nu se schimbă. Când serverul o schimbă — o restaurare, o migrare de cutie —
    #: numerele se reatribuie de la capăt, iar continuarea de la `last_uid` ar
    #: sări peste tot ce a venit între timp, tăcut. Atunci se ia dosarul de la
    #: început; idempotența pe `Message-ID` face ca nimic să nu intre de două ori.
    uid_validity: Mapped[int | None] = mapped_column(default=None)

    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Ultima eroare, ca să se vadă. O parolă schimbată oprește preluarea, iar
    #: fără rândul ăsta documentele pur și simplu nu mai vin și nimeni nu află.
    last_error: Mapped[str | None] = mapped_column(String(255), default=None)
    files_ingested: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    def __repr__(self) -> str:
        return f"<ImapMailbox {self.username}/{self.folder}>"
