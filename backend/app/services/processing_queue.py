"""Coada de procesare, ca outbox tranzacțional (§38, §39, §43).

Problema pe care o rezolvă: „am salvat documentul, apoi am programat procesarea"
sunt două acte, iar între ele procesul poate cădea. Dacă programarea trăiește doar
în memorie, cererea se pierde și documentul rămâne tăcut în `RECEIVED` — exact
defectul găsit la M5.5, rulând serverul.

Soluția: cererea se scrie **în aceeași tranzacție cu documentul**, ca rând `PENDING`
în `document_processing_jobs`. Ori se comit amândouă, ori niciunul. Cine execută —
un background task azi, un worker Celery mâine — doar revendică rândul.

Revendicarea este o tranziție de stare, nu o citire: `PENDING → RUNNING` sub
`FOR UPDATE`, deci doi executanți nu pot lua același job. Un job care nu mai este
`PENDING` a fost deja tratat, iar a doua livrare a aceleiași cereri nu produce
nimic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.document import Document, DocumentProcessingJob

logger = get_logger(__name__)

JOB_TYPE = "EXTRACTION"

PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
# Documentul a mers între timp în altă parte. Nu este o eroare, dar nici nu mai e
# nimic de făcut — a-l trece la `FAILED` ar umple raportul de eșecuri cu lucruri
# care au mers exact cum trebuia.
SKIPPED = "SKIPPED"


def idempotency_key(document_id: uuid.UUID, attempt: int) -> str:
    """Cheia unei cereri. Aceeași cerere, relivrată, dă aceeași cheie."""
    return f"{document_id}:{attempt}"


def unfinished(session: Session, document_id: uuid.UUID) -> DocumentProcessingJob | None:
    """Ultima cerere care nu s-a încheiat: `PENDING` sau `RUNNING`."""
    return session.scalars(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.document_id == document_id,
            DocumentProcessingJob.status.in_([PENDING, RUNNING]),
        )
        .order_by(DocumentProcessingJob.created_at.desc())
        .limit(1)
    ).first()


def enqueue(
    session: Session,
    document: Document,
    *,
    job_type: str = JOB_TYPE,
    stale_after: timedelta | None = None,
) -> DocumentProcessingJob:
    """Înregistrează cererea de procesare. Se apelează **înainte** de commit.

    Nu pornește nimic: doar spune „asta trebuie făcut".

    Dacă documentul are deja o cerere neîncheiată, aceea **este** cererea — nu se
    creează a doua. Două apăsări pe „Reprocesează" nu înseamnă două procesări, iar
    un job rămas `PENDING` de la o încercare care nu a apucat să pornească se reia,
    în loc să fie dublat.

    Excepția: un job `RUNNING` mai vechi decât `stale_after` aparține unui proces
    care a murit. Cererea nouă îl readuce în `PENDING` — adică butonul de
    reprocesare deblochează și documentele înțepenite, fără să aștepte recuperarea.
    """
    existing = unfinished(session, document.id)
    if existing is not None:
        if (
            existing.status == RUNNING
            and stale_after is not None
            and _is_stale(existing, stale_after)
        ):
            reset(session, existing)
            logger.info(
                "processing_job_revived",
                document_id=str(document.id),
                attempt=existing.attempt,
            )
        return existing

    attempt = document.processing_attempts + 1
    job = DocumentProcessingJob(
        document_id=document.id,
        job_type=job_type,
        status=PENDING,
        attempt=attempt,
        idempotency_key=idempotency_key(document.id, attempt),
    )
    session.add(job)
    session.flush()
    logger.info("processing_enqueued", document_id=str(document.id), attempt=attempt)
    return job


def _is_stale(job: DocumentProcessingJob, older_than: timedelta) -> bool:
    if job.started_at is None:
        return True
    return job.started_at < datetime.now(UTC) - older_than


def claim(
    session: Session, key: str, *, provider: str | None = None
) -> DocumentProcessingJob | None:
    """Ia jobul dacă mai este de făcut; `None` dacă altcineva l-a luat deja.

    `FOR UPDATE` ține rândul până la finalul tranzacției, deci doi executanți care
    pornesc simultan nu pot ajunge amândoi să proceseze.
    """
    job = session.scalars(
        select(DocumentProcessingJob)
        .where(DocumentProcessingJob.idempotency_key == key)
        .with_for_update()
    ).first()

    if job is None:
        return None
    if job.status != PENDING:
        return None

    job.status = RUNNING
    job.started_at = datetime.now(UTC)
    job.provider = provider
    session.flush()
    return job


def finish(
    job: DocumentProcessingJob,
    status: str,
    *,
    error_code: str | None = None,
    error_detail: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Închide jobul. Fără traceback — codul se poate filtra și număra, urma nu (§53)."""
    job.status = status
    job.finished_at = datetime.now(UTC)
    job.error_code = error_code
    job.error_detail = None if error_detail is None else error_detail[:512]
    job.duration_ms = duration_ms


# ── Recuperare ───────────────────────────────────────────────────────────────


def abandoned(
    session: Session, *, running_older_than: timedelta, limit: int = 100
) -> list[DocumentProcessingJob]:
    """Cererile care au rămas pe drum.

    Două feluri: `PENDING` care nu a pornit niciodată (procesul a căzut între commit
    și pornirea taskului), și `RUNNING` care nu s-a mai terminat (a căzut în timpul
    extracției). Al doilea are nevoie de un prag de timp — un job pornit acum o
    secundă lucrează, nu este abandonat.
    """
    cutoff = datetime.now(UTC) - running_older_than
    return list(
        session.scalars(
            select(DocumentProcessingJob)
            .where(
                (DocumentProcessingJob.status == PENDING)
                | (
                    (DocumentProcessingJob.status == RUNNING)
                    & (DocumentProcessingJob.started_at < cutoff)
                )
            )
            .order_by(DocumentProcessingJob.created_at)
            .limit(limit)
        ).all()
    )


def reset(session: Session, job: DocumentProcessingJob) -> None:
    """Readuce un job abandonat în `PENDING`, ca să poată fi revendicat din nou.

    `attempt` **nu** crește: nu este o încercare nouă, este aceeași care nu a apucat
    să se termine. Altfel un proces care cade repetat ar consuma limita de
    reprocesări fără ca nimeni să fi cerut ceva.
    """
    job.status = PENDING
    job.started_at = None
    job.finished_at = None
    job.error_code = None
    job.error_detail = None
    session.flush()


__all__ = [
    "FAILED",
    "JOB_TYPE",
    "PENDING",
    "RUNNING",
    "SKIPPED",
    "SUCCEEDED",
    "abandoned",
    "claim",
    "enqueue",
    "finish",
    "idempotency_key",
    "reset",
    "unfinished",
]
