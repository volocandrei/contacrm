"""Semnul că workerul este viu (§9).

**Ce lipsea.** Un worker mort nu se vedea nicăieri. Documentele intrau, rămâneau
în `PENDING`, iar ecranul nu arăta nicio eroare — fiindcă nu era niciuna. Singurul
semn era o coadă care creștea și pe care nu o privea nimeni; se descoperea a doua
zi, la o sută de documente neprocesate.

**De ce un rând în baza de date, și nu un fișier sau o metrică.** Procesul care
răspunde la `/health/workers` este **altul** decât workerul, adesea pe altă
mașină. Singurul lucru pe care îl împart este baza. Un fișier ar fi mers doar cât
timp stau împreună — adică exact până la prima instalare care le separă.

**Ce nu este.** Nu este o listă de procese și nu se șterge singur: un worker care
a fost oprit intenționat lasă în urmă ultimul lui bătut, iar vechimea acestuia
este chiar informația căutată. Ștergerea rândului ar fi făcut „oprit deliberat"
să arate identic cu „nu a existat niciodată".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk

#: Numele sub care bate workerul obișnuit. Un al doilea proces, cu alt rol, ar
#: folosi alt nume — de aceea numele este cheia, nu un rând unic.
DEFAULT_WORKER = "processing"


class WorkerHeartbeat(Base):
    """Ultima dată la care un worker a spus că trăiește."""

    __tablename__ = "worker_heartbeats"

    id: Mapped[uuid_pk]
    #: Cine bate. Unic: fiecare worker are un singur rând, actualizat.
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: Când a bătut ultima oară. Ceasul **bazei**, nu al procesului: două mașini
    #: cu ceasuri diferite ar fi produs o vechime negativă sau una uriașă, iar
    #: alarma ar fi sunat din cauza NTP-ului, nu a workerului.
    beat_at: Mapped[datetime] = mapped_column(nullable=False)
    #: De unde bate, ca să se știe care proces a murit când sunt mai multe.
    hostname: Mapped[str | None] = mapped_column(String(255), default=None)
    pid: Mapped[int | None] = mapped_column(default=None)

    def __repr__(self) -> str:
        return f"<WorkerHeartbeat {self.name} {self.beat_at}>"
