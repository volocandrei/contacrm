"""Legarea XML-ului de PDF-ul aceleiași facturi (§16, §17, §27).

Regulile stau în `app/domain/efactura_pairing.py`, care este pur. Aici se aduc
candidații din bază, se scrie legătura și se lasă urmă în jurnal.

**Când se leagă singur, și când nu.** Pe identitatea legală completă — CUI
furnizor, serie, număr, plus aceeași sumă — legătura se face automat: nu este o
ghicire, este aceeași factură după cheia care o definește. Orice lipsă coboară la
„probabil", iar acolo apasă un om. Un conflict de sume nu se leagă niciodată: el
**este** informația.

**Legătura este reciprocă.** Amândouă rândurile arată unul spre celălalt, ca
oricare dintre ele să răspundă la „unde este celălalt exemplar" fără o a doua
interogare.

**Se cheamă la sfârșitul procesării**, după ce documentul și-a citit datele: mai
devreme nu are cu ce se compara. Se cheamă și pentru XML, și pentru PDF, fiindcă
ordinea în care sosesc nu se poate alege — de obicei XML-ul vine primul, din SPV,
dar nu întotdeauna.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain import efactura_pairing as pairing
from app.domain.enums import DocumentSource, DocumentStatus
from app.models.document import Document
from app.models.user import User
from app.services.audit import AuditService

logger = get_logger(__name__)

#: Cât în urmă și cât înainte se caută perechea. Fereastra este mai largă decât
#: cea din reguli, ca marginea să fie hotărâtă de reguli, nu de interogare.
SEARCH_WINDOW = timedelta(days=pairing.MAX_DAYS_APART + 30)


def is_electronic(document: Document) -> bool:
    """Documentul este factura electronică, nu exemplarul clasic.

    Se citește din **conținut**, nu din sursă: un XML urcat de mână de contabil
    este tot o factură electronică, iar unul venit prin email la fel. Sursa spune
    de unde l-am luat, nu ce este.
    """
    return document.mime_type in {"application/xml", "text/xml"} or (
        document.source is DocumentSource.EFACTURA
    )


class PairingService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id
        self.audit = AuditService(session)

    # ── Citire ──────────────────────────────────────────────────────────────

    def evaluate(self, document: Document) -> pairing.Result:
        """Ce pereche are documentul, printre cele din bază. Nu scrie nimic."""
        subject = self._identity(document)
        if subject.number is None:
            # Fără numărul facturii nu există cheie. Un document necitit încă nu
            # are ce să caute, iar o potrivire fără număr ar fi o coincidență.
            return pairing.Result(state=pairing.PairingState.MISSING, candidates=())

        candidates = [self._identity(other) for other in self._candidates(document)]
        return pairing.evaluate(subject, candidates)

    def document(self, document_id: uuid.UUID) -> Document:
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

    # ── Scriere ─────────────────────────────────────────────────────────────

    def pair_automatically(self, document: Document) -> Document | None:
        """Leagă, dacă nu rămâne nimic de hotărât. Întoarce perechea sau `None`.

        Se cheamă din procesare. Nu ridică niciodată: o pereche negăsită este
        cazul obișnuit, nu un eșec al procesării.
        """
        if document.paired_with_id is not None:
            return None

        result = self.evaluate(document)
        certain = result.certain
        if certain is None:
            return None

        other = self.session.get(Document, uuid.UUID(certain.document_id))
        if other is None or other.paired_with_id is not None:
            return None

        self._link(document, other, reasons=certain.reasons, automatic=True)
        logger.info(
            "efactura_paired",
            document_id=str(document.id),
            paired_with=str(other.id),
            reasons=", ".join(certain.reasons),
        )
        return other

    def pair(
        self, document_id: uuid.UUID, other_id: uuid.UUID, *, actor: User, ip: str | None = None
    ) -> Document:
        """Legarea cerută de un om, dintre candidații propuși."""
        document = self.document(document_id)
        other = self.document(other_id)

        if document.id == other.id:
            raise ValidationError(
                "Un document nu se poate lega de el însuși.", {"documentId": ["Același id."]}
            )
        if is_electronic(document) == is_electronic(other):
            raise ValidationError(
                "Se leagă doar exemplare de feluri diferite: XML-ul cu PDF-ul.",
                {"documentId": ["Amândouă sunt de același fel — este un duplicat, nu o pereche."]},
            )
        for side in (document, other):
            if side.paired_with_id is not None and side.paired_with_id != (
                other.id if side is document else document.id
            ):
                raise ValidationError(
                    "Unul dintre documente este deja legat de altul.",
                    {"documentId": ["Desfă legătura existentă întâi."]},
                )

        found = pairing.compare(self._identity(document), self._identity(other))
        reasons = found.reasons if found else ("legat manual",)
        self._link(document, other, reasons=reasons, automatic=False)

        self.audit.record(
            organization_id=self.organization_id,
            action="DOCUMENT_PAIRED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail=f"Legat cu {other.id}: {', '.join(reasons)}",
            ip=ip,
        )
        return document

    def unpair(self, document_id: uuid.UUID, *, actor: User, ip: str | None = None) -> Document:
        """Rupe legătura. Reversibil, ca orice hotărâre luată pe o propunere."""
        document = self.document(document_id)
        if document.paired_with_id is None:
            raise ValidationError(
                "Documentul nu este legat de niciun altul.", {"documentId": ["Nicio pereche."]}
            )

        other = self.session.get(Document, document.paired_with_id)
        if other is not None:
            other.paired_with_id = None
            other.pairing_reasons = None
            other.paired_automatically = None
        document.paired_with_id = None
        document.pairing_reasons = None
        document.paired_automatically = None
        self.session.flush()

        self.audit.record(
            organization_id=self.organization_id,
            action="DOCUMENT_UNPAIRED",
            entity_type="Document",
            entity_id=str(document.id),
            user_id=actor.id,
            user_name=actor.full_name,
            detail="Legătură ruptă",
            ip=ip,
        )
        return document

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _link(
        self, left: Document, right: Document, *, reasons: tuple[str, ...], automatic: bool
    ) -> None:
        """Legătura, în amândouă direcțiile."""
        text = ", ".join(reasons)[:512]
        for document, other in ((left, right), (right, left)):
            document.paired_with_id = other.id
            document.pairing_reasons = text
            document.paired_automatically = automatic
        self.session.flush()

    @staticmethod
    def _identity(document: Document) -> pairing.Identity:
        return pairing.Identity(
            document_id=str(document.id),
            is_electronic=is_electronic(document),
            supplier_tax_id=document.supplier_tax_id,
            series=document.series,
            number=document.document_number,
            total=document.total_amount,
            document_date=document.document_date,
        )

    def _candidates(self, document: Document) -> list[Document]:
        """Documentele care ar putea fi celălalt exemplar, restrânse în interogare.

        Se caută după **numărul facturii**, care este cheia, plus o fereastră de
        dată. Fără restrângere, fiecare document procesat ar fi trecut prin toate
        documentele cabinetului.
        """
        stmt = select(Document).where(
            Document.organization_id == self.organization_id,
            Document.id != document.id,
            Document.deleted_at.is_(None),
            Document.document_number == document.document_number,
            Document.paired_with_id.is_(None),
            Document.status.notin_(
                (DocumentStatus.REJECTED, DocumentStatus.DUPLICATE, DocumentStatus.SPLIT)
            ),
        )
        if document.document_date is not None:
            stmt = stmt.where(
                Document.document_date >= document.document_date - SEARCH_WINDOW,
                Document.document_date <= document.document_date + SEARCH_WINDOW,
            )
        return list(self.session.scalars(stmt))


__all__ = ["SEARCH_WINDOW", "PairingService", "is_electronic"]
