"""Acces la date pentru documente.

Ca la clienți: filtrarea pe `organization_id` și excluderea rândurilor șterse
trăiesc aici, nu în endpoint (R10, §72). O rută care uită `WHERE` scurge documente
între organizații; un repository care le pune din construcție nu poate.

Lista este deliberat ușoară (§64): `ocr_text` nu se selectează niciodată aici, iar
numele clientului vine dintr-un JOIN, nu dintr-un SELECT per rând (§65).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session, joinedload, lazyload

from app.domain.enums import DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType, DocumentVersion
from app.schemas.common import PageParams
from app.schemas.document import SORTABLE_FIELDS, DocumentFilters

# Coloanele în care caută bara de căutare. `client_name` vine din tabela alăturată.
_SEARCHABLE_COLUMNS = ("original_filename", "stored_filename", "supplier_name", "document_number")


def _normalised(column: Any) -> ColumnElement[str]:
    """Forma în care se compară textul: fără diacritice, litere mici.

    Refolosește `app_unaccent` — funcția IMMUTABLE introdusă de migrarea CRM. Nu
    există un al doilea mecanism de căutare în proiect (§63).
    """
    return func.app_unaccent(func.lower(func.coalesce(column, "")))


def escape_like(value: str) -> str:
    """Neutralizează metacaracterele LIKE din textul căutat (§63).

    Fără asta, cine scrie `%` primește toate documentele. Nu e o problemă de
    injecție — interogarea rămâne parametrizată — ci de corectitudine.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True)
