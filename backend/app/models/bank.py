"""Extrasele bancare și tranzacțiile lor (§11, §12, §13).

**De ce nu sunt documente obișnuite.** Un extras de cont ajunge în cabinet ca PDF
sau ca fișier, exact ca o factură — dar ce se face cu el este altceva. O factură
se citește o dată și se arhivează. Un extras se **desface**: fiecare rând al lui
devine o întrebare — „ce factură a plătit banii ăștia?" — iar răspunsul la ea este
munca de reconciliere, adică una dintre cele mai costisitoare ore ale lunii.

De aceea extrasul are tabelele lui. Un document cu text OCR nu se poate interoga
după sumă, dată și contrapartidă, iar potrivirea automată exact asta cere.

**Trei tabele, nu două.**

`BankStatement` este documentul: banca, IBAN-ul, perioada, soldurile.

`BankTransaction` este rândul: dată, sumă, descriere, contrapartidă.

`TransactionMatch` este **legătura**, și are tabel propriu pentru că nu este
unu-la-unu. Realitatea unui cabinet arată așa:

- o plată închide **trei facturi** deodată;
- o factură se plătește în **două tranșe**;
- se plătește **mai mult** decât factura (avans) sau **mai puțin** (rest de plată);
- din sumă se scade un comision.

O coloană `document_id` pe tranzacție ar fi acoperit primul caz din cinci, iar
restul s-ar fi rezolvat prin note scrise de mână — adică nicăieri.

**Suma stă pe legătură, nu pe tranzacție.** Cât din tranzacția asta a mers pe
factura aceea. Fără ea, „plătit parțial" nu se poate scrie deloc.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import BankDirection, BankTransactionStatus
from app.models.base import Base, EnumString, TimestampMixin, enum_check, uuid_pk


class BankStatement(Base, TimestampMixin):
    """Un extras de cont: de la ce bancă, pe ce cont, pe ce perioadă."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        # Același extras importat de două ori nu are voie să dubleze tranzacțiile.
        # Cheia este contul plus perioada plus numărul: două extrase diferite ale
        # aceluiași cont nu pot avea toate trei identice.
        UniqueConstraint(
            "organization_id",
            "iban",
            "period_start",
            "period_end",
            "statement_number",
            name="uq_bank_statements_identity",
        ),
        CheckConstraint("period_end >= period_start", name="period_ordered"),
        Index("ix_bank_statements_organization_id_client_id", "organization_id", "client_id"),
        Index("ix_bank_statements_period_start", "period_start"),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    #: Al cui este contul. Poate lipsi la import, până când cineva îl atribuie —
    #: la fel ca un document ajuns fără client.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), default=None
    )
    #: Documentul din care a venit, dacă a venit dintr-un fișier încărcat. Extrasul
    #: rămâne astfel descărcabil în forma lui originală, ca orice probă contabilă.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )

    bank_name: Mapped[str | None] = mapped_column(String(128), default=None)
    #: Fără spații și cu majuscule — forma în care se compară. IBAN-ul românesc
    #: are 24 de caractere; coloana lasă loc pentru cele străine.
    iban: Mapped[str | None] = mapped_column(String(34), default=None)
    statement_number: Mapped[str | None] = mapped_column(String(64), default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    #: Soldurile declarate de bancă. Nu se calculează din tranzacții: dacă cele
    #: două nu se potrivesc, asta **este** informația — extrasul este incomplet.
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), default=None)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), default=None)

    imported_at: Mapped[datetime] = mapped_column(nullable=False)
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    transactions: Mapped[list[BankTransaction]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        order_by="BankTransaction.booking_date, BankTransaction.position",
    )

    def __repr__(self) -> str:
        return f"<BankStatement {self.iban} {self.period_start}..{self.period_end}>"


