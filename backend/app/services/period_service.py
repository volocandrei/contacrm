"""Perioadele contabile, calculate din documente (§18, §19).

Ce se citește din baza de date: faptele umane — cine a deschis o lună, cine a
închis-o, ce se așteaptă de la fiecare client. Ce se calculează: tot restul.

Contoarele nu se stochează. Un contor ținut într-o coloană rămâne în urmă de fiecare
dată când cineva mută un document dintr-o lună în alta sau schimbă clientul, iar
„documente complete" devine o minciună exact în ecranul după care se închide luna.
Aici numărătoarea se face la citire, dintr-o singură interogare grupată.

Perioadele **fără rând în tabel** există și ele: dacă un client are documente în
august dar nimeni nu a atins luna, ea apare cu `openedAt: null`. Absența rândului
înseamnă „nu s-a întâmplat nimic administrativ", nu „luna nu există".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.domain.enums import DocumentStatus, PeriodStatus
from app.domain.periods import (
    ChecklistEntry,
    derive_period_status,
    is_valid_reference_month,
    period_progress,
    split_reference_month,
)
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.period import AccountingPeriod, ClientExpectation

logger = get_logger(__name__)

# Documentele care nu contează la checklist: un duplicat sau un document respins nu
# acoperă o obligație. Un document încă neprocesat contează — a sosit.
UNCOUNTED = (DocumentStatus.DUPLICATE, DocumentStatus.REJECTED)


@dataclass(frozen=True, slots=True)
class PeriodView:
    """O perioadă așa cum o vede interfața: fapte plus tot ce s-a calculat."""

    id: uuid.UUID | None
    client_id: uuid.UUID
    client_name: str
    reference_month: str
    year: int
    month: int
    status: PeriodStatus
    received_count: int
    satisfied_count: int
    expected_count: int
    checklist: list[ChecklistEntry]
    opened_at: datetime | None
    closed_at: datetime | None
    completed_at: datetime | None


class PeriodService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Citire ──────────────────────────────────────────────────────────────

    def list_periods(
        self,
        organization_id: uuid.UUID,
        *,
        reference_month: str | None = None,
        client_id: uuid.UUID | None = None,
        status: PeriodStatus | None = None,
    ) -> list[PeriodView]:
        """Perioadele care există, fie ca rând, fie doar prin documentele din ele."""
        clients = self._clients(organization_id, client_id)
        if not clients:
            return []

        counts = self._document_counts(organization_id, reference_month, client_id)
        expectations = self._expectations(organization_id)
        rows = self._period_rows(organization_id, reference_month, client_id)
        labels = self._type_labels(organization_id)

        months = self._months_in_play(counts, rows, reference_month)

        views: list[PeriodView] = []
        for client in clients:
            for month in sorted(months):
                per_type = counts.get((client.id, month), {})
                row = rows.get((client.id, month))
                # O lună fără documente și fără rând nu s-a întâmplat: nu o inventăm.
                if not per_type and row is None:
                    continue
                view = self._build(client, month, per_type, expectations, labels, row)
                if status is None or view.status is status:
                    views.append(view)

        views.sort(key=lambda v: (v.client_name.lower(), v.reference_month))
        return views

    def latest_active_month(self, organization_id: uuid.UUID) -> str | None:
        """Cea mai recentă lună în care există documente sau o perioadă atinsă.

        Panoul principal se uită la ea, **nu** la luna din calendar. Pe 1 septembrie
        un cabinet lucrează la august: documentele lunii încheiate încă sosesc, iar
        un panou care arată septembrie ar fi gol exact când e cel mai mult de lucru.

        TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: până când rămâne „luna
        în lucru" o lună încheiată. În practică se leagă de termenul declarației, dar
        pragul exact este o decizie a cabinetului (ADR-008). Până atunci urmăm datele,
        nu calendarul.
        """
        from_documents = self.session.scalar(
            select(func.max(Document.reference_month)).where(
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
                Document.client_id.is_not(None),
                Document.reference_month.is_not(None),
                Document.status.not_in(UNCOUNTED),
            )
        )
        from_periods = self.session.scalar(
            select(func.max(AccountingPeriod.reference_month)).where(
                AccountingPeriod.organization_id == organization_id
            )
        )
        candidates = [m for m in (from_documents, from_periods) if m]
        return max(candidates) if candidates else None

    def get(
        self, organization_id: uuid.UUID, client_id: uuid.UUID, reference_month: str
    ) -> PeriodView:
        found = self.list_periods(
            organization_id, reference_month=reference_month, client_id=client_id
        )
        if not found:
            raise NotFoundError("Perioadă", f"{client_id}/{reference_month}")
        return found[0]

    def missing(
        self, organization_id: uuid.UUID, reference_month: str
    ) -> list[tuple[PeriodView, list[ChecklistEntry]]]:
        """Ce se așteaptă și încă nu a sosit, per client (§19).

        Doar clienții cărora chiar le lipsește ceva: un raport care listează și
        clienții în regulă nu se mai citește.
        """
        result = []
        for view in self.list_periods(organization_id, reference_month=reference_month):
            gaps = [item for item in view.checklist if not item.is_satisfied]
            if gaps:
                result.append((view, gaps))
        return result

    # ── Fapte umane ─────────────────────────────────────────────────────────

    def touch(
        self, organization_id: uuid.UUID, client_id: uuid.UUID, reference_month: str
    ) -> AccountingPeriod:
        """Se apelează când un document ajunge într-o lună.

        Creează rândul dacă lipsește și marchează momentul în care checklistul a
        devenit prima dată complet. `completed_at` nu se poate deriva la citire —
        este *primul* moment, nu starea de acum — deci se scrie când se întâmplă.
        """
        if not is_valid_reference_month(reference_month):
            raise ConflictError(f"Lună de referință invalidă: {reference_month!r}.")

        period = self._row(organization_id, client_id, reference_month)
        if period is None:
            year, month = split_reference_month(reference_month)
            period = AccountingPeriod(
                organization_id=organization_id,
                client_id=client_id,
                reference_month=reference_month,
                year=year,
                month=month,
                opened_at=datetime.now(UTC),
            )
            self.session.add(period)
            self.session.flush()

        view = self.get(organization_id, client_id, reference_month)
        if view.status is PeriodStatus.COMPLETE and period.completed_at is None:
            period.completed_at = datetime.now(UTC)
            self.session.flush()
            logger.info(
                "period_completed", client_id=str(client_id), reference_month=reference_month
            )
        return period

    def close(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        reference_month: str,
        *,
        closed_by: uuid.UUID,
        force: bool = False,
    ) -> AccountingPeriod:
        """Închide luna.

        Refuză dacă mai lipsesc documente așteptate, **dacă nu** i se cere explicit
        altfel. Închiderea este declarația că luna este gata; a o lăsa să treacă
        peste un checklist incomplet ar goli-o de sens. Dar decizia rămâne a omului:
        există motive legitime — un client care chiar nu a avut extras de cont luna
        asta — iar sistemul nu le cunoaște.
        """
        view = self.get(organization_id, client_id, reference_month)
        if view.closed_at is not None:
            raise ConflictError("Perioada este deja închisă.")

        gaps = [item for item in view.checklist if not item.is_satisfied]
        if gaps and not force:
            names = ", ".join(item.document_type_label for item in gaps)
            raise ConflictError(f"Mai lipsesc documente așteptate: {names}.")

        period = self.touch(organization_id, client_id, reference_month)
        period.closed_at = datetime.now(UTC)
        period.closed_by = closed_by
        self.session.flush()
        logger.info(
            "period_closed",
            client_id=str(client_id),
            reference_month=reference_month,
            forced=bool(gaps),
        )
        return period

    def reopen(
        self, organization_id: uuid.UUID, client_id: uuid.UUID, reference_month: str
    ) -> AccountingPeriod:
        """Redeschide o lună închisă. Rămâne în audit cine și când.

        `get` întâi, ca răspunsul să fie 404 pentru o lună care nu există — inclusiv
        a unui client din altă organizație. Un 409 acolo ar spune „perioada există,
        dar nu e închisă", ceea ce confirmă existența clientului.
        """
        self.get(organization_id, client_id, reference_month)

        period = self._row(organization_id, client_id, reference_month)
        if period is None or period.closed_at is None:
            raise ConflictError("Perioada nu este închisă.")
        period.closed_at = None
        period.closed_by = None
        self.session.flush()
        logger.info("period_reopened", client_id=str(client_id), reference_month=reference_month)
        return period

    def is_closed(
        self, organization_id: uuid.UUID, client_id: uuid.UUID, reference_month: str
    ) -> bool:
        period = self._row(organization_id, client_id, reference_month)
        return period is not None and period.closed_at is not None

    # ── Interogări interne ──────────────────────────────────────────────────

    def _clients(self, organization_id: uuid.UUID, client_id: uuid.UUID | None) -> list[Client]:
        stmt = select(Client).where(
            Client.organization_id == organization_id, Client.deleted_at.is_(None)
        )
        if client_id is not None:
            stmt = stmt.where(Client.id == client_id)
        return list(self.session.scalars(stmt).all())

    def _document_counts(
        self,
        organization_id: uuid.UUID,
        reference_month: str | None,
        client_id: uuid.UUID | None,
    ) -> dict[tuple[uuid.UUID, str], dict[uuid.UUID | None, int]]:
        """Câte documente are fiecare client, în fiecare lună, pe fiecare tip.

        O singură interogare grupată pentru tot ecranul: alternativa ar fi o
        numărătoare per perioadă, adică N+1 pe numărul de clienți.
        """
        stmt = (
            select(
                Document.client_id,
                Document.reference_month,
                Document.document_type_id,
                func.count(),
            )
            .where(
                Document.organization_id == organization_id,
                Document.deleted_at.is_(None),
                Document.client_id.is_not(None),
                Document.reference_month.is_not(None),
                Document.status.not_in(UNCOUNTED),
            )
            .group_by(Document.client_id, Document.reference_month, Document.document_type_id)
        )
        if reference_month is not None:
            stmt = stmt.where(Document.reference_month == reference_month)
        if client_id is not None:
            stmt = stmt.where(Document.client_id == client_id)

        counts: dict[tuple[uuid.UUID, str], dict[uuid.UUID | None, int]] = {}
        for row_client_id, month, type_id, total in self.session.execute(stmt).all():
            counts.setdefault((row_client_id, month), {})[type_id] = total
        return counts

    def _expectations(self, organization_id: uuid.UUID) -> dict[uuid.UUID, list[ClientExpectation]]:
        rows = self.session.scalars(
            select(ClientExpectation).where(ClientExpectation.organization_id == organization_id)
        ).all()
        grouped: dict[uuid.UUID, list[ClientExpectation]] = {}
        for row in rows:
            grouped.setdefault(row.client_id, []).append(row)
        return grouped

    def _type_labels(self, organization_id: uuid.UUID) -> dict[uuid.UUID, tuple[str, str]]:
        rows = self.session.execute(
            select(DocumentType.id, DocumentType.code, DocumentType.label).where(
                DocumentType.organization_id == organization_id
            )
        ).all()
        return {row[0]: (row[1], row[2]) for row in rows}

    def _period_rows(
        self,
        organization_id: uuid.UUID,
        reference_month: str | None,
        client_id: uuid.UUID | None,
    ) -> dict[tuple[uuid.UUID, str], AccountingPeriod]:
        stmt = select(AccountingPeriod).where(AccountingPeriod.organization_id == organization_id)
        if reference_month is not None:
            stmt = stmt.where(AccountingPeriod.reference_month == reference_month)
        if client_id is not None:
            stmt = stmt.where(AccountingPeriod.client_id == client_id)
        return {
            (row.client_id, row.reference_month): row for row in self.session.scalars(stmt).all()
        }

    def _row(
        self, organization_id: uuid.UUID, client_id: uuid.UUID, reference_month: str
    ) -> AccountingPeriod | None:
        return self.session.scalars(
            select(AccountingPeriod).where(
                AccountingPeriod.organization_id == organization_id,
                AccountingPeriod.client_id == client_id,
                AccountingPeriod.reference_month == reference_month,
            )
        ).first()

    @staticmethod
    def _months_in_play(
        counts: dict[tuple[uuid.UUID, str], dict[uuid.UUID | None, int]],
        rows: dict[tuple[uuid.UUID, str], AccountingPeriod],
        reference_month: str | None,
    ) -> set[str]:
        if reference_month is not None:
            return {reference_month}
        return {month for _, month in counts} | {month for _, month in rows}

    def _build(
        self,
        client: Client,
        reference_month: str,
        per_type: dict[uuid.UUID | None, int],
        expectations: dict[uuid.UUID, list[ClientExpectation]],
        labels: dict[uuid.UUID, tuple[str, str]],
        row: AccountingPeriod | None,
    ) -> PeriodView:
        checklist = [
            ChecklistEntry(
                document_type=labels[expectation.document_type_id][0],
                document_type_label=labels[expectation.document_type_id][1],
                expected_min_count=expectation.expected_min_count,
                received_count=per_type.get(expectation.document_type_id, 0),
            )
            for expectation in expectations.get(client.id, [])
            if expectation.document_type_id in labels
        ]
        checklist.sort(key=lambda item: item.document_type)

        received_count = sum(per_type.values())
        progress = period_progress(checklist)
        year, month = split_reference_month(reference_month)

        return PeriodView(
            id=row.id if row else None,
            client_id=client.id,
            client_name=client.name,
            reference_month=reference_month,
            year=year,
            month=month,
            status=derive_period_status(
                checklist, received_count, is_closed=bool(row and row.closed_at)
            ),
            received_count=received_count,
            satisfied_count=progress.satisfied,
            expected_count=progress.expected,
            checklist=checklist,
            opened_at=row.opened_at if row else None,
            closed_at=row.closed_at if row else None,
            completed_at=row.completed_at if row else None,
        )


__all__ = ["PeriodService", "PeriodView"]
