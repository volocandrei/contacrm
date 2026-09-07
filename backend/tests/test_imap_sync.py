"""Preluarea documentelor dintr-o cutie poștală obișnuită.

**Golul pe care îl umple.** Preluarea din email exista de la M10, dar numai prin
Microsoft Graph — adică numai pentru cabinetele de pe Microsoft 365. În România,
cabinetul mic are cutia la Gmail, la Yahoo sau la găzduirea unde îi stă și
site-ul. Pentru toate acelea, „documentele intră singure din email" era o
propoziție adevărată despre alt cabinet.

**Ce apără testele, în ordinea gravității:**

1. **Nimic nu intră de două ori.** O cutie se citește la fiecare bătaie de cron;
   dacă a doua citire ar produce încă un document, arhiva s-ar dubla peste noapte
   și nimeni n-ar putea spune care exemplar este cel bun.
2. **Nimic nu se pierde când serverul reatribuie UID-urile.** O restaurare de
   cutie schimbă `UIDVALIDITY`, iar continuarea de la ultimul UID ar sări peste
   tot ce a venit între timp — tăcut, ceea ce e cel mai rău fel.
3. **Clientul vine din adresa expeditorului**, iar o adresă necunoscută nu
   oprește nimic: documentul intră neatribuit și așteaptă un om.
4. **Logo-ul din semnătură nu este document.**
5. **O eroare se vede.** O parolă schimbată oprește preluarea; fără urmă pe
   ecran, documentele pur și simplu nu mai vin și nimeni nu află de ce.
6. **Parola nu iese niciodată** prin API și nu ajunge în jurnal (§73).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt, encryption_available
from app.domain.enums import DocumentSource
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client, Contact
from app.models.document import Document, DocumentIntake
from app.models.imap import ImapMailbox
from app.models.organization import Organization
from app.models.user import Role, User
from app.services.imap.base import ImapAttachment
from app.services.imap.sync import ImapSyncService
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db
from tests.imap_fake import LOGO_BYTES, PDF_BYTES, FakeImapClient, message
from tests.test_periods_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

PAROLA = "parola-de-aplicatie"


@pytest.fixture
def encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fără cheie de criptare nu se poate stoca nicio parolă — deci nici testa."""
    if not encryption_available():
        pytest.skip("DRIVE_TOKEN_KEY nu este configurată în mediul de test")


@pytest.fixture
def mailbox(db: Session, org: Organization, encryption: None) -> ImapMailbox:
    row = ImapMailbox(
        organization_id=org.id,
        host="imap.exemplu.ro",
        port=993,
        username="contabil@cabinet.test",
        password=encrypt(PAROLA),
        folder="INBOX",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def contact(db: Session, client_row: Client) -> Contact:
    row = Contact(client_id=client_row.id, full_name="Mihai Dobre", email="contact@alfa.test")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


def sync(db: Session, storage: LocalStorageProvider, client: FakeImapClient, mailbox: ImapMailbox):
    return ImapSyncService(db, storage, client).sync_mailbox(mailbox)


def documents(db: Session, org: Organization) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == org.id, Document.source == DocumentSource.EMAIL)
        )
        or 0
    )


# ── Ce intră ─────────────────────────────────────────────────────────────────


class TestItBringsDocumentsIn:
    def test_an_attachment_becomes_a_document_of_the_right_client(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        client_row: Client,
        contact: Contact,
    ) -> None:
        """Clientul îl dă expeditorul: în cutie intră toți clienții deodată."""
        client = FakeImapClient(messages=[message(uid=10)])

        outcome = sync(db, storage, client, mailbox)

        assert outcome.ingested == 1
        document = db.scalars(select(Document).where(Document.source == DocumentSource.EMAIL)).one()
        assert document.client_id == client_row.id
        assert document.original_filename == "factura.pdf"

    def test_an_unknown_sender_still_gets_in(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
    ) -> None:
        """Mai bine să ajungă la un om decât să nu intre deloc.

        Neatribuit se vede pe ecranul „Neatribuite" și așteaptă. Refuzat, nimeni
        n-ar ști vreodată că documentul a venit.
        """
        client = FakeImapClient(messages=[message(uid=4, sender="nimeni@necunoscut.test")])

        outcome = sync(db, storage, client, mailbox)

        assert outcome.ingested == 1
        assert db.scalars(select(Document)).one().client_id is None

    def test_it_remembers_where_it_stopped(
        self, db: Session, storage: LocalStorageProvider, mailbox: ImapMailbox
    ) -> None:
        """Fără UID-ul memorat, fiecare bătaie ar reciti toată cutia."""
        client = FakeImapClient(messages=[message(uid=7)])

        sync(db, storage, client, mailbox)

        assert mailbox.last_uid == 7
        assert mailbox.uid_validity == client.uid_validity
        assert mailbox.last_error is None


