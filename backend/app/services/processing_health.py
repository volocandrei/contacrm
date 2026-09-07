"""Starea cozii de procesare, ca răspuns la o singură întrebare (§7, §36).

**Întrebarea.** „De ce nu s-a procesat documentul pe care l-am urcat acum
douăzeci de minute?" Până acum, aplicația nu avea unde să răspundă. Documentul
stătea în `RECEIVED`, ecranul nu arăta nicio eroare — fiindcă nu era niciuna —
iar singurul semn că workerul murise era o coadă care creștea și pe care nu o
vedea nimeni. Se descoperea a doua zi, la o sută de documente neprocesate.

**Numărul care contează nu este câte sunt în coadă, ci de când așteaptă cea mai
veche.** O coadă de treizeci de cereri într-o dimineață aglomerată este normală
și se golește singură. O singură cerere care așteaptă de patruzeci de minute nu
are nicio explicație bună: ori workerul nu rulează, ori s-a blocat. Prima cifră
alarmează degeaba; a doua spune adevărul.

**Ce nu face.** Nu repară nimic și nu repornește nimic singur. Recuperarea are
comanda ei (`app.cli recover-processing`), iar reprocesarea unui document se
cere de pe documentul acela — acolo se vede ce se reprocesează. Un ecran care ar
relua totul cu un buton ar fi exact felul de acțiune pe care cineva o apasă de
două ori.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob
from app.services.processing_queue import FAILED, PENDING, RUNNING

#: Câte eșecuri recente se arată. Ecranul răspunde la „ce s-a stricat acum", nu
#: ține loc de jurnal: istoria completă a unei cereri stă pe documentul ei.
RECENT_FAILURES: Final = 20

#: Cât în urmă se uită lista de eșecuri. Un eșec de acum trei zile a fost deja
#: văzut sau deja nu mai contează; amestecat printre cele de azi, l-ar ascunde.
FAILURE_WINDOW: Final = timedelta(days=2)


@dataclass(frozen=True, slots=True)
class FailedJob:
    document_id: uuid.UUID
    original_filename: str
    client_name: str | None
    error_code: str | None
    error_detail: str | None
    attempt: int
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class QueueHealth:
    queued: int
    running: int
    #: `RUNNING` de mai mult decât are voie o procesare să dureze: procesul care
    #: le ținea a murit. `recover-processing` le readuce în coadă.
    stuck: int
    failed_recently: int
    #: De când așteaptă cea mai veche cerere nepornită. `None` = coada e goală.
    oldest_queued_at: datetime | None
    recent_failures: list[FailedJob]

    @property
    def waiting_seconds(self) -> int | None:
        if self.oldest_queued_at is None:
            return None
        return int((datetime.now(UTC) - self.oldest_queued_at).total_seconds())


class ProcessingHealthService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def health(self, *, stale_after: timedelta) -> QueueHealth:
        """Starea cozii cabinetului acestuia.

        Fiecare cifră se numără **prin documentul** cererii, nu direct pe tabelul
        de joburi: acela nu are organizație, fiindcă o cerere aparține unui
        document, iar documentul unui cabinet. Numărate direct, cifrele ar fi
        fost ale întregii instalări — un cabinet ar fi văzut coada altuia.
        """
        now = datetime.now(UTC)
        base = select(DocumentProcessingJob).join(
            Document, Document.id == DocumentProcessingJob.document_id
        )
        mine = base.where(Document.organization_id == self.organization_id)

        def count(*conditions: object) -> int:
            query = (
                select(func.count())
                .select_from(DocumentProcessingJob)
                .join(Document, Document.id == DocumentProcessingJob.document_id)
                .where(Document.organization_id == self.organization_id, *conditions)  # type: ignore[arg-type]
            )
            return self.session.scalar(query) or 0

        queued = count(DocumentProcessingJob.status == PENDING)
        running = count(DocumentProcessingJob.status == RUNNING)
        stuck = count(
            DocumentProcessingJob.status == RUNNING,
            DocumentProcessingJob.started_at < now - stale_after,
        )
        failed_recently = count(
            DocumentProcessingJob.status == FAILED,
            DocumentProcessingJob.finished_at >= now - FAILURE_WINDOW,
        )

        oldest = self.session.scalar(
            mine.with_only_columns(func.min(DocumentProcessingJob.created_at)).where(
                DocumentProcessingJob.status == PENDING
            )
        )

        return QueueHealth(
            queued=queued,
            running=running,
            stuck=stuck,
            failed_recently=failed_recently,
            oldest_queued_at=oldest,
            recent_failures=self._failures(now),
        )

    def _failures(self, now: datetime) -> list[FailedJob]:
        """Ce s-a stricat, cu numele fișierului și motivul scris.

        Numele și clientul, nu doar un identificator: cine deschide ecranul caută
        „factura de la Alfa", nu un UUID. `error_detail` este mesajul structurat
        al procesării, fără traceback (§53) — un traceback pe un ecran de cabinet
        nu se citește și, uneori, spune mai mult decât are voie.
        """
        rows = self.session.execute(
            select(DocumentProcessingJob, Document, Client)
            .join(Document, Document.id == DocumentProcessingJob.document_id)
            .outerjoin(Client, Client.id == Document.client_id)
            .where(
                Document.organization_id == self.organization_id,
                DocumentProcessingJob.status == FAILED,
                DocumentProcessingJob.finished_at >= now - FAILURE_WINDOW,
            )
            .order_by(DocumentProcessingJob.finished_at.desc())
            .limit(RECENT_FAILURES)
        ).all()

        return [
            FailedJob(
                document_id=document.id,
                original_filename=document.original_filename,
                client_name=client.name if client is not None else None,
                error_code=job.error_code,
                error_detail=job.error_detail,
                attempt=job.attempt,
                finished_at=job.finished_at,
            )
            for job, document, client in rows
        ]


__all__ = [
    "FAILURE_WINDOW",
    "RECENT_FAILURES",
    "FailedJob",
    "ProcessingHealthService",
    "QueueHealth",
]
