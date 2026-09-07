"""Reminderele către clienți: singurul lucru pe care aplicația îl trimite singură.

**De ce testele astea sunt cele mai importante din modul.** Restul aplicației
greșește înăuntru: un raport strâmb se vede și se corectează. Aici greșeala pleacă
din cabinet, semnată cu numele cabinetului, către clientul lui — și nu se mai
poate retrage. Un reminder în plus nu produce o eroare; produce un client care
mută adresa contabilului în spam, și pe urmă nu mai citește nici ce scrie omul.

De aceea aproape toate testele de mai jos verifică **ce nu pleacă**. Fiecare
corespunde unei reguli din `app/services/reminders.py`, iar dacă o regulă cade,
testul spune în românește ce anume a pățit clientul.

Ordinea este a gravității:

1. **Nu se reamintește ce nu s-a cerut niciodată.** Un client care primește o
   reamintire pentru ceva ce nu i-a cerut nimeni nu înțelege ce se întâmplă.
2. **Nu se scrie de două ori în aceeași zi**, și nici mai mult de două ori pe lună.
3. **Nu se scrie celui care tocmai a trimis ceva.**
4. **Nu se scrie după termen**, unde fraza „ca să depunem la timp" ar fi falsă.
5. **Un mesaj care n-a plecat nu lasă urmă că a plecat** — altfel contorul lunar
   ar consuma o șansă pe care clientul n-a primit-o.
6. **Jurnalul spune cine a scris**, iar când a scris planificatorul nu numește un
   om care dormea la ora aceea.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config as core_config
from app.domain.enums import ReminderStatus
from app.domain.periods import filing_deadline
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client, Contact
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.reminder import ClientReminder
from app.models.upload_link import ClientUploadLink
from app.models.user import Role, User
from app.services.mail import EmailError, EmailMessage
from app.services.reminders import MAX_PER_MONTH, SILENCE_DAYS, ReminderService
from app.services.upload_links import hash_token
from tests.conftest import requires_db
from tests.test_periods_api import MONTH, PDF, add_document, login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

#: Termenul lunii de probă. Toate zilele de mai jos se raportează la el, ca
#: testele să nu depindă de data la care rulează.
DEADLINE = filing_deadline(MONTH, day=core_config.settings.filing_deadline_day)

#: O zi în plină lună de lucru: după ce a sosit primul document, înainte de termen.
WORKDAY = date(2026, 9, 3)


class Collecting:
    """Providerul de email, înlocuit cu unul care reține ce ar fi plecat."""

    name = "test"

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class Refusing:
    """Un server de mail care refuză. Nu o excepție de test: cazul obișnuit."""

    name = "test"

    def send(self, message: EmailMessage) -> None:
        raise EmailError("Serverul a refuzat adresa.")


@pytest.fixture
def gaps(
    db: Session,
    org: Organization,
    client_row: Client,
    types: dict[str, DocumentType],
    expectations: dict[str, ClientExpectation],
) -> None:
    """O lună începută și neterminată: o factură a sosit, restul lipsește."""
    add_document(db, org, client_row, types["FACTURA_INTRARE"])
    db.flush()


@pytest.fixture
def contact(db: Session, client_row: Client) -> Contact:
    row = Contact(
        client_id=client_row.id,
        full_name="Mihai Dobre",
        email="mihai@alfa.test",
        whatsapp_number="0722 123 456",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def service(db: Session, org: Organization) -> ReminderService:
    return ReminderService(db, org.id)


def asked(
    db: Session,
    org: Organization,
    client_row: Client,
    *,
    days_ago: int,
    reference_month: str = MONTH,
    used_days_ago: int | None = None,
) -> ClientUploadLink:
    """Cabinetul i-a cerut documentele acum atâtea zile, și mesajul a plecat.

    `used_days_ago` spune că omul a și trimis ceva pe drumul acela — diferența
    dintre „nu a răspuns" și „a răspuns, dar tot mai lipsește".
    """
    when = datetime.combine(WORKDAY, datetime.min.time(), tzinfo=UTC) - timedelta(days=days_ago)
    link = ClientUploadLink(
        organization_id=org.id,
        client_id=client_row.id,
        token_hash=hash_token(uuid.uuid4().hex),
        expires_at=datetime.now(UTC) + timedelta(days=45),
        reference_month=reference_month,
        notified_at=when,
        notified_to="mihai@alfa.test",
    )
    if used_days_ago is not None:
        link.upload_count = 1
        link.last_used_at = datetime.combine(
            WORKDAY, datetime.min.time(), tzinfo=UTC
        ) - timedelta(days=used_days_ago)
    db.add(link)
    db.flush()
    return link


def reminded(
    db: Session, org: Organization, client_row: Client, *, days_ago: int, count: int = 1
) -> None:
    """Aplicația i-a scris deja de atâtea ori luna asta."""
    when = datetime.combine(WORKDAY, datetime.min.time(), tzinfo=UTC) - timedelta(days=days_ago)
    for index in range(count):
        db.add(
            ClientReminder(
                organization_id=org.id,
                client_id=client_row.id,
                reference_month=MONTH,
                sent_at=when - timedelta(days=index * SILENCE_DAYS),
                sent_to="mihai@alfa.test",
            )
        )
    db.flush()


def only_row(service: ReminderService, *, today: date = WORKDAY):
    rows = service.rows(MONTH, today=today)
    assert len(rows) == 1, [row.client_name for row in rows]
    return rows[0]


# ── Ce nu pleacă ─────────────────────────────────────────────────────────────


class TestItDoesNotWriteWhenItShouldNot:
    def test_it_does_not_remind_what_it_never_asked(
        self, service: ReminderService, gaps: None, contact: Contact
    ) -> None:
        """Prima regulă. Reamintirea presupune o cerere înainte.

        Un client care primește direct o reamintire pentru ceva ce nu i s-a cerut
        niciodată nu are cum să înțeleagă despre ce este vorba — și are dreptate.
        """
        assert only_row(service).status is ReminderStatus.NOT_ASKED
        assert service.due(MONTH, today=WORKDAY) == []

    def test_it_waits_a_few_days_after_the_request(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """Documentele se strâng de la casierie, uneori din alt oraș."""
        asked(db, org, client_row, days_ago=SILENCE_DAYS - 1)

        row = only_row(service)
        assert row.status is ReminderStatus.WAITING
        assert row.days_silent == SILENCE_DAYS - 1

    def test_it_keeps_quiet_for_the_one_who_just_sent_something(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """A trimis ieri jumătate din documente: omul lucrează.

        Tăcerea se măsoară de la **ultimul nostru mesaj**, dar se rupe de orice
        semn de viață de la client. Un reminder aici l-ar anunța că nu ne uităm
        la ce face.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS + 3, used_days_ago=1)

        assert only_row(service).status is ReminderStatus.ANSWERED

    def test_it_stops_after_two_in_a_month(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """Al treilea mesaj nu aduce documente, aduce un filtru de spam."""
        asked(db, org, client_row, days_ago=20)
        reminded(db, org, client_row, days_ago=SILENCE_DAYS + 1, count=MAX_PER_MONTH)

        assert only_row(service).status is ReminderStatus.MAX_REACHED

    def test_it_does_not_write_after_the_deadline(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """După termen, fraza „ca să depunem la timp" ar fi o minciună.

        De aici încolo se sună. Un robot care scrie mai departe după termen este
        un robot pe care înveți să-l ignori — inclusiv luna următoare, când
        mesajul lui ar mai fi ajutat.
        """
        asked(db, org, client_row, days_ago=30)

        assert only_row(service, today=DEADLINE + timedelta(days=1)).status is (
            ReminderStatus.PAST_DEADLINE
        )
        # Chiar în ziua termenului încă se scrie: mai este timp.
        assert only_row(service, today=DEADLINE).status is ReminderStatus.DUE

    def test_it_says_when_there_is_nowhere_to_write(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
    ) -> None:
        """Fără contact cu email, rândul spune de ce — nu dispare din listă.

        Un client fără adresă nu devine contactabil peste trei zile. Arătat ca
        „mai așteptăm", s-ar fi descoperit abia la sfârșitul lunii, când nu mai
        era nimic de făcut.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS + 1)

        row = only_row(service)
        assert row.status is ReminderStatus.NO_EMAIL
        assert row.email is None


# ── Ce pleacă ────────────────────────────────────────────────────────────────


class TestItWritesWhenItShould:
    def test_after_the_silence_it_is_due(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        row = only_row(service)
        assert row.status is ReminderStatus.NOT_ASKED

        asked(db, org, client_row, days_ago=SILENCE_DAYS)

        row = only_row(service)
        assert row.status is ReminderStatus.DUE
        assert row.email == "mihai@alfa.test"
        # Numărul de pe rând este de tipuri, nu de bucăți: din trei așteptate a
        # sosit una, deci mai lipsesc două tipuri… nu, un tip întreg plus restul.
        assert row.missing_count >= 1

    def test_the_message_says_when_we_wrote_before(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """„Vă reamintim" o poate scrie oricine despre orice.

        Data spune verificabil de când așteptăm, iar clientul care crede că a
        trimis deja se poate duce să caute în ziua aceea.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS)
        sender = Collecting()

        service.send(sender, today=WORKDAY)

        assert len(sender.sent) == 1
        body = sender.sent[0].body
        first = (WORKDAY - timedelta(days=SILENCE_DAYS)).strftime("%d.%m.%Y")
        assert f"V-am scris pe {first}" in body
        # Și nu deschiderea primei cereri: două mesaje identice l-ar face pe
        # client să creadă că cel dintâi nu a plecat niciodată.
        assert "mai avem nevoie de următoarele documente" not in body

    def test_the_link_in_the_reminder_works(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """Testul care contează: clientul deschide linkul din reminder și trimite.

        Restul verifică forma mesajului. Ăsta verifică fondul — că al doilea
        mesaj îl duce la dosarul lui, la fel ca primul.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS)
        db.commit()
        sender = Collecting()
        ReminderService(db, org.id).send(sender, today=WORKDAY)
        db.commit()

        marker = f"{core_config.settings.public_base_url}/incarca/"
        line = next(row for row in sender.sent[0].body.splitlines() if row.startswith(marker))
        sent = api_storage.post(
            f"/api/v1/portal/{line[len(marker) :]}",
            files={"file": ("de-la-client.pdf", PDF, "application/pdf")},
        )

        assert sent.status_code == 201, sent.text
        document = db.scalars(
            select(Document).where(Document.original_filename == "de-la-client.pdf")
        ).one()
        assert document.client_id == client_row.id


# ── Urma ─────────────────────────────────────────────────────────────────────


class TestTheTrace:
    def test_a_sent_reminder_silences_the_next_day(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """Trimis azi, mâine nu se mai trimite. Asta face cronul repetabil.

        Ruta de cron nu are idempotență și nu pretinde că are; ce o face
        inofensivă chemată de două ori este chiar regula zilelor de tăcere.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS)
        service.send(Collecting(), today=WORKDAY)

        row = only_row(service, today=WORKDAY + timedelta(days=1))
        assert row.status is ReminderStatus.WAITING
        assert row.sent_count == 1

    def test_a_refused_message_leaves_no_trace_that_it_left(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """Un server de mail căzut nu are voie să consume o șansă din două.

        Scris invers — rândul înainte de confirmare — clientul ar fi primit cu un
        mesaj mai puțin într-o lună în care n-a primit niciunul, iar nimeni n-ar
        fi aflat de ce.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS)

        report = service.send(Refusing(), today=WORKDAY)

        assert report.sent == 0
        assert report.failed == 1
        assert db.scalars(select(ClientReminder)).all() == []
        assert only_row(service).status is ReminderStatus.DUE

    def test_the_journal_says_who_wrote_and_never_what(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        asked(db, org, client_row, days_ago=SILENCE_DAYS)

        service.send(Collecting(), today=WORKDAY, actor=admin)

        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "CLIENT_REMINDER_SENT")
        ).one()
        assert entry.user_id == admin.id
        assert entry.detail is not None
        assert client_row.name in entry.detail
        assert "mihai@alfa.test" in entry.detail
        # Cui și când, niciodată ce scria în mesaj (§33, §52).
        assert "V-am scris" not in entry.detail

    def test_when_the_scheduler_writes_it_does_not_borrow_a_name(
        self,
        service: ReminderService,
        db: Session,
        org: Organization,
        client_row: Client,
        gaps: None,
        contact: Contact,
    ) -> None:
        """„Cabinetul a scris" și „aplicația a scris" nu sunt același lucru.

        Cine citește auditul peste o lună trebuie să le poată deosebi — mai ales
        când clientul întreabă cine i-a trimis mesajul de la ora șapte dimineața.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS)

        service.send(Collecting(), today=WORKDAY)

        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "CLIENT_REMINDER_SENT")
        ).one()
        assert entry.user_id is None
        assert entry.user_name == "Aplicația"
        assert db.scalars(select(ClientReminder)).one().sent_by_id is None


