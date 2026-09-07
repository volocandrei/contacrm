"""Reminderele către clienți: cine primește, cine nu, și de ce.

**Ecranul răspunde la două întrebări**, iar a doua este cea care lipsea peste
tot. Prima: cui îi pleacă azi o reamintire. A doua: **de ce nu-i pleacă
celuilalt** — nu i s-a cerut niciodată, a răspuns ieri, nu are email, a primit
deja două luna asta. Un ecran care arată doar prima listă lasă contabilul să
creadă că aplicația a uitat pe cineva.

**Citirea nu trimite nimic.** `GET` calculează stările; niciun link nu se deschide
și niciun mesaj nu pleacă. Efectele se produc doar din `POST`, la apăsare — sau,
în afara aplicației, la ora planificatorului.

Ambele cer `communication:send`: ecranul este despre ce iese din cabinet către
clienți, iar lista poartă adresele lor.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Request

from app.api.deps import DbSession, client_ip, require_permission
from app.api.route import CommittingRoute
from app.core import clock
from app.core.config import settings
from app.domain.enums import ReminderStatus
from app.domain.permissions import Permission
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.mail import build_email_sender
from app.services.reminders import MAX_PER_MONTH, SILENCE_DAYS, ReminderRow, ReminderService

router = APIRouter(route_class=CommittingRoute, prefix="/reminders", tags=["communication"])

ReminderSender = Annotated[User, require_permission(Permission.COMMUNICATION_SEND)]


class ReminderRowOut(ApiModel):
    client_id: uuid.UUID
    client_name: str
    #: Câte tipuri de document mai lipsesc.
    missing_count: int
    status: ReminderStatus
    last_message_at: datetime | None
    days_silent: int | None
    sent_count: int
    #: Adresa către care ar pleca. Se arată pentru că altfel „trimite" este o
    #: promisiune fără destinatar: cine apasă trebuie să vadă unde ajunge.
    email: str | None
    #: Numărul de WhatsApp, pentru butonul de pe rând. Conversația se deschide
    #: dintr-un clic, dar mesajul îl scrie omul.
    whatsapp_number: str | None


class RemindersOut(ApiModel):
    """Tot ce afișează ecranul, într-un singur răspuns."""

    #: Luna în lucru. Nulă când cabinetul nu are încă nicio lună începută — atunci
    #: nu există nici rânduri, nici ceva de trimis.
    reference_month: str | None
    deadline: date | None
    rows: list[ReminderRowOut]
    #: Câte ar pleca acum. Numărul de pe buton, ca să nu se apese în gol.
    due: int
    #: Dacă planificatorul are voie să trimită singur. Butonul funcționează și
    #: când este oprit: un om care apasă nu face automatizare.
    automatic_enabled: bool
    #: Dacă există prin ce trimite. Fals, ecranul spune ce lipsește în loc să
    #: lase pe cineva să apese un buton care nu poate reuși.
    mail_configured: bool
    #: Regulile, ca ecranul să le poată scrie fără să le rescrie.
    silence_days: int
    max_per_month: int


class SendReportOut(ApiModel):
    sent: int
    failed: int
    #: Câți nu erau de trimis. Nu este o eroare: este chiar restul listei.
    skipped: int


def _row_out(row: ReminderRow) -> ReminderRowOut:
    return ReminderRowOut(
        client_id=row.client_id,
        client_name=row.client_name,
        missing_count=row.missing_count,
        status=row.status,
        last_message_at=row.last_message_at,
        days_silent=row.days_silent,
        sent_count=row.sent_count,
        email=row.email,
        whatsapp_number=row.whatsapp_number,
    )


@router.get("", response_model=RemindersOut)
def list_reminders(session: DbSession, user: ReminderSender) -> RemindersOut:
    service = ReminderService(session, user.organization_id)
    reference_month = service.month()
    if reference_month is None:
        return RemindersOut(
            reference_month=None,
            deadline=None,
            rows=[],
            due=0,
            automatic_enabled=settings.client_reminders_enabled,
            mail_configured=settings.mail_is_configured,
            silence_days=SILENCE_DAYS,
            max_per_month=MAX_PER_MONTH,
        )

    rows = service.rows(reference_month, today=clock.today())
    return RemindersOut(
        reference_month=reference_month,
        deadline=rows[0].deadline if rows else None,
        rows=[_row_out(row) for row in rows],
        due=sum(1 for row in rows if row.is_due),
        automatic_enabled=settings.client_reminders_enabled,
        mail_configured=settings.mail_is_configured,
        silence_days=SILENCE_DAYS,
        max_per_month=MAX_PER_MONTH,
    )


@router.post("/send", response_model=SendReportOut)
def send_reminders(request: Request, session: DbSession, user: ReminderSender) -> SendReportOut:
    """Trimite acum tot ce este de trimis.

    **Aceleași reguli ca la ora planificatorului.** Butonul nu ocolește plafonul
    lunar și nu scrie cuiva căruia nu i s-a cerut niciodată: dacă apăsarea ar
    trimite altceva decât rulează automat, ecranul de deasupra ar deveni o
    previzualizare mincinoasă.

    Ce ocolește este doar comutatorul `CLIENT_REMINDERS_ENABLED`, care spune dacă
    aplicația scrie **singură**.
    """
    report = ReminderService(session, user.organization_id).send(
        build_email_sender(),
        today=clock.today(),
        actor=user,
        ip=client_ip(request),
    )
    return SendReportOut(sent=report.sent, failed=report.failed, skipped=report.skipped)
