"""Reconcilierea: ce factură a plătit fiecare rând din extras (§13, §14, §15).

Regulile de potrivire stau în `app/domain/bank_matching.py`, care este pur și se
poate citi fără bază de date. Aici se face restul: se aduc candidații, se scriu
legăturile, se ține starea tranzacției la zi.

**Trei reguli care nu se negociază.**

1. **Nimic nu se leagă singur.** Sistemul propune, omul confirmă. O plată legată
   de factura greșită mută bani între conturi analitice, iar greșeala se
   descoperă la închiderea anului.
2. **Nu se poate aloca mai mult decât există.** Nici mai mult decât tranzacția,
   nici mai mult decât restul de plată al facturii. Amândouă verificările sunt
   aici, nu în interfață: un al doilea ecran, o comandă din CLI sau un import ar
   ocoli-o pe cea din browser.
3. **Starea tranzacției se recalculează, nu se setează.** După orice legătură
   adăugată sau scoasă, starea iese din sume: acoperită integral înseamnă
   `MATCHED`, parțial înseamnă `NEEDS_REVIEW`, deloc înseamnă `UNMATCHED`. O stare
   scrisă de mână s-ar fi desincronizat de sume la a treia operațiune.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain import bank_matching as matching
from app.domain.enums import BankTransactionStatus, DocumentStatus
from app.models.bank import BankTransaction, TransactionMatch
from app.models.document import Document, DocumentType
from app.models.user import User
from app.services.audit import AuditService

logger = get_logger(__name__)

#: Tipurile de document care pot fi plătite sau încasate. Un extras de cont sau o
#: chitanță nu au ce căuta printre candidați — nu se plătesc, sunt dovada plății.
PAYABLE_TYPES = ("FACTURA_INTRARE", "FACTURA_IESIRE")

#: Cât în urmă și cât înainte se caută facturi față de data plății. Fereastra este
#: puțin mai largă decât cea din potrivire, ca marginea să fie decisă de reguli,
#: nu de interogare.
SEARCH_WINDOW = timedelta(days=matching.MAX_DAYS_APART + 5)


@dataclass(frozen=True, slots=True)
class Proposal:
    """O propunere gata de afișat: documentul, cât, cât de sigur și de ce."""

    document_id: uuid.UUID
    score: float
    reasons: tuple[str, ...]
    #: Cât s-ar aloca dacă cineva apasă: minimul dintre restul tranzacției și
    #: restul facturii. Nu se propune niciodată mai mult decât încape.
    amount: Decimal
    document_number: str | None
    document_date: str | None
    partner_name: str | None
    total: Decimal | None


class ReconciliationService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id
        self.audit = AuditService(session)

    # ── Citire ──────────────────────────────────────────────────────────────

    def transaction(self, transaction_id: uuid.UUID) -> BankTransaction:
        found = self.session.scalars(
            select(BankTransaction).where(
                BankTransaction.id == transaction_id,
                BankTransaction.organization_id == self.organization_id,
            )
        ).first()
        if found is None:
            # `404`, nu `403`: un „nu ai voie" ar confirma că id-ul există undeva.
            raise NotFoundError("Tranzacție", transaction_id)
        return found

    def allocated(self, transaction: BankTransaction) -> Decimal:
        """Cât din tranzacție este deja pus pe facturi."""
        return sum((item.amount for item in transaction.matches), Decimal("0"))

    def unallocated(self, transaction: BankTransaction) -> Decimal:
        return abs(transaction.amount) - self.allocated(transaction)

    def covered(self, document_id: uuid.UUID) -> Decimal:
        """Cât s-a plătit deja pe un document, din toate tranzacțiile."""
        rows = self.session.scalars(
            select(TransactionMatch.amount).where(TransactionMatch.document_id == document_id)
        ).all()
        return sum(rows, Decimal("0"))

    def propose(self, transaction: BankTransaction, *, limit: int = 5) -> list[Proposal]:
        """Ce facturi ar putea fi. Nu leagă nimic.

        Candidații se restrâng în interogare — client, direcție, fereastră de
        dată — iar regulile decid dintre ei. Fără restrângere, o lună cu două mii
        de documente ar fi trecut de fiecare dată prin toate.
        """
        movement = matching.Movement(
            amount=transaction.amount,
            booking_date=transaction.booking_date,
            description=transaction.description,
            counterparty_name=transaction.counterparty_name,
            counterparty_iban=transaction.counterparty_iban,
            reference=transaction.reference,
        )

        documents = self._candidates(transaction)
        covered = self._covered_map([document.id for document in documents])

        candidates = [
            matching.Candidate(
                document_id=str(document.id),
                total=document.total_amount,
                document_date=document.document_date,
                series=document.series,
                number=document.document_number,
                partner_name=(
                    document.supplier_name if _is_incoming(document) else document.customer_name
                ),
                partner_tax_id=(
                    document.supplier_tax_id if _is_incoming(document) else document.customer_tax_id
                ),
                is_incoming=_is_incoming(document),
                already_matched=covered.get(document.id, Decimal("0")),
            )
            for document in documents
        ]

        by_id = {str(document.id): document for document in documents}
        remaining = self.unallocated(transaction)

        found: list[Proposal] = []
        for suggestion in matching.suggest(movement, candidates, limit=limit):
            document = by_id[suggestion.document_id]
            open_amount = (document.total_amount or Decimal("0")) - covered.get(
                document.id, Decimal("0")
            )
            offered = min(remaining, open_amount) if open_amount > 0 else remaining
            found.append(
                Proposal(
                    document_id=document.id,
                    score=suggestion.score,
                    reasons=suggestion.reasons,
                    amount=max(offered, Decimal("0")),
                    document_number=document.document_number,
                    document_date=(
                        document.document_date.isoformat() if document.document_date else None
                    ),
                    partner_name=(
                        document.supplier_name if _is_incoming(document) else document.customer_name
                    ),
                    total=document.total_amount,
                )
            )
        return found

    # ── Scriere ─────────────────────────────────────────────────────────────

    def match(
        self,
        transaction_id: uuid.UUID,
        document_id: uuid.UUID,
        amount: Decimal | None,
        *,
        actor: User,
        confidence: float | None = None,
        reasons: str | None = None,
        ip: str | None = None,
    ) -> BankTransaction:
        """Leagă o tranzacție de un document, pe o sumă.

        `amount` gol înseamnă „cât încape": minimul dintre restul tranzacției și
        restul facturii. Este ce vrea omul în nouă cazuri din zece, iar cifra
        rămâne vizibilă pe ecran înainte de apăsare.
        """
        transaction = self.transaction(transaction_id)
        document = self._document(document_id)

        remaining = self.unallocated(transaction)
        if remaining <= 0:
            raise ValidationError(
                "Tranzacția este deja alocată integral.",
                {"amount": ["Scoate o legătură existentă întâi."]},
            )

        open_amount = (document.total_amount or Decimal("0")) - self.covered(document_id)
        wanted = amount if amount is not None else min(remaining, open_amount or remaining)

        if wanted <= 0:
            raise ValidationError(
                "Suma trebuie să fie pozitivă.", {"amount": ["Alege o sumă mai mare ca zero."]}
            )
        if wanted > remaining:
            raise ValidationError(
                "Suma depășește ce a mai rămas din tranzacție.",
                {"amount": [f"Maximum {remaining}."]},
            )
        if document.total_amount is not None and wanted > open_amount:
            raise ValidationError(
                "Suma depășește restul de plată al facturii.",
                {"amount": [f"Maximum {open_amount}."]},
            )

        existing = next(
            (item for item in transaction.matches if item.document_id == document_id), None
        )
        if existing is not None:
            # A doua alocare pe aceeași factură crește legătura, nu adaugă un rând:
            # două rânduri pe aceeași pereche ar fi făcut ca „cât s-a plătit" să
            # depindă de câte ori a apăsat cineva.
            existing.amount += wanted
            existing.confirmed_by_id = actor.id
            existing.confirmed_at = clock_now()
        else:
            transaction.matches.append(
                TransactionMatch(
                    transaction_id=transaction.id,
                    document_id=document_id,
                    amount=wanted,
                    confidence=confidence,
                    reasons=reasons,
                    confirmed_by_id=actor.id,
                    confirmed_at=clock_now(),
                )
            )

        self.session.flush()
        self._refresh_status(transaction)
        self.audit.record(
            organization_id=self.organization_id,
            action="BANK_TRANSACTION_MATCHED",
            entity_type="BankTransaction",
            entity_id=str(transaction.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail=f"{wanted} pe documentul {document.document_number or document.id}",
            ip=ip,
        )
        logger.info(
            "bank_match",
            transaction_id=str(transaction.id),
            document_id=str(document_id),
            amount=str(wanted),
        )
        return transaction

    def unmatch(
        self,
        transaction_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        actor: User,
        ip: str | None = None,
    ) -> BankTransaction:
        """Scoate o legătură. Reconcilierea trebuie să fie reversibilă.

        Fără asta, o singură apăsare greșită ar fi cerut o intervenție în bază —
        iar contabilul care știe asta nu mai apasă deloc.
        """
        transaction = self.transaction(transaction_id)
        found = next(
            (item for item in transaction.matches if item.document_id == document_id), None
        )
        if found is None:
            raise NotFoundError("Legătură", document_id)

        transaction.matches.remove(found)
        self.session.flush()
        self._refresh_status(transaction)
        self.audit.record(
            organization_id=self.organization_id,
            action="BANK_TRANSACTION_UNMATCHED",
            entity_type="BankTransaction",
            entity_id=str(transaction.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail=f"Legătură scoasă de pe documentul {document_id}",
            ip=ip,
        )
        return transaction

    def ignore(
        self, transaction_id: uuid.UUID, note: str | None, *, actor: User, ip: str | None = None
    ) -> BankTransaction:
        """Scoate rândul din lista de lucru, cu un motiv scris.

        Un comision bancar de trei lei nu este „nepotrivit", este **lămurit**.
        Fără starea asta, lista de nepotrivite nu s-ar mai goli niciodată, iar o
        listă care nu se golește nu se mai deschide.
        """
        transaction = self.transaction(transaction_id)
        if transaction.matches:
            raise ValidationError(
                "Tranzacția are legături. Scoate-le înainte să o marchezi lămurită.",
                {"transactionId": ["Are documente atașate."]},
            )
        transaction.status = BankTransactionStatus.IGNORED
        transaction.note = (note or "").strip()[:512] or None
        self.session.flush()
        self.audit.record(
            organization_id=self.organization_id,
            action="BANK_TRANSACTION_IGNORED",
            entity_type="BankTransaction",
            entity_id=str(transaction.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail=transaction.note or "fără motiv scris",
            ip=ip,
        )
        return transaction

    def reopen(
        self, transaction_id: uuid.UUID, *, actor: User, ip: str | None = None
    ) -> BankTransaction:
        """Readuce în lista de lucru un rând marcat lămurit din greșeală."""
        transaction = self.transaction(transaction_id)
        transaction.note = None
        self._refresh_status(transaction)
        self.audit.record(
            organization_id=self.organization_id,
            action="BANK_TRANSACTION_REOPENED",
            entity_type="BankTransaction",
            entity_id=str(transaction.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail="Readusă în lista de lucru",
            ip=ip,
        )
        return transaction

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _refresh_status(self, transaction: BankTransaction) -> None:
        """Starea iese din sume, nu se scrie de mână.

        O stare setată explicit s-ar fi desincronizat de legături la a treia
        operațiune, iar atunci lista de lucru ar fi mințit în amândouă direcțiile.
        """
        allocated = self.allocated(transaction)
        total = abs(transaction.amount)
        if allocated <= 0:
            transaction.status = BankTransactionStatus.UNMATCHED
        elif allocated == total:
            transaction.status = BankTransactionStatus.MATCHED
        else:
            # Parțial: nu este nici gata, nici de la capăt. Cere un om.
            transaction.status = BankTransactionStatus.NEEDS_REVIEW

    def _document(self, document_id: uuid.UUID) -> Document:
        found = self.session.scalars(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == self.organization_id,
                Document.deleted_at.is_(None),
            )
        ).first()
        if found is None:
            raise NotFoundError("Document", document_id)
        return found

    def _candidates(self, transaction: BankTransaction) -> list[Document]:
        """Facturile care ar putea fi plata asta, restrânse în interogare."""
        window_start = transaction.booking_date - SEARCH_WINDOW
        window_end = transaction.booking_date + SEARCH_WINDOW

        stmt = (
            select(Document)
            .join(DocumentType, Document.document_type_id == DocumentType.id)
            .where(
                Document.organization_id == self.organization_id,
                Document.deleted_at.is_(None),
                Document.status.notin_(
                    (DocumentStatus.REJECTED, DocumentStatus.DUPLICATE, DocumentStatus.ERROR)
                ),
                DocumentType.code.in_(PAYABLE_TYPES),
                Document.document_date.is_not(None),
                Document.document_date >= window_start,
                Document.document_date <= window_end,
            )
        )
        if transaction.client_id is not None:
            # Extrasul este al unui client anume: facturile altora nu au ce căuta
            # printre candidați, oricât de bine s-ar potrivi suma.
            stmt = stmt.where(Document.client_id == transaction.client_id)

        return list(self.session.scalars(stmt))

    def _covered_map(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """Cât s-a plătit pe fiecare document, într-o singură interogare.

        Cerut per candidat, un ecran cu cincizeci de tranzacții ar fi făcut
        cincizeci de interogări în plus, fiecare pentru un singur număr.
        """
        if not document_ids:
            return {}
        rows = self.session.execute(
            select(TransactionMatch.document_id, TransactionMatch.amount).where(
                TransactionMatch.document_id.in_(document_ids)
            )
        ).all()
        totals: dict[uuid.UUID, Decimal] = {}
        for document_id, amount in rows:
            totals[document_id] = totals.get(document_id, Decimal("0")) + amount
        return totals


def _is_incoming(document: Document) -> bool:
    """Factură de la furnizor (bani ieșiți) sau emisă de client (bani intrați)."""
    return bool(document.document_type and document.document_type.code == "FACTURA_INTRARE")


__all__ = ["PAYABLE_TYPES", "Proposal", "ReconciliationService"]