# ── Ecranul ──────────────────────────────────────────────────────────────────


def current_month() -> str:
    """Luna de azi. Testele de rută nu au voie să depindă de calendar.

    Cu luna de probă (august 2026), aceleași teste ar fi început să pice pe 26
    septembrie 2026 — regula „nu după termen" e adevărată, dar picarea n-ar fi
    spus nimic despre cod.
    """
    today = datetime.now(UTC).date()
    return f"{today.year:04d}-{today.month:02d}"


@pytest.fixture
def gaps_now(
    db: Session,
    org: Organization,
    client_row: Client,
    types: dict[str, DocumentType],
    expectations: dict[str, ClientExpectation],
) -> str:
    month = current_month()
    add_document(db, org, client_row, types["FACTURA_INTRARE"], reference_month=month)
    db.flush()
    return month


class TestTheScreen:
    def test_it_lists_everyone_with_a_reason(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        gaps_now: str,
        contact: Contact,
    ) -> None:
        """Întrebarea contabilului nu este „cine primește", ci „ăsta de ce nu"."""
        db.commit()
        login(api, admin.email)

        body = api.get("/api/v1/reminders").json()

        assert body["referenceMonth"] == gaps_now
        assert body["due"] == 0
        assert [row["status"] for row in body["rows"]] == ["NOT_ASKED"]
        assert body["rows"][0]["whatsappNumber"] == "0722 123 456"
        assert body["silenceDays"] == SILENCE_DAYS
        assert body["maxPerMonth"] == MAX_PER_MONTH

    def test_reading_the_screen_sends_nothing_and_opens_nothing(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        gaps_now: str,
        contact: Contact,
    ) -> None:
        """Efectele nu se produc ca efect secundar al unei citiri.

        Ecranul are un buton tocmai ca deschiderea lui să nu trimită nimic. Fără
        testul ăsta, o singură linie mutată în `list_reminders` ar fi făcut ca
        fiecare reîncărcare de pagină să deschidă un drum public per client.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS, reference_month=gaps_now)
        before = len(db.scalars(select(ClientUploadLink)).all())
        db.commit()
        login(api, admin.email)

        api.get("/api/v1/reminders")

        assert len(db.scalars(select(ClientUploadLink)).all()) == before
        assert db.scalars(select(ClientReminder)).all() == []

    def test_a_visitor_may_not_see_the_list(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        gaps_now: str,
    ) -> None:
        """Lista poartă adresele clienților și butonul scrie în numele cabinetului.

        Ascunderea butonului în interfață nu este o măsură de securitate (§32):
        refuzul îl dă serverul, pe amândouă rutele.
        """
        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        db.commit()
        login(api, viewer.email)

        assert api.get("/api/v1/reminders").status_code == 403
        assert api.post("/api/v1/reminders/send").status_code == 403


class TestTheSwitchAndTheButton:
    def test_the_switch_stops_the_clock_not_the_button(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        gaps_now: str,
        contact: Contact,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Un om care apasă nu face automatizare, face muncă.

        `CLIENT_REMINDERS_ENABLED` se referă strict la ce pleacă **singur**. Dacă
        ar opri și butonul, un cabinet care nu vrea mesaje la ora șapte dimineața
        ar rămâne fără mijlocul de a trimite când vrea el.
        """
        asked(db, org, client_row, days_ago=SILENCE_DAYS, reference_month=gaps_now)
        db.commit()
        monkeypatch.setattr(core_config.settings, "client_reminders_enabled", False)
        sender = Collecting()
        monkeypatch.setattr("app.api.v1.reminders.build_email_sender", lambda: sender)
        login(api, admin.email)

        from app.services.reminders import run_reminders

        assert run_reminders(sender, today=datetime.now(UTC).date()).sent == 0
        assert sender.sent == []

        body = api.post("/api/v1/reminders/send").json()

        assert body["sent"] == 1
        assert len(sender.sent) == 1

    def test_the_button_obeys_the_same_rules_as_the_clock(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        gaps_now: str,
        contact: Contact,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Altfel ecranul de deasupra ar fi o previzualizare mincinoasă.

        Clientul de aici nu a fost întrebat niciodată, deci nici butonul nu-i
        scrie: apăsat, raportul spune că nu era nimic de trimis.
        """
        db.commit()
        sender = Collecting()
        monkeypatch.setattr("app.api.v1.reminders.build_email_sender", lambda: sender)
        login(api, admin.email)

        body = api.post("/api/v1/reminders/send").json()

        assert body["sent"] == 0
        assert body["skipped"] == 1
        assert sender.sent == []
