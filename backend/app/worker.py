"""Procesul care execută cererile de procesare (§38, §43, ADR-003).

**De ce nu Celery + Redis.** Coada există deja și este durabilă:
`document_processing_jobs` este un outbox tranzacțional, revendicat cu
`FOR UPDATE SKIP LOCKED`. Un broker separat ar aduce încă un serviciu de rulat,
monitorizat și repornit, ca să facă exact ce face deja baza de date pe care oricum
o avem. La volumul unui cabinet contabil — sute de documente pe zi, nu sute pe
secundă — Postgres este coada potrivită.

Ce câștigăm: un singur loc unde se ține starea, deci nicio situație în care jobul
există în broker dar nu în baza de date, sau invers. Ce pierdem: throughput pe care
nu îl folosim. Dacă vreodată devine strâmt, `process(document_id)` are deja
semnătura unui task de worker — se schimbă transportul, nu logica.

**Rulare:**

    python -m app.worker                # bucla continuă
    python -m app.worker --once         # un singur tur, pentru cron sau teste

Workerul face două lucruri, nu unul: execută coada de procesare **și** întreabă
periodic sursele externe (OneDrive, cutia poștală) dacă a apărut ceva nou.

Mai multe procese pot rula în paralel: revendicarea este atomică, deci două worker-e
nu iau același job. Oprirea la `SIGINT`/`SIGTERM` este ordonată — jobul în lucru se
termină, apoi procesul iese.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import types
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.models.document import Document, DocumentProcessingJob
from app.services import processing_queue as queue
from app.services.microsoft.runner import run_drive_sync
from app.services.processing_runner import run_processing
from app.services.storage import StorageProvider
from app.services.storage.factory import build_storage_provider

logger = get_logger(__name__)

# Cât așteaptă workerul când coada este goală. Suficient de scurt ca un document
# încărcat să nu pară blocat, suficient de lung ca o bază de date liniștită să nu fie
# întrebată de o sută de ori pe secundă degeaba.
IDLE_SLEEP_SECONDS = 2.0

# Câte joburi ia într-un tur înainte să verifice din nou dacă a fost oprit.
BATCH = 10

# La cât timp întreabă Microsoft dacă a apărut ceva nou în dosarele urmărite și
# în cutia poștală.
#
# **De ce stă aici.** Sincronizarea era pornită dintr-un singur loc:
# `/internal/run-queue`, ruta pe care o bate cronul de pe Vercel. O instalare pe
# serverul cabinetului — `docker compose`, adică exact varianta din documentație —
# pornește acest worker și niciun cron, deci nu aducea niciodată nimic: dosarele
# rămâneau urmărite, ecranul arăta conexiunea activă, și nu sosea niciun document.
# Preluarea automată este tot ce a cerut cabinetul; nu are voie să depindă de
# platforma pe care se întâmplă să ruleze.
#
# Două minute, nu două secunde: fiecare tur costă cereri către Microsoft, iar
# documentele nu sosesc mai des de-atât.
SYNC_EVERY_SECONDS = 120.0


@dataclass
class Stopper:
    """Oprire ordonată: jobul în lucru se termină, apoi ieșim.

    Un `SIGTERM` care taie procesul în mijlocul extracției ar lăsa jobul `RUNNING`
    pentru totdeauna — recuperabil, dar abia după pragul de vechime. Mai bine îl
    lăsăm să se termine.
    """

    requested: bool = False

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle)

    def _handle(self, signum: int, _frame: types.FrameType | None) -> None:
        if self.requested:
            # Al doilea semnal: cineva chiar se grăbește.
            logger.warning("worker_force_stop", signal=signum)
            sys.exit(1)
        logger.info("worker_stop_requested", signal=signum)
        self.requested = True


def next_batch(limit: int = BATCH) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """Ce este de executat acum, într-o tranzacție scurtă.

    **Nu revendică** — de aceea nu se numește `claim`. Revendicarea propriu-zisă
    (`PENDING → RUNNING`) se face în `process()`, chiar înainte de muncă. Dacă ar fi
    făcută aici, un worker care moare între selecție și extracție ar lăsa jobul
    `RUNNING` și recuperabil abia după pragul de vechime; lăsat `PENDING`, este reluat
    imediat.

    `SKIP LOCKED` ține două worker-e care se uită simultan pe seturi disjuncte, fără
    să se aștepte unul pe altul. Dacă totuși ajung amândouă la același job, cel de-al
    doilea pierde la `queue.claim` și nu face nimic. Tranzacția se închide înainte de
    orice muncă: extracția nu are voie să țină un lock de coadă.
    """
    with session_scope() as session:
        jobs = session.scalars(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.status == queue.PENDING)
            .order_by(DocumentProcessingJob.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        if not jobs:
            return []

        # Documentul există întotdeauna: cheia străină are `ON DELETE CASCADE`, deci
        # un job nu poate supraviețui documentului lui.
        documents = {
            row.id: row
            for row in session.scalars(
                select(Document).where(Document.id.in_([job.document_id for job in jobs]))
            ).all()
        }
        return [
            (documents[job.document_id].organization_id, job.document_id, job.idempotency_key)
            for job in jobs
        ]


def run_once(storage: StorageProvider, *, limit: int = BATCH) -> int:
    """Un tur: câte cereri au fost executate."""
    claimed = next_batch(limit)
    for organization_id, document_id, key in claimed:
        run_processing(organization_id, document_id, storage, idempotency_key=key)
    return len(claimed)


def sync_sources(storage: StorageProvider) -> int:
    """Un tur peste sursele externe. Nu aruncă: un cabinet căzut nu oprește workerul."""
    try:
        report = run_drive_sync(storage)
    except Exception:
        logger.exception("worker_sync_failed")
        return 0
    return report.ingested


def run_forever(storage: StorageProvider, stopper: Stopper) -> None:
    logger.info(
        "worker_started",
        idle_seconds=IDLE_SLEEP_SECONDS,
        batch=BATCH,
        sync_seconds=SYNC_EVERY_SECONDS,
    )
    # `-inf`, nu `monotonic()`: primul tur se face la pornire, nu peste două minute.
    # Un worker repornit trebuie să recupereze imediat ce a apărut cât a fost jos.
    last_sync = float("-inf")

    while not stopper.requested:
        if time.monotonic() - last_sync >= SYNC_EVERY_SECONDS:
            last_sync = time.monotonic()
            sync_sources(storage)

        try:
            done = run_once(storage)
        except Exception:
            # Un tur eșuat nu are voie să oprească workerul: următorul document
            # poate fi perfect sănătos. Jobul rămâne recuperabil.
            logger.exception("worker_cycle_failed")
            done = 0

        if done == 0:
            _sleep_interruptibly(IDLE_SLEEP_SECONDS, stopper)
    logger.info("worker_stopped")


def _sleep_interruptibly(seconds: float, stopper: Stopper) -> None:
    """Somn care se trezește la oprire, nu după ce expiră."""
    deadline = time.monotonic() + seconds
    while not stopper.requested and time.monotonic() < deadline:
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))


def recover_stale(storage: StorageProvider) -> int:
    """Repune în coadă ce a rămas de la un proces mort.

    Se face o dată la pornire: dacă workerul tocmai a fost repornit, foarte probabil
    exact el este cel care a murit la mijloc.
    """
    from app.services.processing_recovery import recover

    report = recover(
        storage,
        stale_after=timedelta(minutes=settings.processing_stale_after_minutes),
        execute=False,
    )
    if report.requeued:
        logger.info("worker_recovered_on_start", requeued=report.requeued)
    return report.requeued


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Workerul de procesare a documentelor.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="execută un singur tur și iese (pentru cron sau verificări)",
    )
    parser.add_argument(
        "--no-recover",
        action="store_true",
        help="nu repune în coadă joburile rămase de la o rulare anterioară",
    )
    args = parser.parse_args(argv)

    configure_logging()
    storage = build_storage_provider()

    if not args.no_recover:
        recover_stale(storage)

    if args.once:
        # Aceeași ordine ca în buclă: întâi aducem ce e nou, apoi procesăm coada —
        # altfel un fișier apărut acum ar aștepta rularea următoare.
        ingested = sync_sources(storage)
        done = run_once(storage)
        print(f"documente aduse: {ingested}")
        print(f"cereri executate: {done}")
        return

    stopper = Stopper()
    stopper.install()
    run_forever(storage, stopper)


if __name__ == "__main__":
    main()
