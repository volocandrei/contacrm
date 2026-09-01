"""Operațiile de business pe un document (§19, §33, §40).

Fiecare schimbare de stare trece prin `assert_transition`, nu prin atribuire
directă: regulile ciclului de viață trăiesc într-un singur loc, iar workerul — care
nu trece prin HTTP — le respectă la fel.

Fiecare operație scrie în audit, cu `old_value` și `new_value` acolo unde există o
valoare anterioară (§33).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.domain.document_state import (
    InvalidTransitionError,
    assert_transition,
    can_transition,
)
from app.domain.enums import DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.services.audit import AuditService
from app.services.document_fields import (
    DocumentFieldWriter,
    FieldUpdate,
    missing_required_fields,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Cine face acțiunea și de unde — pentru audit."""

    user: User
    ip: str | None = None
    user_agent: str | None = None


def approval_blockers(document: Document) -> list[str]:
    """Ce mai lipsește ca documentul să poată fi aprobat.

    Aceeași funcție hrănește și verificarea din `approve()`, și câmpul
    `approvalBlockers` din detaliu — ecranul de verificare nu recalculează nimic
    și nu poate ajunge să spună altceva decât serverul.
    """
    problems: list[str] = []
    if document.client_id is None:
        problems.append("Documentul nu are client atribuit.")
    missing = missing_required_fields(document)
    if missing:
        problems.append("Câmpuri obligatorii lipsă: " + ", ".join(missing))
    return problems


class DocumentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.documents = DocumentRepository(session)
        self.audit = AuditService(session)
        self.fields = DocumentFieldWriter(session)

    # ── Ajutătoare ──────────────────────────────────────────────────────────

    def _get(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        """Blochează rândul: două cereri simultane nu trebuie să-l aprobe de două ori (§43)."""
        document = self.documents.get_for_update(organization_id, document_id)
        if document is None:
            # Un document din altă organizație e indistinct de unul inexistent (§72).
            raise NotFoundError("Document", document_id)
        return document

    def _types(self, organization_id: uuid.UUID) -> dict[str, DocumentType]:
        return {t.code: t for t in self.documents.list_types(organization_id)}

    def _record(
        self,
        actor: ActorContext,
        document: Document,
        action: str,
        *,
        detail: str | None = None,
        old_value: dict[str, object] | None = None,
        new_value: dict[str, object] | None = None,
    ) -> None:
        self.audit.record(
            organization_id=document.organization_id,
            action=action,
            entity_type="Document",
            entity_id=str(document.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            detail=detail,
            old_value=old_value,
            new_value=new_value,
            ip=actor.ip,
            user_agent=actor.user_agent,
        )

    def _transition(
        self, document: Document, target: DocumentStatus, *, explicit: bool = False
    ) -> None:
        try:
            assert_transition(document.status, target, explicit_reprocess=explicit)
        except InvalidTransitionError as exc:
            raise ConflictError(str(exc)) from exc
        document.status = target

    # ── Modificarea metadatelor ─────────────────────────────────────────────

    def update_fields(
        self,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        updates: list[FieldUpdate],
        actor: ActorContext,
    ) -> Document:
        document = self._get(organization_id, document_id)
        changes = self.fields.apply(
            document,
            updates,
            changed_by=actor.user.id,
            document_types=self._types(organization_id),
        )
        if not changes:
            return document

        self._mark_reviewed(document, actor)
        self._record(
            actor,
            document,
            "DOCUMENT_METADATA_UPDATED",
            detail=", ".join(change.field for change in changes),
            old_value={c.field: c.old_value for c in changes},
            new_value={c.field: c.new_value for c in changes},
        )
        # Corectarea manuală rezolvă problemele semnalate de extracție.
        document.validation_issues = missing_required_fields(document)
        self.session.flush()
        logger.info(
            "document_fields_updated",
            document_id=str(document.id),
            fields=[c.field for c in changes],
        )
        return document

    def _mark_reviewed(self, document: Document, actor: ActorContext) -> None:
        document.reviewed_by = actor.user.id
        document.reviewed_at = datetime.now(UTC)

    # ── Atribuirea clientului ───────────────────────────────────────────────

    def assign_client(
        self,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        client_id: uuid.UUID,
        actor: ActorContext,
    ) -> Document:
        document = self._get(organization_id, document_id)
        client = self.session.get(Client, client_id)
        if client is None or client.organization_id != organization_id or client.deleted_at:
            raise NotFoundError("Client", client_id)

        previous = document.client_id
        document.client_id = client.id

        # Documentul nu mai este neatribuit, deci poate merge la verificare.
        if document.status is DocumentStatus.UNMATCHED:
            self._transition(document, DocumentStatus.REVIEW_REQUIRED)
            document.review_required = True

        self._record(
            actor,
            document,
            "DOCUMENT_CLIENT_ASSIGNED",
            detail=client.name,
            old_value={"clientId": str(previous) if previous else None},
            new_value={"clientId": str(client.id)},
        )
        self.session.flush()
        return document

    # ── Aprobare ────────────────────────────────────────────────────────────

    def approve(
        self, organization_id: uuid.UUID, document_id: uuid.UUID, actor: ActorContext
    ) -> Document:
        """Aprobă documentul. Arhivarea fizică vine separat, la M5.7."""
        document = self._get(organization_id, document_id)

        # Starea se verifica prima: un document neprocesat nu poate fi aprobat
        # indiferent cat de complete ii sunt campurile.
        check = can_transition(document.status, DocumentStatus.APPROVED)
        if not check.allowed:
            raise ConflictError(
                f"Documentul nu poate fi aprobat din starea {document.status.value}."
            )

        problems = approval_blockers(document)
        if problems:
            raise ValidationError("Documentul nu poate fi aprobat.", {"document": problems})

        self._transition(document, DocumentStatus.APPROVED)
        document.review_required = False
        document.validation_issues = []
        document.approved_by = actor.user.id
        document.approved_at = datetime.now(UTC)
        self._mark_reviewed(document, actor)

        self._record(actor, document, "DOCUMENT_APPROVED", detail=document.original_filename)
        self.session.flush()
        logger.info("document_approved", document_id=str(document.id))
        return document

    # ── Respingere ──────────────────────────────────────────────────────────

    def reject(
        self,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        reason: str,
        actor: ActorContext,
    ) -> Document:
        cleaned = reason.strip()
        if not cleaned:
            # Un document respins fără motiv nu poate fi corectat de nimeni.
            raise ValidationError(
                "Motivul respingerii este obligatoriu.", {"reason": ["Câmp obligatoriu."]}
            )

        document = self._get(organization_id, document_id)
        self._transition(document, DocumentStatus.REJECTED)
        document.review_required = False
        document.rejected_reason = cleaned[:512]
        self._mark_reviewed(document, actor)

        self._record(actor, document, "DOCUMENT_REJECTED", detail=cleaned[:255])
        self.session.flush()
        return document

    # ── Cererea de reprocesare ──────────────────────────────────────────────

    def begin_reprocessing(
        self, organization_id: uuid.UUID, document_id: uuid.UUID, actor: ActorContext
    ) -> Document:
        """Acceptă cererea și mută documentul în `PROCESSING`.

        Starea se schimbă aici, nu abia când workerul apucă să pornească. Altfel
        răspunsul ar spune „am acceptat" și ar returna un document care arată
        neatins — iar ecranul de verificare, care se ține după status, nu ar avea
        de unde ști că mai are ce aștepta.

        Tranziția este cea explicită: numai o cerere ca asta scoate un document din
        arhivă (§40).
        """
        document = self._get(organization_id, document_id)
        self._transition(document, DocumentStatus.PROCESSING, explicit=True)
        self._record(
            actor,
            document,
            "DOCUMENT_REPROCESS_REQUESTED",
            detail=f"încercarea {document.processing_attempts + 1}",
        )
        self.session.flush()
        return document

    # ── Marcare duplicat ────────────────────────────────────────────────────

    def mark_duplicate(
        self,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        duplicate_of_id: uuid.UUID | None,
        actor: ActorContext,
    ) -> Document:
        document = self._get(organization_id, document_id)

        original_id = duplicate_of_id
        if original_id is None:
            # Fără un original indicat, îl căutăm după conținut.
            found = self.documents.find_by_hash(
                organization_id, document.sha256_hash, exclude_id=document.id
            )
            if found is None:
                raise ValidationError(
                    "Nu există un document original identificat.",
                    {"duplicateOfId": ["Indică documentul original."]},
                )
            original_id = found.id
        elif original_id == document.id:
            raise ValidationError(
                "Un document nu poate fi propriul duplicat.",
                {"duplicateOfId": ["Valoare invalidă."]},
            )
        else:
            original = self.documents.get(organization_id, original_id)
            if original is None:
                raise NotFoundError("Document", original_id)

        self._transition(document, DocumentStatus.DUPLICATE)
        document.is_duplicate = True
        document.duplicate_of_id = original_id
        document.review_required = False

        self._record(
            actor,
            document,
            "DOCUMENT_MARKED_DUPLICATE",
            detail=str(original_id),
            new_value={"duplicateOfId": str(original_id)},
        )
        self.session.flush()
        return document
