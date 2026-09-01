"""Reluarea cererilor de procesare rămase pe drum (§43, §55).

Outbox-ul (`processing_queue`) garantează că o cerere nu se **pierde**: rândul se
scrie în aceeași tranzacție cu documentul. Nu garantează că cineva o și duce la
capăt — procesul care o execută poate cădea la mijloc.

Aici este partea a doua: găsim cererile abandonate și le repunem în coadă.

Două feluri de abandon:

- `PENDING` care nu a pornit niciodată — procesul a murit între commit și pornirea
  taskului;
- `RUNNING` mai vechi decât pragul de vechime — a murit în timpul extracției.

Documentul rămas în `PROCESSING` nu are nevoie de nimic special: mașina de stări
acceptă `PROCESSING → PROCESSING`, deci reluarea îl duce mai departe de unde a
rămas. `attempt` nu crește (vezi `queue.reset`): un proces care cade repetat nu are
voie să consume limita de reprocesări a nimănui.

Astăzi se cheamă din `app.cli recover-processing`. Când vine coada persistentă
(M6), aceeași funcție rulează periodic în worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.document import Document
from app.services import processing_queue as queue
from app.services.processing_runner import run_processing
from app.services.storage import StorageProvider

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Ce s-a găsit și ce s-a reluat. Se afișează, deci trebuie să fie citibil."""

    requeued: int
    ran: int

    @property
    def nothing_to_do(self) -> bool:
        return self.requeued == 0


def recover(
    storage: StorageProvider,
    *,
    stale_after: timedelta | None = None,
    limit: int = 100,
    execute: bool = True,
) -> RecoveryReport:
    """Repune în coadă cererile abandonate și, opțional, le rulează.

    Repunerea și rularea sunt tranzacții separate. Prima se comite singură, deci
    chiar dacă rularea eșuează sau procesul cade din nou, cererea rămâne `PENDING`
    și o rulare următoare o va găsi.
    """
    threshold = stale_after or timedelta(minutes=settings.processing_stale_after_minutes)

    with session_scope() as session:
        jobs = queue.abandoned(session, running_older_than=threshold, limit=limit)
        pending: list[tuple[str, uuid.UUID]] = []
        for job in jobs:
            if job.status == queue.RUNNING:
                queue.reset(session, job)
            document = job.document_id
            pending.append((job.idempotency_key, document))
            logger.info(
                "processing_requeued",
                document_id=str(document),
                attempt=job.attempt,
                previous_status=job.status,
            )
        organizations = _organizations_of(session, [document for _, document in pending])

    if not execute:
        return RecoveryReport(requeued=len(pending), ran=0)

    ran = 0
    for key, document_id in pending:
        organization_id = organizations.get(document_id)
        if organization_id is None:
            # Documentul a fost șters între timp; jobul nu mai are ce relua.
            logger.warning("processing_requeue_orphan", document_id=str(document_id))
            continue
        run_processing(organization_id, document_id, storage, idempotency_key=key)
        ran += 1

    return RecoveryReport(requeued=len(pending), ran=ran)


def _organizations_of(
    session: Session, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Organizația fiecărui document, citită **înainte** ca sesiunea să se închidă.

    Rularea se face pe sesiuni proprii, deci obiectele nu mai sunt disponibile după
    ieșirea din `session_scope`. Luăm doar ce ne trebuie: două UUID-uri.
    """
    if not document_ids:
        return {}
    rows = session.execute(
        select(Document.id, Document.organization_id).where(Document.id.in_(document_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


__all__ = ["RecoveryReport", "recover"]
