"""Panoul principal și contoarele din bara laterală.

Ce răspunde M5: tot ce se poate spune despre **documente** și **clienți**.
Perioadele contabile nu există încă în backend, deci `periods` este o listă goală —
ceea ce este adevărat, nu o omisiune: sistemul chiar nu are nicio perioadă. La fel
`clientsComplete` și `clientsMissingDocs`, care se măsoară pe perioade. M6 le umple.

„Necesită atenție" este partea care contează: lista lucrurilor pe care sistemul
le-a făcut cât a putut și care acum așteaptă un om. Include documentele înțepenite
în procesare — singurul mod în care o cădere de proces devine vizibilă cuiva.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require_permission
from app.core.config import settings
from app.domain.enums import ClientStatus, DocumentStatus, TaskStatus
from app.domain.permissions import Permission
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob
from app.models.task import Task
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.schemas.common import ApiModel
from app.schemas.document import DocumentListItemOut
from app.services import processing_queue as queue

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DashboardReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]

# „Inbox" înseamnă „a intrat, sistemul încă lucrează la el".
INBOX_STATUSES = (DocumentStatus.RECEIVED, DocumentStatus.PROCESSING)

# Sub acest prag, extracția a ghicit mai mult decât a citit.
LOW_CONFIDENCE = 0.75

RECENT_DOCUMENTS = 8
MAX_ATTENTION = 8
PER_REASON = 3
TIMELINE_EVENTS = 6


class SidebarCountsOut(ApiModel):
    inbox: int
    review: int
    unmatched: int
    tasks: int


class DashboardKpisOut(ApiModel):
    clients_total: int
    clients_active: int
    # Se măsoară pe perioade contabile, care vin cu M6. Până atunci sunt zero
    # pentru că nu există nicio perioadă — nu pentru că nu le-am calculat.
    clients_complete: int
    clients_missing_docs: int
    documents_today: int
    documents_processing: int
    documents_error: int
    documents_need_review: int
    documents_duplicate: int
    documents_unmatched: int


AttentionReason = Literal[
    "UNMATCHED_CLIENT",
    "OCR_FAILED",
    "LOW_CONFIDENCE",
    "POSSIBLE_DUPLICATE",
    "MISSING_DATE",
    "STUCK_IN_PROCESSING",
    "INCOMPLETE_PERIOD",
]

TimelineKind = Literal[
    "DOCUMENTS_RECEIVED", "PROCESSED", "NEEDS_REVIEW", "NOTIFICATION_SENT", "MESSAGE"
]


class AttentionItemOut(ApiModel):
    id: str
    document_id: uuid.UUID | None
    reason: AttentionReason
    title: str
    detail: str
    occurred_at: datetime


class TimelineEventOut(ApiModel):
    id: str
    occurred_at: datetime
    kind: TimelineKind
    description: str


class DashboardOut(ApiModel):
    kpis: DashboardKpisOut
    attention: list[AttentionItemOut]
    recent_documents: list[DocumentListItemOut]
    # Gol până la M6: perioadele contabile nu există încă.
    periods: list[dict[str, object]]
    timeline: list[TimelineEventOut]


@router.get("/counts", response_model=SidebarCountsOut)
def sidebar_counts(session: DbSession, user: DashboardReader) -> SidebarCountsOut:
    by_status = DocumentRepository(session).count_by_status(user.organization_id)

    return SidebarCountsOut(
        inbox=sum(by_status.get(s, 0) for s in INBOX_STATUSES),
        review=by_status.get(DocumentStatus.REVIEW_REQUIRED, 0),
        unmatched=by_status.get(DocumentStatus.UNMATCHED, 0),
        tasks=_open_tasks(session, user.organization_id),
    )


@router.get("", response_model=DashboardOut)
def dashboard(session: DbSession, user: DashboardReader) -> DashboardOut:
    organization_id = user.organization_id
    repository = DocumentRepository(session)
    by_status = repository.count_by_status(organization_id)

    return DashboardOut(
        kpis=_kpis(session, organization_id, by_status),
        attention=_attention(session, organization_id),
        recent_documents=[
            _to_list_item(row) for row in _recent(session, organization_id, RECENT_DOCUMENTS)
        ],
        periods=[],
        timeline=_timeline(session, organization_id),
    )


# ── Indicatori ───────────────────────────────────────────────────────────────


def _open_tasks(session: Session, organization_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.organization_id == organization_id,
                Task.deleted_at.is_(None),
                Task.status != TaskStatus.DONE,
            )
        )
        or 0
    )


def _kpis(
    session: Session, organization_id: uuid.UUID, by_status: dict[DocumentStatus, int]
) -> DashboardKpisOut:
    clients_total = (
        session.scalar(
            select(func.count())
            .select_from(Client)
            .where(Client.organization_id == organization_id, Client.deleted_at.is_(None))
        )
        or 0
    )
    clients_active = (
        session.scalar(
            select(func.count())
            .select_from(Client)
            .where(
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
                Client.status == ClientStatus.ACTIVE,
            )
        )
        or 0
    )
    since = _start_of_today()
    documents_today = (
        session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
                Document.received_at >= since,
            )
        )
        or 0
    )

    return DashboardKpisOut(
        clients_total=clients_total,
        clients_active=clients_active,
        clients_complete=0,
        clients_missing_docs=0,
        documents_today=documents_today,
        documents_processing=by_status.get(DocumentStatus.PROCESSING, 0),
        documents_error=by_status.get(DocumentStatus.ERROR, 0),
        documents_need_review=by_status.get(DocumentStatus.REVIEW_REQUIRED, 0),
        documents_duplicate=by_status.get(DocumentStatus.DUPLICATE, 0),
        documents_unmatched=by_status.get(DocumentStatus.UNMATCHED, 0),
    )


def _start_of_today() -> datetime:
    """Miezul nopții de azi, în fusul configurat, exprimat în UTC.

    „Azi" nu este „ultimele 24 de ore", și nu este miezul nopții UTC: pentru un
    contabil din București ziua se termină la 00:00 local. Fusul vine din
    configurare, nu este presupus în cod (§71).
    """
    zone = ZoneInfo(settings.default_timezone)
    local_midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


# ── Necesită atenție ─────────────────────────────────────────────────────────


def _documents_where(
    session: Session, organization_id: uuid.UUID, *conditions: object, limit: int
) -> list[Document]:
    stmt = (
        select(Document)
        .where(
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
            *conditions,  # type: ignore[arg-type]
        )
        .order_by(Document.received_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def _attention(session: Session, organization_id: uuid.UUID) -> list[AttentionItemOut]:
    items: list[AttentionItemOut] = []

    def add(document: Document, reason: AttentionReason, title: str, detail: str) -> None:
        items.append(
            AttentionItemOut(
                id=f"att-{reason.lower()}-{document.id}",
                document_id=document.id,
                reason=reason,
                title=title,
                detail=detail,
                occurred_at=document.received_at,
            )
        )

    for document in _documents_where(
        session, organization_id, Document.status == DocumentStatus.UNMATCHED, limit=PER_REASON
    ):
        add(
            document,
            "UNMATCHED_CLIENT",
            "Client neidentificat",
            f"{document.original_filename} — expeditor nemapat",
        )

    for document in _documents_where(
        session, organization_id, Document.status == DocumentStatus.ERROR, limit=PER_REASON
    ):
        add(
            document,
            "OCR_FAILED",
            "Procesare eșuată",
            f"{document.original_filename} — {document.error_detail or 'motiv necunoscut'}",
        )

    for document in _documents_where(
        session,
        organization_id,
        Document.status == DocumentStatus.REVIEW_REQUIRED,
        Document.ai_extraction_confidence < LOW_CONFIDENCE,
        limit=PER_REASON,
    ):
        percent = round((document.ai_extraction_confidence or 0) * 100)
        add(
            document,
            "LOW_CONFIDENCE",
            "Încredere scăzută la extracție",
            f"{document.original_filename} · {percent}%",
        )

    for document in _documents_where(
        session, organization_id, Document.is_duplicate.is_(True), limit=2
    ):
        add(
            document,
            "POSSIBLE_DUPLICATE",
            "Posibil document duplicat",
            document.original_filename,
        )

    for document in _stuck(session, organization_id):
        add(
            document,
            "STUCK_IN_PROCESSING",
            "Procesare întreruptă",
            f"{document.original_filename} — cere `recover-processing` sau o reprocesare",
        )

    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return items[:MAX_ATTENTION]


def _stuck(session: Session, organization_id: uuid.UUID) -> list[Document]:
    """Documentele a căror procesare a rămas pe drum.

    Fără asta, o cădere de proces nu se vede nicăieri: documentul stă în
    `PROCESSING`, iar singurul care ar putea observa este cine îl caută anume.
    """
    threshold = datetime.now(UTC) - timedelta(minutes=settings.processing_stale_after_minutes)
    stmt = (
        select(Document)
        .join(DocumentProcessingJob, DocumentProcessingJob.document_id == Document.id)
        .where(
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
            DocumentProcessingJob.status.in_([queue.PENDING, queue.RUNNING]),
            DocumentProcessingJob.created_at < threshold,
        )
        .order_by(Document.received_at.desc())
        .limit(PER_REASON)
    )
    return list(session.scalars(stmt).unique().all())


# ── Documente recente și cronologie ──────────────────────────────────────────


def _recent(
    session: Session, organization_id: uuid.UUID, limit: int
) -> list[tuple[Document, str | None]]:
    stmt = (
        select(Document, Client.name)
        .outerjoin(Client, Document.client_id == Client.id)
        .where(Document.organization_id == organization_id, Document.deleted_at.is_(None))
        .order_by(Document.received_at.desc(), Document.id)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in session.execute(stmt).unique().all()]


def _to_list_item(row: tuple[Document, str | None]) -> DocumentListItemOut:
    from app.api.v1.documents import to_list_item
    from app.repositories.document import DocumentRow

    return to_list_item(DocumentRow(document=row[0], client_name=row[1]))


# Ce fel de eveniment este fiecare acțiune din audit. Ce nu apare aici este o
# mișcare obișnuită prin fluxul de lucru.
_TIMELINE_KIND: dict[str, TimelineKind] = {
    "DOCUMENT_UPLOADED": "DOCUMENTS_RECEIVED",
    "DOCUMENT_PROCESSED": "PROCESSED",
    "DOCUMENT_APPROVED": "PROCESSED",
    "DOCUMENT_ARCHIVED": "PROCESSED",
    "DOCUMENT_PROCESSING_FAILED": "NEEDS_REVIEW",
    "DOCUMENT_REPROCESS_REQUESTED": "NEEDS_REVIEW",
}


def _timeline(session: Session, organization_id: uuid.UUID) -> list[TimelineEventOut]:
    """Cronologia vine din jurnalul de audit. Nu există un al doilea jurnal (§33)."""
    entries = session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == organization_id,
            # Doar ce s-a întâmplat cu documentele. Panoul principal este despre
            # fluxul de documente; autentificările și schimbările de setări au
            # locul lor în jurnalul de audit, nu aici.
            AuditLog.entity_type == "Document",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(TIMELINE_EVENTS)
    ).all()

    return [
        TimelineEventOut(
            id=str(entry.id),
            occurred_at=entry.created_at,
            kind=_TIMELINE_KIND.get(entry.action, "MESSAGE"),
            description=(
                f"{entry.user_name}: {entry.action}"
                + (f" — {entry.detail}" if entry.detail else "")
            ),
        )
        for entry in entries
    ]
