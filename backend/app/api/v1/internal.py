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
from sqlalchemy import select

from app.api.deps import StorageDep
from app.api.route import CommittingRoute
from app.core import clock
from app.core.config import settings
from app.core.db import session_scope
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.models.organization import Organization
from app.schemas.common import ApiModel
from app.services import worker_health
from app.services.anaf.runner import run_anaf_sync
from app.services.daily_digest import DailyDigestService
from app.services.imap.runner import run_imap_sync
from app.services.mail import build_email_sender
from app.services.microsoft.runner import run_drive_sync
from app.services.processing_recovery import recover
from app.services.rate_limit import forget_old
from app.services.reminders import run_reminders
from app.worker import run_once

logger = get_logger(__name__)

router = APIRouter(
    route_class=CommittingRoute, prefix="/internal", tags=["internal"], include_in_schema=False
)

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
    #: Documente aduse din surse externe — OneDrive, email, e-Factura — în
    #: bătaia asta. Un singur număr: planificatorul citește o linie, nu un raport.
    ingested: int


def _forget_old_rate_limit_windows() -> None:
    """Curățenie în contorul de încercări, în tranzacție proprie.

    Rândurile sunt mici, dar fără ștergere ar fi unul per adresă care a greșit
    vreodată o parolă, la nesfârșit. Ca și bătutul: un eșec aici nu are voie să
    oprească turul.
    """
    try:
        with session_scope() as session:
            forgotten = forget_old(session)
        if forgotten:
            logger.info("rate_limit_windows_forgotten", count=forgotten)
    except Exception:
        logger.exception("rate_limit_cleanup_failed")


def _beat() -> None:
    """Scrie semnul de viață al workerului, într-o tranzacție proprie.

    **Un eșec aici nu are voie să oprească turul.** Bătutul este un semnal despre
    muncă, nu munca însăși: dacă baza clipește o clipă, turul trebuie să continue,
    iar vechimea semnalului va spune singură ce s-a întâmplat. Aceeași regulă ca
    în `app/worker.py`.
    """
    try:
        with session_scope() as session:
            worker_health.beat(session)
    except Exception:
        logger.exception("cron_heartbeat_failed")


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

    # Semnul de viață, înaintea muncii. **Pe o platformă fără proces continuu —
    # Vercel, de exemplu — ruta asta *este* workerul.** Fără bătaia de aici,
    # `/health/workers` ar fi raportat la nesfârșit „nu a raportat niciodată",
    # monitorul ar fi sunat la fiecare verificare, iar după a treia zi nimeni
    # nu s-ar mai fi uitat la el — adică exact alarma de care avem nevoie ar fi
    # fost cea ignorată.
    _beat()
    _forget_old_rate_limit_windows()

    report = recover(
        storage,
        stale_after=timedelta(minutes=settings.processing_stale_after_minutes),
        execute=False,
    )
    # Întâi aducem ce e nou din sursele externe, apoi procesăm coada: altfel un
    # fișier apărut acum ar aștepta degeaba bătaia următoare.
    drive = run_drive_sync(storage, limit=DRIVE_BATCH)
    anaf = run_anaf_sync(storage, limit=DRIVE_BATCH)
    imap = run_imap_sync(storage, limit=DRIVE_BATCH)
    executed = run_once(storage, limit=CRON_BATCH)

    ingested = drive.ingested + anaf.ingested + imap.ingested
    logger.info(
        "cron_queue_run",
        requeued=report.requeued,
        executed=executed,
        ingested=ingested,
        from_drive=drive.ingested,
        from_anaf=anaf.ingested,
        from_imap=imap.ingested,
    )
    return QueueRunOut(requeued=report.requeued, executed=executed, ingested=ingested)


class DigestRunOut(ApiModel):
    """Câte rezumate au plecat. Planificatorul citește o linie, nu un raport."""

    organizations: int
    sent: int


@router.get("/daily-digest", response_model=DigestRunOut)
def daily_digest(authorization: Annotated[str | None, Header()] = None) -> DigestRunOut:
    """Rezumatul zilei, către fiecare cabinet.

    **De ce există.** Aplicația nu face nimic dacă nu o deschide cineva. Știe că
    trei clienți n-au răspuns de o săptămână și că un termen e peste două zile,
    dar așteaptă să fie întrebată.

    **Către cabinet, nu către clienți.** Mesajele către clienți pleacă pe cealaltă
    rută, `/internal/reminders`, cu regulile ei. Sunt lucruri diferite și au
    comutatoare diferite: un cabinet poate vrea rezumatul de dimineață fără să lase
    aplicația să scrie clienților, iar invers nu are sens.

    **Oprit implicit**, spre deosebire de remindere: rezumatul este o obișnuință a
    cabinetului, nu o funcție de care depinde cineva.

    Se cheamă o dată pe zi, dimineața. Chemată de două ori, trimite de două ori:
    nu are idempotență, fiindcă un rezumat este o fotografie a momentului, nu o
    scriere. Planificatorul răspunde de cadență.

    *NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE.*
    """
    if not _authorized(authorization):
        logger.warning("cron_unauthorized")
        raise AppError(ErrorCode.NOT_FOUND, "Resursa nu există.")

    if not settings.daily_digest_enabled:
        return DigestRunOut(organizations=0, sent=0)

    sender = build_email_sender()
    today = clock.today()
    organizations = 0
    sent = 0

    with session_scope() as session:
        for organization_id in session.scalars(select(Organization.id)):
            organizations += 1
            sent += DailyDigestService(session, organization_id).send(sender, today=today)

    logger.info("daily_digest", organizations=organizations, sent=sent)
    return DigestRunOut(organizations=organizations, sent=sent)


class ReminderRunOut(ApiModel):
    """Câte reamintiri au plecat. O linie în logul planificatorului."""

    sent: int
    failed: int


@router.get("/reminders", response_model=ReminderRunOut)
def reminders(authorization: Annotated[str | None, Header()] = None) -> ReminderRunOut:
    """Reamintirile către clienți, o dată pe zi.

    **De ce este singura rută care scrie în afara cabinetului.** Rezumatul zilnic
    merge la colegi; asta merge la clienții cabinetului, în numele lui. Cabinetul
    a hotărât că are voie, iar `app/services/reminders.py` ține tot ce face
    hotărârea suportabilă: nu se reamintește ce nu s-a cerut, nu mai des de câteva
    zile, nu celui care tocmai a trimis ceva, cel mult două pe lună, deloc după
    termen.

    Se cheamă dimineața. Chemată de două ori în aceeași zi nu trimite de două ori:
    primul mesaj face ca al doilea să cadă sub regula zilelor de tăcere. Asta nu
    este idempotență, este exact regula de business — dar are același efect acolo
    unde contează, la client.

    *NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE.*
    """
    if not _authorized(authorization):
        logger.warning("cron_unauthorized")
        raise AppError(ErrorCode.NOT_FOUND, "Resursa nu există.")

    report = run_reminders(build_email_sender())
    logger.info("cron_reminders", sent=report.sent, failed=report.failed)
    return ReminderRunOut(sent=report.sent, failed=report.failed)