# ── Ce nu intră de două ori ──────────────────────────────────────────────────


class TestItDoesNotDuplicate:
    def test_a_second_pass_over_the_same_mailbox_brings_nothing(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        contact: Contact,
    ) -> None:
        """Cutia se citește la fiecare bătaie de cron. A doua oară nu mai e nimic."""
        client = FakeImapClient(messages=[message(uid=10)])
        sync(db, storage, client, mailbox)

        second = sync(db, storage, client, mailbox)

        assert second.ingested == 0
        assert documents(db, org) == 1

    def test_the_next_pass_continues_from_where_it_stopped(
        self,
        db: Session,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        contact: Contact,
    ) -> None:
        """A doua bătaie cere mesajele **de după** ultimul UID, nu tot dosarul.

        Fără asta nimic nu s-ar dubla — idempotența ar prinde totul — dar o cutie
        cu trei mii de mesaje n-ar avansa niciodată: fiecare bătaie ar reciti
        primele cincisprezece și s-ar opri acolo, la nesfârșit. Cel mai scump fel
        de defect: nu dă nicio eroare, doar nu aduce nimic.
        """
        client = FakeImapClient(messages=[message(uid=42)])
        sync(db, storage, client, mailbox)

        sync(db, storage, client, mailbox)

        assert client.last_since_uid == 42

    def test_a_reassigned_uid_does_not_lose_the_mail_that_came_meanwhile(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        contact: Contact,
    ) -> None:
        """O restaurare de cutie schimbă `UIDVALIDITY` și numerele reîncep.

        Continuarea de la ultimul UID ar fi sărit peste tot ce a venit între timp,
        fără nicio eroare. Aici dosarul se reia de la început, iar mesajele deja
        preluate nu se dublează: cheia este `Message-ID`, nu UID-ul.
        """
        vechi = "<deja-preluat@alfa.test>"
        client = FakeImapClient(messages=[message(uid=50, message_id=vechi)])
        sync(db, storage, client, mailbox)
        assert mailbox.last_uid == 50
        assert documents(db, org) == 1

        # Serverul reatribuie: **același** mesaj primește UID 1 — un mesaj fizic
        # își păstrează `Message-ID`-ul, oricâte UID-uri ar primi — iar unul nou
        # primește UID 2.
        client.uid_validity = 2000
        client.messages = [
            message(uid=1, message_id=vechi),
            message(uid=2, message_id="<nou@alfa.test>"),
        ]

        outcome = sync(db, storage, client, mailbox)

        # S-a reluat de la zero, nu de la 50 — altfel n-ar fi văzut nimic.
        assert client.last_since_uid == 0
        assert outcome.ingested == 1, "doar mesajul nou trebuia luat"
        assert outcome.skipped == 1, "cel deja preluat trebuia sărit"
        assert documents(db, org) == 2
        assert mailbox.uid_validity == 2000

    def test_the_signature_logo_is_not_a_document(
        self, db: Session, org: Organization, storage: LocalStorageProvider, mailbox: ImapMailbox
    ) -> None:
        """Altfel fiecare email ar produce trei „documente" de respins manual.

        După a doua zi, nimeni nu le-ar mai respinge — ar închide ecranul.
        """
        client = FakeImapClient(
            messages=[
                message(
                    uid=3,
                    attachments=(
                        ImapAttachment(index=1, name="logo.png", content=LOGO_BYTES),
                        ImapAttachment(
                            index=2, name="banner.png", content=PDF_BYTES, is_inline=True
                        ),
                    ),
                )
            ]
        )

        outcome = sync(db, storage, client, mailbox)

        assert outcome.ingested == 0
        assert outcome.skipped == 2
        assert documents(db, org) == 0


# ── Ce se vede când nu merge ─────────────────────────────────────────────────


class TestItSaysWhenItBreaks:
    def test_a_refused_password_is_written_on_the_mailbox(
        self, db: Session, storage: LocalStorageProvider, mailbox: ImapMailbox
    ) -> None:
        """O parolă schimbată oprește preluarea. Fără urmă, nimeni nu află de ce."""
        client = FakeImapClient(auth_fails=True)

        outcome = sync(db, storage, client, mailbox)

        assert outcome.error
        assert mailbox.last_error
        # Și nu avansează nimic: mesajele trebuie recitite după ce se repară.
        assert mailbox.last_uid == 0

    def test_an_error_clears_after_a_good_pass(
        self, db: Session, storage: LocalStorageProvider, mailbox: ImapMailbox
    ) -> None:
        """Altfel un ecran ar rămâne roșu peste o problemă rezolvată acum o lună."""
        mailbox.last_error = "ceva vechi"
        client = FakeImapClient(messages=[message(uid=2)])

        sync(db, storage, client, mailbox)

        assert mailbox.last_error is None


