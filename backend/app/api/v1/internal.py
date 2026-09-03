"""Ruta prin care un planificator extern face treaba workerului (§38, §43).

**De ce există.** `app/worker.py` presupune un proces care trăiește: pornește,
ia din coadă, așteaptă, ia iar. Într-un mediu unde nimic nu rulează între cereri
— Vercel, Cloud Run scalat la zero — procesul acela nu are unde să existe. Ce
rămâne este un ceas din afară care bate periodic, iar bătaia trebuie să intre pe
undeva. Aici.

**Nu este o rută publică și nu este o rută de utilizator.** Nu are sesiune, nu
are organizație, nu apare în navigație. Singura ei autorizare este un secret
partajat cu planificatorul, comparat în timp constant. Fără `CRON_SECRET`
configurat, ruta răspunde `404`: un endpoint care execută muncă nu are voie să
fie deschis nici măcar o clipă, iar un `503` explicativ ar fi confirmat că
există.

**Face exact ce face workerul la pornire**, în aceeași ordine: mai întâi repune
în coadă ce a rămas de la o rulare moartă, apoi execută un lot. Într-un mediu
fără proces continuu, „o rulare moartă" este cazul normal — o funcție care a
depășit timpul maxim lasă exact aceeași urmă ca un proces ucis.

Lotul este mic deliberat. O invocare are un timp maxim, iar un lot care nu apucă
să se termine ar fi cea mai proastă variantă: muncă începută și abandonată, la
fiecare bătaie.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Header

from app.api.deps import StorageDep
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.schemas.common import ApiModel
from app.services.drive.runner import run_drive_sync
from app.services.processing_recovery import recover
from app.worker import run_once

logger = get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)

# Cât ia o singură bătaie. Sub limita de timp a oricărei platforme rezonabile,
# chiar dacă fiecare document merge prost.
CRON_BATCH = 5

# Câte cabinete se sincronizează într-o bătaie. Fiecare dosar își ține propriul
# token delta, deci ce nu apucă acum se ia la următoarea — nimic nu se pierde.
DRIVE_BATCH = 3


class QueueRunOut(ApiModel):
    """Ce a făcut bătaia. Se citește din logurile planificatorului, deci e scurt."""

    requeued: int
    executed: int
    #: Documente aduse din OneDrive în bătaia asta.
    ingested: int


def _authorized(authorization: str | None) -> bool:
    if not settings.cron_secret:
        return False
    if not authorization or not authorization.startswith("Bearer "):
        return False
    # Comparație în timp constant: altfel secretul se poate ghici caracter cu
    # caracter, măsurând cât durează refuzul.
    return secrets.compare_digest(authorization.removeprefix("Bearer "), settings.cron_secret)


@router.get("/run-queue", response_model=QueueRunOut)
def run_queue(
    storage: StorageDep,
    authorization: Annotated[str | None, Header()] = None,
) -> QueueRunOut:
    """Un tur de coadă, cerut din afară.

    `GET` pentru că asta trimite un cron; nu este idempotentă și nu pretinde că
    ar fi — dar două bătăi suprapuse nu se calcă, pentru că revendicarea din
    coadă este atomică (`FOR UPDATE SKIP LOCKED`). A doua nu găsește nimic de
    făcut și pleacă.
    """
    if not _authorized(authorization):
        # Același răspuns pentru „secret greșit" și „secret neconfigurat": nimic
        # din afară nu află care dintre ele s-a întâmplat.
        logger.warning("cron_unauthorized")
        raise AppError(ErrorCode.NOT_FOUND, "Resursa nu există.")

    report = recover(
        storage,
        stale_after=timedelta(minutes=settings.processing_stale_after_minutes),
        execute=False,
    )
    # Întâi aducem ce e nou în dosarele urmărite, apoi procesăm coada: altfel un
    # fișier apărut acum ar aștepta degeaba bătaia următoare.
    drive = run_drive_sync(storage, limit=DRIVE_BATCH)
    executed = run_once(storage, limit=CRON_BATCH)

    logger.info(
        "cron_queue_run",
        requeued=report.requeued,
        executed=executed,
        ingested=drive.ingested,
    )
    return QueueRunOut(requeued=report.requeued, executed=executed, ingested=drive.ingested)
