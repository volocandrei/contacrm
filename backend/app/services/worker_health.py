"""Cât de proaspăt este ultimul semn de viață al workerului (§9).

**Regula pe care o impune modulul:** un worker nu este sănătos pentru că procesul
există. Este sănătos dacă a **terminat un tur recent**. Un proces blocat într-un
apel de rețea care nu se mai întoarce este viu pentru sistemul de operare și mort
pentru cabinet — documentele lui stau în coadă la fel ca și cum ar fi murit.

**Ceasul este al bazei, nu al procesului.** `beat()` scrie `now()` executat de
PostgreSQL, iar `staleness()` compară tot cu ceasul bazei. Două mașini cu ceasuri
nesincronizate ar fi produs o vechime negativă sau una uriașă, iar alarma ar fi
sunat pentru NTP, nu pentru worker.

**De ce nu se șterge rândul la oprire.** Un worker oprit deliberat lasă în urmă
ultimul lui bătut, iar vechimea aceluia este chiar informația căutată. Șters,
„oprit aseară" ar fi arătat identic cu „nu a existat niciodată" — iar al doilea
caz se citește, greșit, ca o instalare nouă.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.worker import DEFAULT_WORKER, WorkerHeartbeat

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    """Ce știm despre un worker, și de când."""

    name: str
    #: `None` = nu a bătut niciodată. Se deosebește de „a bătut demult".
    beat_at: datetime | None
    age_seconds: int | None
    hostname: str | None
    pid: int | None
    timeout_seconds: int

    @property
    def has_ever_beaten(self) -> bool:
        return self.beat_at is not None

    @property
    def is_fresh(self) -> bool:
        """Sănătos = a bătut, și nu demult.

        Un worker care nu a bătut **niciodată** nu este sănătos. Tratat ca atare
        de la început, o instalare în care workerul nu a fost pornit deloc arată
        exact ce este: fără worker. Tratat ca „necunoscut", ar fi tăcut până la
        primul document — adică până când conta.
        """
        return self.age_seconds is not None and self.age_seconds <= self.timeout_seconds

    def describe(self) -> str:
        """Ce se scrie într-o alertă, în cuvinte."""
        if self.beat_at is None:
            return f"Workerul {self.name} nu a raportat niciodată."
        if self.is_fresh:
            return f"Workerul {self.name} a raportat acum {self.age_seconds} secunde."
        return (
            f"Workerul {self.name} nu a mai raportat de {self.age_seconds} secunde "
            f"(pragul este {self.timeout_seconds}). Documentele se strâng în coadă."
        )


def beat(session: Session, name: str = DEFAULT_WORKER) -> None:
    """Scrie „sunt viu", cu ceasul bazei.

    `ON CONFLICT DO UPDATE`: un singur rând pe worker, actualizat. Un `INSERT` la
    fiecare tur ar fi umplut tabelul cu istorie pe care nimeni nu o citește.
    """
    statement = (
        insert(WorkerHeartbeat)
        .values(
            name=name,
            beat_at=func.now(),
            hostname=socket.gethostname()[:255],
            pid=os.getpid(),
        )
        .on_conflict_do_update(
            index_elements=[WorkerHeartbeat.name],
            set_={
                "beat_at": func.now(),
                "hostname": socket.gethostname()[:255],
                "pid": os.getpid(),
            },
        )
    )
    session.execute(statement)


def status(session: Session, name: str = DEFAULT_WORKER) -> WorkerStatus:
    """Vechimea ultimului bătut, măsurată de bază."""
    timeout = settings.worker_heartbeat_timeout_seconds
    row = session.execute(
        select(
            WorkerHeartbeat.beat_at,
            WorkerHeartbeat.hostname,
            WorkerHeartbeat.pid,
            # Diferența se calculează **în bază**, ca să nu intre ceasul
            # procesului care întreabă în ecuație.
            func.extract("epoch", func.now() - WorkerHeartbeat.beat_at),
        ).where(WorkerHeartbeat.name == name)
    ).first()

    if row is None:
        return WorkerStatus(
            name=name,
            beat_at=None,
            age_seconds=None,
            hostname=None,
            pid=None,
            timeout_seconds=timeout,
        )

    beat_at, hostname, pid, age = row
    return WorkerStatus(
        name=name,
        beat_at=beat_at,
        # Negativ ar însemna un ceas de bază care a mers înapoi; zero este mai
        # onest decât o vechime imposibilă.
        age_seconds=max(0, int(age)),
        hostname=hostname,
        pid=pid,
        timeout_seconds=timeout,
    )


def is_stale(session: Session, name: str = DEFAULT_WORKER) -> bool:
    return not status(session, name).is_fresh


__all__ = [
    "WorkerStatus",
    "beat",
    "is_stale",
    "status",
]