# ── Parola ───────────────────────────────────────────────────────────────────


class TestThePassword:
    def test_it_never_leaves_through_the_api(
        self, api: TestClient, db: Session, admin: User, mailbox: ImapMailbox
    ) -> None:
        """Nici întreagă, nici trunchiată, nici ca „****" (§73)."""
        db.commit()
        login(api, admin.email)

        body = api.get("/api/v1/integrations/imap").text

        assert PAROLA not in body
        assert "password" not in body

    def test_it_is_not_stored_in_clear(self, db: Session, mailbox: ImapMailbox) -> None:
        assert mailbox.password != PAROLA

    def test_the_journal_says_which_mailbox_never_the_password(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        encryption: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db.commit()
        fake = FakeImapClient()
        from app.services.imap.deps import get_imap_client

        api.app.dependency_overrides[get_imap_client] = lambda: fake  # type: ignore[attr-defined]
        login(api, admin.email)

        answer = api.post(
            "/api/v1/integrations/imap",
            json={
                "host": "imap.exemplu.ro",
                "username": "cutie@cabinet.test",
                "password": PAROLA,
                "folder": "INBOX",
            },
        )

        assert answer.status_code == 201, answer.text
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "IMAP_MAILBOX_ADDED")).one()
        assert entry.detail is not None
        assert "cutie@cabinet.test" in entry.detail
        assert PAROLA not in entry.detail
        api.app.dependency_overrides.pop(get_imap_client, None)  # type: ignore[attr-defined]


# ── Ecranul ──────────────────────────────────────────────────────────────────


class TestAddingAMailbox:
    def test_a_wrong_password_is_refused_at_save_not_discovered_later(
        self, api: TestClient, db: Session, org: Organization, admin: User, encryption: None
    ) -> None:
        """O parolă greșită salvată tăcut nu se vede nicăieri.

        Documentele pur și simplu nu vin, iar cabinetul află peste o săptămână,
        când caută facturi care nu există. Conectarea se încearcă acum, cu omul
        în fața ecranului.
        """
        db.commit()
        from app.services.imap.deps import get_imap_client

        api.app.dependency_overrides[get_imap_client] = lambda: FakeImapClient(auth_fails=True)  # type: ignore[attr-defined]
        login(api, admin.email)

        answer = api.post(
            "/api/v1/integrations/imap",
            json={"host": "imap.exemplu.ro", "username": "x@y.test", "password": "gresita"},
        )

        assert answer.status_code == 422
        # Și nu a rămas nimic în bază.
        assert db.scalars(select(ImapMailbox)).all() == []
        api.app.dependency_overrides.pop(get_imap_client, None)  # type: ignore[attr-defined]

    def test_only_the_administrator_may_add_one(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Cutia poștală a cabinetului este configurare, nu muncă de zi cu zi."""
        accountant = make_user(
            db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT
        )
        db.commit()
        login(api, accountant.email)

        assert api.get("/api/v1/integrations/imap").status_code == 403

    def test_removing_it_keeps_the_documents(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        contact: Contact,
    ) -> None:
        """Documentele sunt probe contabile. Drumul pe care au venit nu le schimbă."""
        sync(db, storage, FakeImapClient(messages=[message(uid=6)]), mailbox)
        mailbox_id = mailbox.id
        db.commit()
        login(api, admin.email)

        answer = api.delete(f"/api/v1/integrations/imap/{mailbox_id}")

        assert answer.status_code == 204
        assert documents(db, org) == 1
        assert db.scalars(select(ImapMailbox)).all() == []


class TestTheIntakeTrail:
    def test_every_attachment_leaves_a_row(
        self,
        db: Session,
        org: Organization,
        storage: LocalStorageProvider,
        mailbox: ImapMailbox,
        contact: Contact,
    ) -> None:
        """Cronologia „Mesaje" se construiește din ele, nu din documente.

        Un atașament respins nu produce document, dar trebuie să se vadă că a
        sosit — altfel cine caută o factură trimisă nu află niciodată ce a pățit.
        """
        client = FakeImapClient(
            messages=[
                message(
                    uid=8,
                    attachments=(ImapAttachment(index=1, name="factura.pdf", content=PDF_BYTES),),
                )
            ]
        )

        sync(db, storage, client, mailbox)

        intake = db.scalars(
            select(DocumentIntake).where(DocumentIntake.source == DocumentSource.EMAIL)
        ).one()
        assert intake.sender == "contact@alfa.test"
        assert intake.recipient == mailbox.username
        assert intake.raw_payload["uid"] == 8
