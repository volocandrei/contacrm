"""Agregările pentru ecranul de rapoarte (§84).

**De ce în SQL și nu în interfață.** Până acum, pagina de rapoarte cerea primele
200 de documente și le număra în browser. Pe setul de development iese corect,
pentru că sunt mai puțin de 200 — dar la un cabinet real „rata de procesare
reușită" ar fi fost calculată pe o felie arbitrară și afișată ca și cum ar fi
acoperit tot. Un procent greșit care arată oficial este mai rău decât unul
absent.

Aici nu există plafon: numărătoarea se face pe toate rândurile care trec de
filtre, iar peste rețea pleacă doar rezultatul.

**Ce se numără și ce nu.** Nimic nu se ascunde. Documentele fără lună de
referință și cele fără client nu sunt sărite, ci primesc propria găleată — un
document care nu are lună contabilă este exact ce trebuie să vadă cineva, nu ce
trebuie tăcut. Acolo, `key` și `label` sunt amândouă `None`.

**Etichetele sunt doar cele pe care serverul chiar le știe** — numele clientului,
denumirea tipului de document. Cum se scrie „client neidentificat" pe ecran este
treaba interfeței, care are deja formularea; dacă am trimite-o și de aici, ar
exista două surse pentru același text și s-ar despărți la prima modificare.
Statusurile intră în aceeași regulă: `status-badge.tsx` le traduce de mult.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType

# Câți clienți intră în clasament. Restul nu dispar din total — numărul lor este
# raportat separat, ca nimeni să nu creadă că lista este completă.
TOP_CLIENTS: Final = 10

# „Procesat" înseamnă „sistemul a terminat ce avea de făcut", indiferent dacă a
# ieșit bine. Ce este încă în lucru nu are voie să intre în numitorul unei rate de
# reușită: ar coborî procentul pentru simplul fapt că cineva tocmai a încărcat un
# fișier.
IN_PROGRESS: Final = (DocumentStatus.RECEIVED, DocumentStatus.PROCESSING)


@dataclass(frozen=True, slots=True)
class Bucket:
    """O linie de clasament.

    `key` și `label` lipsesc amândouă exact când gruparea este „nimic": document
    fără client, fără tip, fără lună. Interfața decide cum numește absența.
    """

    key: str | None
    label: str | None
    count: int


@dataclass(frozen=True, slots=True)
class ReportSummary:
    total: int
    processed: int
    failed: int
    duplicates: int
    # `None` când nu s-a terminat încă nimic. Zero ar însemna „totul a eșuat",
    # ceea ce este altceva și s-ar citi greșit pe ecran.
    success_rate: float | None
    by_status: list[Bucket]
    by_month: list[Bucket]
    by_type: list[Bucket]
    by_client: list[Bucket]
    # Câți clienți distincți au documente, ca interfața să poată spune „primii 10
    # din 37" în loc să lase impresia că sunt doar zece.
    client_count: int


class ReportService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    # ── Filtre ──────────────────────────────────────────────────────────────

    def _conditions(
        self,
        *,
        from_month: str | None,
        to_month: str | None,
        client_id: uuid.UUID | None,
    ) -> list[ColumnElement[bool]]:
        """Izolarea pe organizație stă prima și nu este opțională (§72)."""
        conditions: list[ColumnElement[bool]] = [Document.organization_id == self.organization_id]
        # `YYYY-MM` se compară lexicografic exact ca cronologic — de asta este
        # stocat așa. Un document fără lună nu intră într-un interval de luni:
        # nu se poate spune că este înainte sau după.
        if from_month:
            conditions.append(Document.reference_month >= from_month)
        if to_month:
            conditions.append(Document.reference_month <= to_month)
        if client_id is not None:
            conditions.append(Document.client_id == client_id)
        return conditions

    # ── Raportul ────────────────────────────────────────────────────────────

    def summary(
        self,
        *,
        from_month: str | None = None,
        to_month: str | None = None,
        client_id: uuid.UUID | None = None,
    ) -> ReportSummary:
        conditions = self._conditions(from_month=from_month, to_month=to_month, client_id=client_id)

        status_counts = {
            DocumentStatus(status): count
            for status, count in self.session.execute(
                select(Document.status, func.count(Document.id))
                .where(*conditions)
                .group_by(Document.status)
            ).all()
        }

        total = sum(status_counts.values())
        in_progress = sum(status_counts.get(status, 0) for status in IN_PROGRESS)
        processed = total - in_progress
        failed = status_counts.get(DocumentStatus.ERROR, 0)

        duplicates = self.session.scalar(
            select(func.count(Document.id)).where(*conditions, Document.is_duplicate.is_(True))
        )

        return ReportSummary(
            total=total,
            processed=processed,
            failed=failed,
            duplicates=duplicates or 0,
            success_rate=(processed - failed) / processed if processed else None,
            by_status=sorted(
                (
                    # Fără etichetă: statusurile au deja traducere în interfață.
                    Bucket(key=status.value, label=None, count=count)
                    for status, count in status_counts.items()
                ),
                key=lambda bucket: (-bucket.count, bucket.key or ""),
            ),
            by_month=self._by_month(conditions),
            by_type=self._by_type(conditions),
            by_client=self._by_client(conditions),
            client_count=self._client_count(conditions),
        )

    def _by_month(self, conditions: list[ColumnElement[bool]]) -> list[Bucket]:
        rows = self.session.execute(
            select(Document.reference_month, func.count(Document.id))
            .where(*conditions)
            .group_by(Document.reference_month)
        ).all()
        buckets = [Bucket(key=month, label=month, count=count) for month, count in rows]
        # Cea mai recentă lună prima; documentele fără lună la coadă, unde se văd
        # fără să strice ordinea cronologică.
        dated = sorted((b for b in buckets if b.key), key=lambda b: b.key or "", reverse=True)
        undated = [b for b in buckets if b.key is None]
        return dated + undated

    def _by_type(self, conditions: list[ColumnElement[bool]]) -> list[Bucket]:
        rows = self.session.execute(
            select(DocumentType.code, DocumentType.label, func.count(Document.id))
            .select_from(Document)
            .outerjoin(DocumentType, Document.document_type_id == DocumentType.id)
            .where(*conditions)
            .group_by(DocumentType.code, DocumentType.label)
        ).all()
        return sorted(
            (Bucket(key=code, label=label, count=count) for code, label, count in rows),
            key=lambda bucket: (-bucket.count, bucket.label or ""),
        )

    def _by_client(self, conditions: list[ColumnElement[bool]]) -> list[Bucket]:
        rows = self.session.execute(
            select(Client.id, Client.name, func.count(Document.id))
            .select_from(Document)
            .outerjoin(Client, Document.client_id == Client.id)
            .where(*conditions)
            .group_by(Client.id, Client.name)
        ).all()
        ranked = sorted(
            (
                Bucket(key=str(client_id) if client_id else None, label=name, count=count)
                for client_id, name, count in rows
            ),
            key=lambda bucket: (-bucket.count, bucket.label or ""),
        )
        return ranked[:TOP_CLIENTS]

    def _client_count(self, conditions: list[ColumnElement[bool]]) -> int:
        """Câți clienți distincți au documente — inclusiv „niciunul", ca grup."""
        rows = self.session.execute(
            select(Document.client_id).where(*conditions).group_by(Document.client_id)
        ).all()
        return len(rows)


__all__ = [
    "TOP_CLIENTS",
    "Bucket",
    "ReportService",
    "ReportSummary",
]
