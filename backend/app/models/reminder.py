"""Reminderul trimis unui client: urma că aplicația a scris singură.

**De ce un tabel și nu jurnalul de audit.** Auditul răspunde cine/ce/când și
atât (§33); a-l interoga ca să decizi dacă mai trimiți un mesaj ar însemna că o
regulă de business citește un registru de probe. Aici stă exact ce trebuie ca
regula să fie decidabilă: cui, pentru ce lună, când, unde a ajuns.

**De ce contorul contează.** Un reminder nu este o notificare, este un mesaj în
numele cabinetului către clientul lui. Al treilea într-o lună nu mai aduce
documentele mai repede; aduce un client care filtrează adresa cabinetului. Fără
rândurile astea, o rulare de cron dublată ar trimite de două ori în aceeași
dimineață și nimeni n-ar afla decât de la client.

Rândul nu poartă textul mesajului. Ce a scris cabinetul se recompune oricând din
lună și din ce lipsea; ce nu se poate reface este faptul că a plecat.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrganizationMixin, TimestampMixin, uuid_pk

#: Canalul pe care a plecat. Deocamdată doar emailul pleacă singur: WhatsApp se
#: deschide dintr-un buton, de un om, deci nu lasă rând aici.
CHANNEL_EMAIL = "EMAIL"


class ClientReminder(Base, OrganizationMixin, TimestampMixin):
    """Un mesaj de reamintire, plecat către un client."""

    __tablename__ = "client_reminders"
    __table_args__ = (
        # Întrebarea vine mereu în forma „câte i-am trimis lui X pentru luna Y".
        Index("ix_client_reminders_client_id_period", "client_id", "reference_month"),
        # Indexul pe `organization_id` vine din `OrganizationMixin`.
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    #: Luna pentru care s-a reamintit. Un reminder fără lună n-ar putea fi numărat
    #: contra plafonului lunar, deci nu există.
    reference_month: Mapped[str] = mapped_column(String(7), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Adresa, nu contactul: contactul se poate schimba, urma trebuie să spună
    #: unde a ajuns mesajul atunci.
    sent_to: Mapped[str] = mapped_column(String(320), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default=CHANNEL_EMAIL, nullable=False)
    #: Linkul pe care l-a purtat mesajul, dacă mai există. `SET NULL` la ștergere:
    #: faptul că am reamintit nu dispare odată cu drumul.
    link_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("client_upload_links.id", ondelete="SET NULL"), default=None
    )
    #: Cine a apăsat, dacă a apăsat cineva. Nul înseamnă că a plecat de la sine,
    #: la ora planificatorului — diferența dintre „cabinetul a scris" și
    #: „aplicația a scris" nu are voie să se piardă.
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    def __repr__(self) -> str:
        return f"<ClientReminder client={self.client_id} {self.reference_month}>"