class DocumentRow:
    """Un document plus numele pe care le afișează lista, aduse în același SELECT."""

    document: Document
    client_name: str | None


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Interogări de bază ──────────────────────────────────────────────────

    def _base(self, organization_id: uuid.UUID) -> Select[tuple[Document]]:
        return select(Document).where(
            Document.organization_id == organization_id,
            Document.deleted_at.is_(None),
        )

    def _apply_filters(self, stmt: Select[Any], filters: DocumentFilters) -> Select[Any]:
        if filters.client_id is not None:
            stmt = stmt.where(Document.client_id == filters.client_id)
        if filters.status:
            stmt = stmt.where(Document.status.in_(filters.status))
        if filters.source is not None:
            stmt = stmt.where(Document.source == filters.source)
        if filters.document_type is not None:
            stmt = stmt.where(DocumentType.code == filters.document_type)
        if filters.reference_month is not None:
            stmt = stmt.where(Document.reference_month == filters.reference_month)
        if filters.year is not None:
            stmt = stmt.where(Document.reference_month.startswith(f"{filters.year}-"))
        if filters.date_from is not None:
            stmt = stmt.where(Document.document_date >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Document.document_date <= filters.date_to)
        if filters.review_required is not None:
            stmt = stmt.where(Document.review_required.is_(filters.review_required))
        if filters.is_duplicate is not None:
            stmt = stmt.where(Document.is_duplicate.is_(filters.is_duplicate))
        if filters.min_confidence is not None:
            stmt = stmt.where(Document.ai_extraction_confidence >= filters.min_confidence)
        if filters.max_confidence is not None:
            stmt = stmt.where(Document.ai_extraction_confidence <= filters.max_confidence)

        if filters.q:
            needle = func.concat("%", func.app_unaccent(func.lower(escape_like(filters.q))), "%")
            conditions = [
                _normalised(getattr(Document, column)).like(needle, escape="\\")
                for column in _SEARCHABLE_COLUMNS
            ]
            # Numele clientului este căutabil deși stă în altă tabelă.
            conditions.append(_normalised(Client.name).like(needle, escape="\\"))
            stmt = stmt.where(or_(*conditions))

        return stmt

    def list(
        self, organization_id: uuid.UUID, filters: DocumentFilters, page: PageParams
    ) -> tuple[list[DocumentRow], int]:
        # LEFT JOIN: un document poate să nu aibă încă nici client, nici tip.
        stmt = (
            select(Document, Client.name)
            .outerjoin(Client, Document.client_id == Client.id)
            .outerjoin(DocumentType, Document.document_type_id == DocumentType.id)
            .where(
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
            )
        )
        stmt = self._apply_filters(stmt, filters)

        total = self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )

        column = getattr(Document, SORTABLE_FIELDS[filters.sort])
        ordering = column.asc() if filters.order == "asc" else column.desc()
        rows = self.session.execute(
            stmt.options(joinedload(Document.document_type))
            # Ordonare stabilă: fără al doilea criteriu, două documente cu aceeași
            # valoare pot sări între pagini.
            .order_by(ordering.nullslast(), Document.id)
            .offset(page.offset)
            .limit(page.page_size)
        ).unique()

        return [DocumentRow(document=row[0], client_name=row[1]) for row in rows], total or 0

    def get(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRow | None:
        """Un document din altă organizație nu se distinge de unul inexistent (§72)."""
        stmt = (
            select(Document, Client.name)
            .outerjoin(Client, Document.client_id == Client.id)
            .where(
                Document.id == document_id,
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
            )
            .options(joinedload(Document.document_type))
        )
        row = self.session.execute(stmt).unique().first()
        return None if row is None else DocumentRow(document=row[0], client_name=row[1])

    def get_for_update(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        """Blochează rândul până la finalul tranzacției (§43).

        Două worker-e care iau același document nu trebuie să-l arhiveze de două ori.
        """
        return self.session.scalars(
            self._base(organization_id)
            .where(Document.id == document_id)
            # `document_type` este `lazy="joined"`, iar Postgres refuza FOR UPDATE pe
            # partea nullable a unui outer join. Pentru blocarea randului nu avem
            # nevoie de relatie; se incarca lene daca o cere cineva.
            .options(lazyload(Document.document_type))
            .with_for_update()
        ).first()

    # ── Duplicate ───────────────────────────────────────────────────────────

    def find_by_hash(
        self,
        organization_id: uuid.UUID,
        sha256_hash: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> Document | None:
        """Primul document cu același conținut (§12).

        Căutarea este limitată la organizație: două cabinete pot avea, legitim,
        același document.
        """
        stmt = self._base(organization_id).where(Document.sha256_hash == sha256_hash)
        if exclude_id is not None:
            stmt = stmt.where(Document.id != exclude_id)
        return self.session.scalars(stmt.order_by(Document.received_at)).first()

    # ── Tipuri de document ──────────────────────────────────────────────────

    def list_types(
        self, organization_id: uuid.UUID, *, active_only: bool = True
    ) -> Sequence[DocumentType]:
        stmt = select(DocumentType).where(DocumentType.organization_id == organization_id)
        if active_only:
            stmt = stmt.where(DocumentType.is_active.is_(True))
        return list(self.session.scalars(stmt.order_by(DocumentType.sort_order, DocumentType.code)))

    def get_type_by_code(self, organization_id: uuid.UUID, code: str) -> DocumentType | None:
        return self.session.scalars(
            select(DocumentType).where(
                DocumentType.organization_id == organization_id,
                DocumentType.code == code,
            )
        ).first()

    # ── Versiuni ────────────────────────────────────────────────────────────

    def next_version_number(self, document_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document_id
            )
        )
        return (current or 0) + 1

    def versions(self, document_id: uuid.UUID) -> Sequence[DocumentVersion]:
        return list(
            self.session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_number)
            )
        )

    # ── Agregări ────────────────────────────────────────────────────────────

    def count_by_status(self, organization_id: uuid.UUID) -> dict[DocumentStatus, int]:
        rows = self.session.execute(
            select(Document.status, func.count())
            .where(Document.organization_id == organization_id, Document.deleted_at.is_(None))
            .group_by(Document.status)
        ).all()
        return {DocumentStatus(row[0]): row[1] for row in rows}

    def soft_delete(self, document: Document, when: datetime) -> None:
        """Documentele nu se șterg fizic (§62, R8): rămân auditabile."""
        document.deleted_at = when
