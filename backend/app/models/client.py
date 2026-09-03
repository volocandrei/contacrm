"""Clienți, contacte, note și etichete (§4).

Clientul este entitatea în jurul căreia se organizează tot restul: documentele se
atribuie unui client, perioadele contabile sunt per client, sarcinile îl referă.
De aceea se șterge logic, niciodată fizic — un client șters ar lăsa documente
contabile orfane.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ClientStatus
from app.models.base import (
    Base,
    EnumString,
    OrganizationMixin,
    SoftDeleteMixin,
    TimestampMixin,
    enum_check,
    uuid_pk,
)

client_tags = Table(
    "client_tags",
    Base.metadata,
    Column("client_id", ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base, OrganizationMixin, TimestampMixin):
    """Etichetă liberă pe client (§4). Se administrează per organizație."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_tags_organization_id_name"),
    )

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Culoarea e opțională: interfața are un implicit dacă lipsește.
    color: Mapped[str | None] = mapped_column(String(16), default=None)

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"


class Client(Base, OrganizationMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "clients"
    __table_args__ = (
        # Numele constrângerilor primesc prefixul din convenția de denumire
        # (`ck_%(table_name)s_%(constraint_name)s`), deci aici se dă doar sufixul.
        CheckConstraint(enum_check("status", ClientStatus), name="status"),
        # CUI-ul este unic per organizație, dar doar printre clienții neșterși —
        # constrângerea parțială se definește în migrare, unde poate avea WHERE.
        Index("ix_clients_organization_id_status", "organization_id", "status"),
        Index("ix_clients_assigned_accountant_id", "assigned_accountant_id"),
    )

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # CUI. Poate lipsi pentru un prospect care încă nu a trimis datele.
    tax_id: Mapped[str | None] = mapped_column(String(32), default=None)
    registration_number: Mapped[str | None] = mapped_column(String(64), default=None)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[ClientStatus] = mapped_column(
        EnumString(ClientStatus, 16), default=ClientStatus.PROSPECT, nullable=False
    )
    # SET NULL: plecarea unui contabil nu șterge clientul, doar îl lasă neatribuit.
    assigned_accountant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(default=None)

    tags: Mapped[list[Tag]] = relationship(secondary=client_tags, lazy="selectin")
    contacts: Mapped[list[Contact]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    notes: Mapped[list[ClientNote]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    @property
    def tag_names(self) -> list[str]:
        return sorted(tag.name for tag in self.tags)

    def __repr__(self) -> str:
        return f"<Client {self.name!r}>"


class Contact(Base, TimestampMixin, SoftDeleteMixin):
    """Persoana de contact. Emailul și numărul de WhatsApp sunt cheile de intake:
    după ele se identifică expeditorul unui document (§8)."""

    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_client_id", "client_id"),
        # Căutarea inversă la intake: de la adresa expeditorului la client.
        Index("ix_contacts_email", "email"),
        Index("ix_contacts_whatsapp_number", "whatsapp_number"),
    )

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), default=None)
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    client: Mapped[Client] = relationship(back_populates="contacts")

    def __repr__(self) -> str:
        return f"<Contact {self.full_name!r}>"


class ClientNote(Base, TimestampMixin):
    """Notă internă pe client. Autorul se păstrează ca text chiar dacă utilizatorul
    dispare — cine a scris o notă nu trebuie să se piardă."""

    __tablename__ = "client_notes"
    __table_args__ = (Index("ix_client_notes_client_id_created_at", "client_id", "created_at"),)

    id: Mapped[uuid_pk]
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    client: Mapped[Client] = relationship(back_populates="notes")

    def __repr__(self) -> str:
        return f"<ClientNote client={self.client_id}>"
