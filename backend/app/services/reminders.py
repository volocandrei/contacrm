"""Reminderele către clienți: ce pleacă singur, și mai ales ce nu.

**Decizia din spate.** Până acum aplicația nu scria niciodată unui client fără ca
un om să apese. Nu era o limitare tehnică — datele existau de luni de zile — ci o
hotărâre care nu fusese luată: un mesaj trimis automat, în numele cabinetului,
clientului lui, schimbă o relație, iar dacă textul sau momentul sunt greșite
cabinetul află de la client. Cabinetul a hotărât: are voie.

Din clipa aceea întrebarea nu mai este *dacă*, ci **cât de des și cui**, iar
răspunsul la asta este tot codul de mai jos. Un robot care scrie prea des nu
aduce documentele mai repede: aduce un client care mută adresa cabinetului în
spam, și pe urmă nu mai citește nici mesajele scrise de om.

**Cele șapte răspunsuri.** Serviciul nu întoarce „cine primește", ci starea
fiecărui client căruia îi lipsește ceva, cu motivul. Ecranul poate atunci
răspunde la întrebarea pe care o pune contabilul — „bine, dar pe ăsta de ce nu-l
anunță?" — fără ca cineva să citească fișierul acesta.

**Regulile, și de ce fiecare există:**

- *Nu reamintim ce n-am cerut.* Primul mesaj este o solicitare și pleacă la
  apăsarea unui om, din „Documente lipsă". Un client care primește direct o
  reamintire pentru ceva ce nu i s-a cerut niciodată nu înțelege ce se întâmplă,
  și are dreptate.
- *Nu mai des de câteva zile.* Documentele se strâng de la contabilul intern, de
  la casierie, uneori din alt oraș. Un mesaj pe zi nu grăbește pe nimeni.
- *Nu celui care tocmai a trimis ceva.* A trimis trei din cinci facturi acum două
  ore: omul lucrează. Reminderul l-ar anunța că nu ne uităm la ce face.
- *Cel mult două pe lună.* Al treilea nu aduce documente; aduce un filtru.
- *Nu după termen.* Fraza „ca declarațiile să poată fi depuse la timp" devine
  falsă, iar un robot care scrie mai departe după termen este un robot pe care
  înveți să-l ignori. După termen se sună.

**Comutatorul oprește planificatorul, nu butonul.** `CLIENT_REMINDERS_ENABLED`
decide dacă mesajele pleacă *singure*. Un om care apasă „Trimite acum" nu face
automatizare, face muncă — și nu are de ce să fie oprit de un comutator despre
programul de dimineață.

*NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE:* fără `SMTP_*`, providerul de email
este cel care nu trimite nimic, iar `send` întoarce zero.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.locks import try_lock_organization
from app.core.logging import get_logger
from app.domain.enums import ReminderStatus
from app.domain.periods import ChecklistEntry, filing_deadline
from app.models.client import Client, Contact
from app.models.organization import Organization
from app.models.reminder import CHANNEL_EMAIL, ClientReminder
from app.models.user import User
from app.services.audit import AuditService
from app.services.document_request import (
    AUTOMATIC_ACTOR,
    DocumentRequestService,
    month_in_words,
)
from app.services.mail import EmailError, EmailMessage, EmailSender
from app.services.period_service import PeriodService
from app.services.upload_links import RequestTrace, UploadLinkService

logger = get_logger(__name__)

#: După câte zile de tăcere se reamintește. Patru, nu una: documentele se strâng
#: de la contabilul intern, de la casierie, uneori din alt oraș.
SILENCE_DAYS = 4

#: Câte remindere trimite aplicația unui client într-o lună. Al treilea nu aduce
#: documente mai repede, aduce un client care filtrează adresa cabinetului.
MAX_PER_MONTH = 2


@dataclass(frozen=True, slots=True)
class ReminderRow:
    """Un client căruia îi lipsește ceva, și ce se întâmplă azi cu el."""

    client_id: uuid.UUID
    client_name: str
    reference_month: str
    #: Câte tipuri de document mai lipsesc. Nu bucăți: „două tipuri" este ce se
    #: poate spune pe un rând de tabel fără să mintă.
    missing_count: int
    status: ReminderStatus
    #: Ultimul mesaj plecat de la cabinet — solicitarea sau un reminder.
    last_message_at: datetime | None
    #: De câte zile așteptăm răspuns. Nulă cât timp nu i s-a scris niciodată.
    days_silent: int | None
    #: Câte remindere au plecat deja luna asta.
    sent_count: int
    email: str | None
    #: Pentru butonul de WhatsApp de pe rând: conversația se deschide dintr-un
    #: clic, dar mesajul îl scrie omul. Aplicația nu trimite singură pe WhatsApp.
    whatsapp_number: str | None
    deadline: date

    @property
    def is_due(self) -> bool:
        return self.status is ReminderStatus.DUE


@dataclass(frozen=True, slots=True)
class SendReport:
    """Ce a plecat dintr-o rulare. Se citește dintr-un log, deci e scurt."""

    sent: int
    failed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class _Reach:
    """Cum se ajunge la un client: prima adresă și primul număr de pe fișă."""

    email: str | None
    whatsapp: str | None


class ReminderService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id
        self.audit = AuditService(session)
        self.links = UploadLinkService(session)

    # ── Citire ──────────────────────────────────────────────────────────────

    def month(self) -> str | None:
        """Luna în lucru — aceeași ca panoul și ca rezumatul zilnic.

        Nu luna din calendar: pe 3 septembrie cabinetul urmărește documentele lui
        august, iar un reminder despre septembrie ar cere documente care încă nu
        s-au emis.
        """
        return PeriodService(self.session).latest_active_month(self.organization_id)

    def rows(self, reference_month: str, *, today: date) -> list[ReminderRow]:
        """Toți clienții cărora le lipsește ceva, cu motivul pentru fiecare."""
        return [row for row, _gaps in self._rows_with_gaps(reference_month, today=today)]

    def _rows_with_gaps(
        self, reference_month: str, *, today: date
    ) -> list[tuple[ReminderRow, list[ChecklistEntry]]]:
        """Rândurile, împreună cu ce anume lipsește fiecăruia.

        Aceeași sursă ca raportul „Documente lipsă" și ca solicitarea: dacă
        reminderul ar avea interogarea lui, într-o zi ar scrie unui client care pe
        ecran apare în regulă — iar diferența s-ar vedea abia din răspunsul lui.

        **Golurile ies odată cu rândurile**, nu se cer a doua oară la trimitere.
        `missing()` se uită de fiecare dată la toți clienții cabinetului: cerut
        per destinatar, o rulare de douăzeci de remindere ar fi trecut de douăzeci
        de ori peste două sute de clienți, sub timpul maxim al unei bătăi de cron.
        Iar două citiri separate ar fi putut, în principiu, să nu mai conțină
        aceiași clienți.
        """
        entries = PeriodService(self.session).missing(self.organization_id, reference_month)
        if not entries:
            return []

        traces = self.links.requests_for(self.organization_id, reference_month)
        counts = self._reminder_counts(reference_month)
        latest = self._latest_reminders(reference_month)
        reach = self._reach([view.client_id for view, _ in entries])
        deadline = filing_deadline(reference_month, day=settings.filing_deadline_day)

        rows: list[tuple[ReminderRow, list[ChecklistEntry]]] = []
        for view, gaps in entries:
            trace = traces.get(view.client_id)
            contact = reach.get(view.client_id, _Reach(None, None))
            last_message = _latest_of(
                trace.notified_at if trace else None, latest.get(view.client_id)
            )
            row = ReminderRow(
                client_id=view.client_id,
                client_name=view.client_name,
                reference_month=reference_month,
                missing_count=len(gaps),
                status=self._status(
                    trace=trace,
                    last_message=last_message,
                    sent_count=counts.get(view.client_id, 0),
                    email=contact.email,
                    deadline=deadline,
                    today=today,
                ),
                last_message_at=last_message,
                days_silent=((today - last_message.date()).days if last_message else None),
                sent_count=counts.get(view.client_id, 0),
                email=contact.email,
                whatsapp_number=contact.whatsapp,
                deadline=deadline,
            )
            rows.append((row, gaps))
        return rows

    def due(self, reference_month: str, *, today: date) -> list[ReminderRow]:
        return [row for row in self.rows(reference_month, today=today) if row.is_due]

    def _status(
        self,
        *,
        trace: RequestTrace | None,
        last_message: datetime | None,
        sent_count: int,
        email: str | None,
        deadline: date,
        today: date,
    ) -> ReminderStatus:
        """Un singur motiv per rând, în ordinea în care contează.

        Ordinea nu este arbitrară: se răspunde întâi la ce **nu se schimbă prin
        așteptare**. Un client fără adresă de email nu devine contactabil peste
        trei zile, deci a-l arăta ca „mai așteptăm" ar fi o minciună care se
        descoperă la sfârșitul lunii.
        """
        if last_message is None:
            # Nici solicitare trimisă, nici reminder: primul mesaj este o cerere,
            # nu o reamintire, și pleacă la apăsarea unui om.
            return ReminderStatus.NOT_ASKED
        if email is None:
            return ReminderStatus.NO_EMAIL
        if today > deadline:
            return ReminderStatus.PAST_DEADLINE
        if sent_count >= MAX_PER_MONTH:
            return ReminderStatus.MAX_REACHED
        if (
            trace is not None
            and trace.last_used_at is not None
            and trace.last_used_at > last_message
        ):
            return ReminderStatus.ANSWERED
        if (today - last_message.date()).days < SILENCE_DAYS:
            return ReminderStatus.WAITING
        return ReminderStatus.DUE

    # ── Trimitere ───────────────────────────────────────────────────────────

    def send(
        self,
        sender: EmailSender,
        *,
        today: date,
        actor: User | None = None,
        ip: str | None = None,
    ) -> SendReport:
        """Trimite tot ce este de trimis azi.

        `actor` este omul care a apăsat, sau nimeni când bate planificatorul.
        Diferența ajunge în jurnal: „cabinetul a scris" și „aplicația a scris" nu
        sunt același lucru, iar cine citește auditul peste o lună trebuie să le
        poată deosebi.

        Un client care eșuează nu-i oprește pe ceilalți: un server de mail care
        refuză o adresă nu este un motiv ca restul să rămână neanunțați.
        """
        # **Un singur trimitator odata, per cabinet.** Tot ce urmeaza citeste din
        # baza ce s-a trimis pana acum — cererea, ultimul reminder, contorul lunii
        # — deci tot ce urmeaza presupune ca cine a scris inaintea noastra a
        # apucat sa comita. Doua batai suprapuse rup presupunerea: amandoua citesc
        # „nu s-a trimis nimic", amandoua hotarasc ca este de trimis, iar clientul
        # primeste acelasi mesaj de doua ori. Masurat: patru batai deodata, patru
        # mesaje.
        #
        # Se intampla fara nimic exotic — un cron care bate peste o rulare mai
        # lunga decat crede el, un „reincearca" apasat, doua procese de API — iar
        # paguba nu apare in nicio consola: apare la client, care muta adresa
        # cabinetului in spam.
        #
        # Nu se asteapta. Cine pierde intoarce zero, si asta este raspunsul corect:
        # altcineva trimite chiar acum. Incuietoarea se elibereaza la commit, adica
        # exact dupa ce randurile devin vizibile pentru urmatorul.
        if not try_lock_organization(self.session, self.organization_id, "reminders"):
            logger.info("reminders_already_running", organization_id=str(self.organization_id))
            return SendReport(sent=0, failed=0, skipped=0)

        reference_month = self.month()
        if reference_month is None:
            return SendReport(sent=0, failed=0, skipped=0)

        rows = self._rows_with_gaps(reference_month, today=today)
        due = [(row, gaps) for row, gaps in rows if row.is_due]

        sent = 0
        failed = 0
        for row, gaps in due:
            if self._send_one(row, sender=sender, actor=actor, ip=ip, missing=gaps):
                sent += 1
            else:
                failed += 1

        logger.info(
            "reminders_sent",
            organization_id=str(self.organization_id),
            reference_month=reference_month,
            sent=sent,
            failed=failed,
            automatic=actor is None,
        )
        return SendReport(sent=sent, failed=failed, skipped=len(rows) - len(due))

    def _send_one(
        self,
        row: ReminderRow,
        *,
        sender: EmailSender,
        actor: User | None,
        ip: str | None,
        missing: Sequence[ChecklistEntry],
    ) -> bool:
        """Un mesaj, un rând de urmă. Întoarce dacă a plecat.

        **Se scrie „trimis" abia după ce providerul a confirmat.** Invers, un
        server de mail căzut ar fi lăsat în bază un reminder care n-a plecat
        niciodată — iar contorul lunar l-ar fi numărat, deci clientul ar fi primit
        cu un mesaj mai puțin fără ca nimeni să afle de ce.
        """
        if row.email is None:
            # `_status` nu dă DUE fără adresă; dacă totuși ajunge aici, tăcerea ar
            # fi mai rea decât rândul din log.
            logger.error("reminder_without_address", client_id=str(row.client_id))
            return False

        composed = DocumentRequestService(self.session, self.organization_id).compose(
            row.client_id,
            row.reference_month,
            actor=actor,
            ip=ip,
            previous_sent_on=row.last_message_at.date() if row.last_message_at else None,
            missing=missing,
        )
        subject = f"Vă reamintim: documentele pentru {month_in_words(row.reference_month)}"
        try:
            sender.send(EmailMessage(to=row.email, subject=subject, body=composed.message))
        except EmailError:
            # Adresa, nu conținutul (§52). Restul clienților primesc oricum.
            logger.error("reminder_send_failed", to=row.email)
            return False

        self.links.mark_notified(composed.link_id, to=row.email)
        self.session.add(
            ClientReminder(
                organization_id=self.organization_id,
                client_id=row.client_id,
                reference_month=row.reference_month,
                sent_at=datetime.now(UTC),
                sent_to=row.email,
                channel=CHANNEL_EMAIL,
                link_id=composed.link_id,
                sent_by_id=actor.id if actor else None,
            )
        )
        self.audit.record(
            organization_id=self.organization_id,
            action="CLIENT_REMINDER_SENT",
            entity_type="Client",
            entity_id=str(row.client_id),
            user_id=actor.id if actor else None,
            user_name=actor.full_name if actor else AUTOMATIC_ACTOR,
            # Cui și pentru ce lună. Nu textul: jurnalul nu ține conținut (§33).
            detail=f"{row.client_name} · {row.email} · {row.reference_month}",
            ip=ip,
        )
        self.session.flush()
        return True

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _reminder_counts(self, reference_month: str) -> dict[uuid.UUID, int]:
        rows = self.session.execute(
            select(ClientReminder.client_id, func.count())
            .where(
                ClientReminder.organization_id == self.organization_id,
                ClientReminder.reference_month == reference_month,
            )
            .group_by(ClientReminder.client_id)
        ).all()
        return {client_id: count for client_id, count in rows}

    def _latest_reminders(self, reference_month: str) -> dict[uuid.UUID, datetime]:
        rows = self.session.execute(
            select(ClientReminder.client_id, func.max(ClientReminder.sent_at))
            .where(
                ClientReminder.organization_id == self.organization_id,
                ClientReminder.reference_month == reference_month,
            )
            .group_by(ClientReminder.client_id)
        ).all()
        return {client_id: sent_at for client_id, sent_at in rows}

    def _reach(self, client_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, _Reach]:
        """Prima adresă și primul număr, în ordinea de pe fișă.

        Aceeași alegere ca la solicitare — primul contact care are ce trebuie, nu
        „cel principal": modelul nu are noțiunea, iar a inventa una aici ar
        însemna că ecranul nu poate arăta dinainte cui pleacă mesajul.
        """
        if not client_ids:
            return {}
        rows = self.session.execute(
            select(Contact.client_id, Contact.email, Contact.whatsapp_number)
            .join(Client, Client.id == Contact.client_id)
            .where(
                Client.organization_id == self.organization_id,
                Contact.client_id.in_(client_ids),
                Contact.deleted_at.is_(None),
                Contact.is_active.is_(True),
            )
            .order_by(Contact.created_at)
        ).all()

        reach: dict[uuid.UUID, _Reach] = {}
        for client_id, email, whatsapp in rows:
            current = reach.get(client_id, _Reach(None, None))
            reach[client_id] = _Reach(
                email=current.email or (email or None),
                whatsapp=current.whatsapp or (whatsapp or None),
            )
        return reach


def _latest_of(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def run_reminders(sender: EmailSender, *, today: date | None = None) -> SendReport:
    """Bătaia planificatorului, peste toate cabinetele.

    Oprită din `CLIENT_REMINDERS_ENABLED`: comutatorul se referă strict la ce
    pleacă **singur**. Butonul din ecran rămâne al omului.
    """
    from app.core.db import session_scope

    if not settings.client_reminders_enabled:
        return SendReport(sent=0, failed=0, skipped=0)

    when = today or clock.today()
    sent = failed = skipped = 0
    with session_scope() as session:
        for organization_id in session.scalars(select(Organization.id)):
            report = ReminderService(session, organization_id).send(sender, today=when)
            sent += report.sent
            failed += report.failed
            skipped += report.skipped
    return SendReport(sent=sent, failed=failed, skipped=skipped)


__all__ = [
    "MAX_PER_MONTH",
    "SILENCE_DAYS",
    "ReminderRow",
    "ReminderService",
    "SendReport",
    "run_reminders",
]