class BankTransaction(Base, TimestampMixin):
    """Un rând din extras: o mișcare de bani."""

    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint("statement_id", "position", name="uq_bank_transactions_position"),
        CheckConstraint(enum_check("status", BankTransactionStatus), name="status"),
        CheckConstraint(enum_check("direction", BankDirection), name="direction"),
        # Zero nu este o mișcare de bani. Un rând cu zero este o eroare de import,
        # iar acceptat tăcut ar rămâne pe veci în lista de nepotrivite.
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        Index("ix_bank_transactions_organization_id_status", "organization_id", "status"),
        Index("ix_bank_transactions_client_id", "client_id"),
        Index("ix_bank_transactions_booking_date", "booking_date"),
        # Potrivirea caută după sumă într-o fereastră de dată; indexul le acoperă
        # pe amândouă, în ordinea în care se filtrează.
        Index("ix_bank_transactions_amount", "organization_id", "amount"),
    )

    id: Mapped[uuid_pk]
    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), nullable=False
    )
    #: Duplicat față de extras, deliberat: fiecare interogare de reconciliere
    #: filtrează pe organizație, iar un `JOIN` până la extras la fiecare rând ar fi
    #: fost prețul plătit pentru o normalizare care nu ajută nimănui.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), default=None
    )

    #: Poziția în extras, de la 1. Ordinea din fișier este ordinea în care le
    #: caută omul, iar data singură nu o păstrează: mai multe operațiuni au
    #: aceeași zi.
    position: Mapped[int] = mapped_column(nullable=False)
    #: Data operațiunii, cea după care se face contabilitatea.
    booking_date: Mapped[date] = mapped_column(nullable=False)
    #: Data valutei, când banca o declară separat. Nu se folosește la potrivire.
    value_date: Mapped[date | None] = mapped_column(default=None)

    description: Mapped[str | None] = mapped_column(Text, default=None)
    #: Suma **cu semn**: negativă la plăți, pozitivă la încasări. `direction` se
    #: derivă din ea, ca să nu existe două surse de adevăr.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    direction: Mapped[BankDirection] = mapped_column(EnumString(BankDirection, 8), nullable=False)

    counterparty_name: Mapped[str | None] = mapped_column(String(255), default=None)
    counterparty_iban: Mapped[str | None] = mapped_column(String(34), default=None)
    #: Referința plății — locul în care apare, de obicei, numărul facturii.
    reference: Mapped[str | None] = mapped_column(String(255), default=None)
    #: Identificatorul dat de bancă. Când există, este cea mai bună apărare
    #: împotriva unui import repetat.
    external_id: Mapped[str | None] = mapped_column(String(128), default=None)

    status: Mapped[BankTransactionStatus] = mapped_column(
        EnumString(BankTransactionStatus, 16),
        default=BankTransactionStatus.UNMATCHED,
        nullable=False,
    )
    #: De ce a fost lăsată în afara reconcilierii, când a fost. Text scris de om.
    note: Mapped[str | None] = mapped_column(String(512), default=None)

    statement: Mapped[BankStatement] = relationship(back_populates="transactions")
    matches: Mapped[list[TransactionMatch]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionMatch.created_at",
    )

    def __repr__(self) -> str:
        return f"<BankTransaction {self.booking_date} {self.amount} {self.status}>"


class TransactionMatch(Base, TimestampMixin):
    """Legătura dintre o tranzacție și un document, cu suma care le leagă.

    **De ce are sumă.** Pentru că o plată nu închide întotdeauna exact o factură.
    `amount` spune cât din tranzacția asta a mers pe documentul acela — restul
    poate merge pe altul, sau poate rămâne neacoperit.

    **De ce are motiv.** Cine se uită peste o lună la o potrivire propusă de
    sistem trebuie să poată afla **de ce** a fost propusă: „CUI identic, număr de
    factură în referință, sumă exactă". Fără explicație, contabilul fie verifică
    tot de la zero — și atunci automatizarea n-a economisit nimic — fie o acceptă
    fără să verifice, ceea ce este mai rău.
    """

    __tablename__ = "transaction_matches"
    __table_args__ = (
        # Aceeași pereche o singură dată. O plată parțială a doua oară pe aceeași
        # factură se scrie ca sumă mai mare pe legătura existentă, nu ca rând nou.
        UniqueConstraint("transaction_id", "document_id", name="uq_transaction_matches_pair"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_transaction_matches_document_id", "document_id"),
    )

    id: Mapped[uuid_pk]
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    #: Cât din tranzacție merge pe documentul acesta. **Pozitivă întotdeauna**:
    #: direcția o dă tranzacția, iar o sumă cu semn aici ar fi însemnat două
    #: convenții care se contrazic la primul raport.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    #: Cât de sigur a fost sistemul, `0..1`. `None` la o potrivire făcută de om:
    #: acolo nu există „cât de sigur", există „a hotărât cineva".
    confidence: Mapped[float | None] = mapped_column(default=None)
    #: De ce. Fraze scurte, în ordinea în care contează: „CUI identic",
    #: „număr factură în referință", „sumă exactă", „dată la 2 zile".
    reasons: Mapped[str | None] = mapped_column(String(512), default=None)
    #: Cine a confirmat. `None` cât timp potrivirea este doar propusă.
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)

    transaction: Mapped[BankTransaction] = relationship(back_populates="matches")

    def __repr__(self) -> str:
        return f"<TransactionMatch {self.transaction_id}->{self.document_id} {self.amount}>"
