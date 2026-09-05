"""Solicitarea de documente: textul și drumul pe care sosește răspunsul (M14).

**Ce apără testele de aici.** Partea grea a muncii unui cabinet nu este
procesarea documentelor, ci adunarea lor. O listă cu ce lipsește îi spune
clientului *ce* să caute și îl lasă singur cu *cum* trimite — scanat, atașat,
limita de mărime a emailului, amânat. De aceea cererea pleacă împreună cu un link
de trimitere, într-un singur mesaj.

Ruta n-a avut niciodată teste, deși compune un text care pleacă la clienți. Acum
compune și un drum public de scriere, așa că are nevoie de ele mai mult ca oricând.

**În ordinea gravității:**

1. **Linkul din mesaj chiar funcționează**, și duce la clientul potrivit. Un link
   mort trimis unui client este mai rău decât niciun link: omul încearcă, nu merge,
   și data viitoare nu mai încearcă.
2. **Nu se deschide un drum degeaba.** Dacă nu lipsește nimic, nu se creează nimic:
   altfel ar rămâne deschise 45 de zile linkuri pentru mesaje care n-au plecat.
3. **Cine aleargă după documente poate.** Gardul este `documents:write`, nu
   `clients:write` — altfel tocmai contabilul, omul pentru care s-a făcut funcția,
   n-ar putea-o folosi.
4. **Jurnalul spune cine și pentru cine, niciodată tokenul** (§33).
5. **Este POST.** Un GET care creează un link l-ar crea din nou la fiecare
   reîncărcare de pagină.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import ClientStatus
from app.domain.periods import filing_deadline
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client, Contact
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.upload_link import ClientUploadLink
from app.models.user import Role, User
from app.services.assistant.tools import previous_month
from app.services.mail import DisabledEmailSender, EmailError, EmailMessage
from tests.conftest import requires_db
from tests.test_periods_api import MONTH, PDF, add_document, login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


@pytest.fixture
def gaps(
    db: Session,
    org: Organization,
    client_row: Client,
    types: dict[str, DocumentType],
    expectations: dict[str, ClientExpectation],
) -> None:
    """O lună începută, dar neterminată.

    O factură a sosit — deci perioada există; restul lipsește — deci e ceva de
    cerut. Fără primul document, luna nu se inventează, iar ruta n-ar avea ce
    compune.
    """
    add_document(db, org, client_row, types["FACTURA_INTRARE"])
    db.commit()


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    """Providerul de email, înlocuit cu unul care reține.

    Nu pleacă nimic nicăieri, dar se poate verifica **ce** ar fi plecat — care
    este singurul lucru pe care un test are cum să-l verifice fără un server de
    mail adevărat.
    """
    sent: list[EmailMessage] = []

    class Collecting:
        name = "test"

        def send(self, message: EmailMessage) -> None:
            sent.append(message)

    # Amândouă rutele: cea pentru un client și cea pentru mai mulți.
    monkeypatch.setattr("app.api.v1.clients.build_email_sender", lambda: Collecting())
    monkeypatch.setattr("app.api.v1.periods.build_email_sender", lambda: Collecting())
    return sent


def compose(api: TestClient, client_row: Client, month: str = MONTH):
    return api.post(f"/api/v1/clients/{client_row.id}/document-request?referenceMonth={month}")


def token_from(message: str) -> str:
    """Tokenul așa cum îl vede clientul: din textul mesajului, nu din bază.

    Testul îl citește de unde îl citește și omul. Dacă mesajul ar purta altă
    adresă decât cea emisă, aici s-ar vedea.
    """
    marker = f"{settings.public_base_url}/incarca/"
    line = next(row for row in message.splitlines() if row.startswith(marker))
    return line[len(marker) :]


# ── Ce trebuie să facă ───────────────────────────────────────────────────────


class TestTheMessage:
    def test_it_lists_what_is_missing_and_says_until_when(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        login(api_storage, admin.email)

        body = compose(api_storage, client_row).json()

        message = body["message"]
        assert "august 2026" in message
        assert "•" in message  # lista, nu o propoziție care spune „lipsesc documente"
        deadline = filing_deadline(MONTH, day=settings.filing_deadline_day)
        assert deadline.strftime("%d.%m.%Y") in message

    def test_it_carries_the_way_to_send(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        """Cererea și drumul pleacă împreună — asta e toată ideea."""
        db.commit()
        login(api_storage, admin.email)

        body = compose(api_storage, client_row).json()

        assert body["uploadUrl"] in body["message"]
        # Și data până la care merge: altfel clientul care încearcă peste patru
        # luni nu află de ce nu mai merge, iar contabilul nu-și amintește când.
        expires = datetime.fromisoformat(body["uploadExpiresAt"])
        assert expires.strftime("%d.%m.%Y") in body["message"]

    def test_the_link_in_the_message_actually_works(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        """Testul care contează: clientul deschide linkul din mesaj și trimite.

        Toate celelalte verifică forma. Ăsta verifică fondul — că mesajul pe care
        îl primește omul îl duce chiar la dosarul lui.
        """
        db.commit()
        login(api_storage, admin.email)
        message = compose(api_storage, client_row).json()["message"]

        sent = api_storage.post(
            f"/api/v1/portal/{token_from(message)}",
            files={"file": ("de-la-client.pdf", PDF, "application/pdf")},
        )

        assert sent.status_code == 201, sent.text
        document = db.scalars(
            select(Document).where(Document.original_filename == "de-la-client.pdf")
        ).one()
        assert document.client_id == client_row.id
        assert document.status.value != "UNMATCHED"


# ── Ce nu trebuie să facă ────────────────────────────────────────────────────


class TestRestraint:
    def test_nothing_is_opened_when_there_is_nothing_to_ask(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        types: dict[str, DocumentType],
        gaps: None,
    ) -> None:
        """Un drum public deschis pentru un mesaj care nu pleacă stă deschis degeaba."""
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["EXTRAS_CONT"])
        db.commit()
        login(api_storage, admin.email)

        response = compose(api_storage, client_row)

        assert response.status_code == 422
        assert db.scalars(select(ClientUploadLink)).all() == []

    def test_a_get_does_not_create_anything(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        """Un GET care creează s-ar executa din nou la fiecare reîncărcare."""
        db.commit()
        login(api_storage, admin.email)

        response = api_storage.get(
            f"/api/v1/clients/{client_row.id}/document-request?referenceMonth={MONTH}"
        )

        assert response.status_code == 405
        assert db.scalars(select(ClientUploadLink)).all() == []

    def test_a_client_from_another_office_is_not_found(
        self, api_storage: TestClient, db: Session, admin: User, client_row: Client
    ) -> None:
        """404, nu 403: altfel răspunsul confirmă că id-ul există undeva (§72)."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        stranger = Client(organization_id=other.id, name="Străin SRL", tax_id="RO999")
        db.add(stranger)
        db.commit()
        login(api_storage, admin.email)

        assert compose(api_storage, stranger).status_code == 404


# ── Cine are voie ────────────────────────────────────────────────────────────


class TestPermissions:
    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            # Contabilul este cel care aleargă după documente. Cu gardul de la
            # început — `clients:write`, pe care îl are numai administratorul —
            # tocmai el n-ar fi putut folosi funcția făcută pentru el.
            (RoleCode.ACCOUNTANT, 200),
            (RoleCode.OPERATOR, 200),
            # Cine doar citește nu deschide o cale publică de scriere.
            (RoleCode.VIEWER, 403),
        ],
    )
    def test_who_can_open_a_way_in(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        gaps: None,
        role: RoleCode,
        expected: int,
    ) -> None:
        user = make_user(db, org, roles, email=f"{role.value.lower()}@contacrm.test", role=role)
        db.commit()
        login(api_storage, user.email)

        assert compose(api_storage, client_row).status_code == expected

    def test_without_a_session_nothing(
        self, api_storage: TestClient, db: Session, client_row: Client
    ) -> None:
        db.commit()

        assert compose(api_storage, client_row).status_code == 401


# ── Urma ─────────────────────────────────────────────────────────────────────


class TestTheTrace:
    def test_the_journal_says_who_and_for_whom_never_the_token(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        """§33: cine, ce, când — nu conținut, și cu atât mai puțin chei."""
        db.commit()
        login(api_storage, admin.email)

        body = compose(api_storage, client_row).json()

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "UPLOAD_LINK_ISSUED")).one()
        assert entry.user_name == admin.full_name
        assert client_row.name in (entry.detail or "")
        assert MONTH in (entry.detail or "")

        token = token_from(body["message"])
        assert token not in (entry.detail or "")
        assert all(token not in (row.detail or "") for row in db.scalars(select(AuditLog)))


# ── Asistentul ───────────────────────────────────────────────────────────────


class TestTheAssistantProposes:
    """Asistentul pregătește cererea, dar nu deschide el drumul.

    Ruta de chat nu execută nimic care schimbă date — un asistent care deschide
    tăcut o cale publică de scriere pentru că cineva a scris o frază ar rupe exact
    promisiunea pe care stă restul lui. Deci: propune, iar omul apasă.
    """

    def test_it_prepares_the_request_without_opening_anything(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        # Luna pe care o are în vedere asistentul, nu una fixă: altfel testul ar
        # fi verde până în prima zi a lunii următoare.
        month = previous_month()
        add_document(db, org, client_row, types["FACTURA_INTRARE"], reference_month=month)
        db.commit()
        login(api_storage, admin.email)

        reply = api_storage.post(
            "/api/v1/assistant/chat",
            json={"message": f"scrie solicitarea pentru {client_row.name}"},
        ).json()

        assert reply["used"] == ["draft_request"]
        action = reply["actions"][0]
        assert action["kind"] == "request_documents"
        assert action["payload"] == {"clientId": str(client_row.id), "referenceMonth": month}
        # Nimic deschis: linkul apare abia când omul apasă butonul.
        assert db.scalars(select(ClientUploadLink)).all() == []
        assert "/incarca/" not in reply["text"]

    def test_a_reader_gets_no_proposal(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Un buton care ar da 403 la apăsare este mai rău decât unul care lipsește."""
        month = previous_month()
        add_document(db, org, client_row, types["FACTURA_INTRARE"], reference_month=month)
        viewer = make_user(db, org, roles, email="doar-citesc@contacrm.test", role=RoleCode.VIEWER)
        db.commit()
        login(api_storage, viewer.email)

        reply = api_storage.post(
            "/api/v1/assistant/chat",
            json={"message": f"scrie solicitarea pentru {client_row.name}"},
        ).json()

        assert reply["actions"] == []


# ── Urmărirea ────────────────────────────────────────────────────────────────


def report(api: TestClient, month: str = MONTH) -> list[dict[str, object]]:
    response = api.get(f"/api/v1/periods/missing?referenceMonth={month}")
    assert response.status_code == 200, response.text
    return list(response.json())


class TestFollowUp:
    """Cine a fost întrebat, când, și dacă a răspuns.

    **De ce contează mai mult decât pare.** Un cabinet cere documentele a
    treizeci de clienți în aceeași săptămână. Fără urmă pe ecran, peste trei zile
    cere de două ori unuia și îl uită complet pe altul — iar uitatul nu costă
    timp, costă o lună întârziată. Raportul de documente lipsă este singurul loc
    unde întrebarea „pe cine mai am de sunat" are un răspuns.
    """

    def test_before_anything_nobody_has_been_asked(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        login(api_storage, admin.email)

        entry = report(api_storage)[0]

        assert entry["requestedAt"] is None
        assert entry["receivedThroughLink"] == 0

    def test_the_report_remembers_the_request(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        login(api_storage, admin.email)
        compose(api_storage, client_row)

        entry = report(api_storage)[0]

        assert entry["requestedAt"] is not None

    def test_it_counts_what_came_through_that_link(
        self, api_storage: TestClient, db: Session, admin: User, client_row: Client, gaps: None
    ) -> None:
        """Semnalul de urmărire: i-am cerut, a făcut ceva?"""
        login(api_storage, admin.email)
        message = compose(api_storage, client_row).json()["message"]
        api_storage.post(
            f"/api/v1/portal/{token_from(message)}",
            files={"file": ("raspuns.pdf", PDF, "application/pdf")},
        )

        entry = report(api_storage)[0]

        assert entry["receivedThroughLink"] == 1

    def test_a_link_opened_from_the_client_file_is_not_a_request(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        """Un drum lăsat deschis nu este o întrebare pusă.

        Dacă ar conta ca cerere, ecranul ar spune „i s-a cerut" despre un client
        pe care nu l-a întrebat nimeni — exact clientul care așteaptă degeaba.
        """
        login(api_storage, admin.email)
        opened = api_storage.post(f"/api/v1/clients/{client_row.id}/upload-links")
        assert opened.status_code == 201, opened.text

        entry = report(api_storage)[0]

        assert entry["requestedAt"] is None

    def test_asking_again_does_not_erase_what_already_arrived(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        """A doua cerere nu șterge de pe ecran ce trimisese omul după prima.

        Dacă am fi numărat doar ultimul link, contorul ar fi sărit înapoi la zero
        și l-am fi sunat pe un client care își făcuse treaba.
        """
        login(api_storage, admin.email)
        message = compose(api_storage, client_row).json()["message"]
        api_storage.post(
            f"/api/v1/portal/{token_from(message)}",
            files={"file": ("primul.pdf", PDF, "application/pdf")},
        )

        compose(api_storage, client_row)

        assert report(api_storage)[0]["receivedThroughLink"] == 1

    def test_the_month_is_the_one_asked_about(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        """O cerere pe august nu apare ca răspuns la întrebarea despre iulie."""
        login(api_storage, admin.email)
        compose(api_storage, client_row)

        other = [row for row in report(api_storage, "2026-07")]

        assert all(row["requestedAt"] is None for row in other)


def _notified(db: Session) -> list[ClientUploadLink]:
    """Linkurile pentru care mesajul chiar a plecat."""
    return list(
        db.scalars(select(ClientUploadLink).where(ClientUploadLink.notified_at.is_not(None)))
    )


class TestSendingIt:
    """Trimiterea, cu providerul înlocuit.

    Ce contează cel mai mult nu este că mesajul pleacă, ci **ordinea**: se scrie
    „trimis" numai după ce providerul a confirmat. Invers, un server de mail
    căzut ar fi lăsat pe ecran „Trimis" pentru un mesaj care n-a plecat.
    """

    def _send(
        self, api: TestClient, client_row: Client, month: str = MONTH, **body: object
    ) -> object:
        return api.post(
            f"/api/v1/clients/{client_row.id}/document-request/send?referenceMonth={month}",
            json=body,
        )

    def test_it_goes_to_the_client_contact(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        login(api_storage, admin.email)
        db.add(
            Contact(
                client_id=client_row.id,
                full_name="Maria Ionescu",
                email="maria@alfaconta.test",
            )
        )
        db.commit()

        response = self._send(api_storage, client_row)

        assert response.status_code == 201, response.text
        assert response.json()["sentTo"] == "maria@alfaconta.test"
        assert len(outbox) == 1
        assert outbox[0].to == "maria@alfaconta.test"

    def test_the_body_is_the_same_text_the_copy_button_gives(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Două implementări ar însemna că doi clienți primesc, în aceeași zi,
        două scrisori diferite de la același cabinet."""
        login(api_storage, admin.email)
        db.add(
            Contact(
                client_id=client_row.id,
                full_name="Maria Ionescu",
                email="maria@alfaconta.test",
            )
        )
        db.commit()
        copied = compose(api_storage, client_row).json()["message"]

        self._send(api_storage, client_row)

        # Linkul diferă — fiecare cerere deschide unul nou —, restul textului nu.
        without_link = lambda text: "\n".join(  # noqa: E731
            line for line in text.splitlines() if "/incarca/" not in line
        )
        assert without_link(outbox[0].body) == without_link(copied)

    def test_an_explicit_address_wins(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Cineva a ales alt contact, sau a corectat o adresă greșită."""
        login(api_storage, admin.email)
        response = self._send(api_storage, client_row, to="altcineva@exemplu.test")

        assert response.status_code == 201, response.text
        assert outbox[0].to == "altcineva@exemplu.test"

    def test_a_client_without_an_address_is_refused_with_what_to_do(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        login(api_storage, admin.email)
        response = self._send(api_storage, client_row)

        assert response.status_code == 422
        assert "email" in response.json()["message"].lower()
        assert outbox == []

    def test_the_trace_says_sent_only_after_it_left(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Diferența dintre „Pregătit" și „Trimis", verificată pe ambele drumuri."""
        login(api_storage, admin.email)
        compose(api_storage, client_row)

        # Ordonarea după `created_at` nu ar deosebi cele două linkuri: `now()`
        # dă în Postgres ora de **început a tranzacției**, deci amândouă pot avea
        # exact aceeași valoare. Se caută după fapt, care este chiar ce apără
        # testul.
        assert _notified(db) == []

        self._send(api_storage, client_row, to="cineva@exemplu.test")
        db.expire_all()

        sent = _notified(db)
        assert len(sent) == 1
        assert sent[0].notified_to == "cineva@exemplu.test"

    def test_a_failed_send_does_not_claim_it_was_sent(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ordinea, apărată direct.

        Scrisă înainte de trimitere, coloana ar fi spus „Trimis" pentru un mesaj
        pe care serverul de mail l-a refuzat.
        """
        login(api_storage, admin.email)

        class Broken:
            name = "broken"

            def send(self, message: EmailMessage) -> None:
                del message
                raise EmailError("serverul a refuzat")

        monkeypatch.setattr("app.api.v1.clients.build_email_sender", lambda: Broken())

        response = self._send(api_storage, client_row, to="cineva@exemplu.test")

        assert response.status_code == 502
        db.expire_all()
        link = db.scalars(
            select(ClientUploadLink).order_by(ClientUploadLink.created_at.desc())
        ).first()
        assert link is not None
        assert link.notified_at is None

    def test_without_configuration_it_says_what_is_missing(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        gaps: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nu o defecțiune: cineva încă nu a pus setările."""
        login(api_storage, admin.email)
        monkeypatch.setattr("app.api.v1.clients.build_email_sender", lambda: DisabledEmailSender())

        response = self._send(api_storage, client_row, to="cineva@exemplu.test")

        assert response.status_code == 422
        assert "NOTIFICATIONS_ENABLED" in response.json()["message"]

    def test_the_log_says_who_and_to_whom_never_the_text(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        login(api_storage, admin.email)
        self._send(api_storage, client_row, to="cineva@exemplu.test")

        entry = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "DOCUMENT_REQUEST_SENT")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        assert "cineva@exemplu.test" in (entry.detail or "")
        # §33: jurnalul spune cine a făcut ce, nu ce scria în mesaj.
        assert "Bună ziua" not in (entry.detail or "")

    def test_nothing_is_sent_when_nothing_is_missing(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        outbox: list[EmailMessage],
    ) -> None:
        """Fără `gaps`: luna nu are ce cere, deci nu pleacă nimic și nu se
        deschide niciun drum public."""
        login(api_storage, admin.email)
        response = self._send(api_storage, client_row)

        assert response.status_code == 422
        assert outbox == []


class TestTheClientWhoSentNothing:
    """Cel căruia îi lipsește tot.

    Raportul „Documente lipsă" îl arată — este chiar clientul pentru care a fost
    făcut — și îi pune butonul de cerere pe rând. Compunerea citea însă din
    `list_periods`, care nu inventează o lună fără documente și fără rând, deci
    butonul răspundea „clientul nu are documente lipsă" exact acolo unde lipsea
    totul.

    Găsit apăsând butonul în browser, nu citind codul.
    """

    def test_a_client_with_no_documents_at_all_can_still_be_asked(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        org: Organization,
        types: dict[str, DocumentType],
        gaps: None,
    ) -> None:
        login(api_storage, admin.email)
        # Client cu așteptări și **niciun** document în luna cerută: nu are rând
        # de perioadă, deci `list_periods` nu-l vede.
        # `ACTIVE` explicit: implicit un client este `PROSPECT`, iar raportul îi
        # lasă deoparte deliberat — un prospect nu este încă client.
        silent = Client(
            organization_id=org.id,
            name="Tăcut SRL",
            tax_id="RO4242",
            status=ClientStatus.ACTIVE,
        )
        db.add(silent)
        db.flush()
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=silent.id,
                document_type_id=types["EXTRAS_CONT"].id,
                expected_min_count=1,
            )
        )
        db.commit()

        response = compose(api_storage, silent, MONTH)

        assert response.status_code == 200, response.text
        assert "Extras cont" in response.json()["message"]

    def test_the_report_and_the_request_agree_on_who_can_be_asked(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        org: Organization,
        types: dict[str, DocumentType],
        gaps: None,
    ) -> None:
        """Un rând cu buton pe care butonul îl refuză este mai rău decât un rând fără buton."""
        login(api_storage, admin.email)
        silent = Client(
            organization_id=org.id,
            name="Tăcut Doi SRL",
            tax_id="RO4243",
            status=ClientStatus.ACTIVE,
        )
        db.add(silent)
        db.flush()
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=silent.id,
                document_type_id=types["EXTRAS_CONT"].id,
                expected_min_count=1,
            )
        )
        db.commit()

        listed = {row["period"]["clientId"] for row in report(api_storage, MONTH)}

        for client_id in listed:
            composed = api_storage.post(
                f"/api/v1/clients/{client_id}/document-request?referenceMonth={MONTH}"
            )
            assert composed.status_code == 200, (
                f"raportul îl listează pe {client_id}, dar cererea îl refuză: {composed.text}"
            )


class TestSendingToMany:
    """Cererea către mai mulți clienți deodată.

    Un cabinet cere documentele a treizeci de clienți în aceeași săptămână. Unul
    câte unul, asta înseamnă treizeci de deschideri de fișă.

    Ce apără testele, în ordinea gravității:

    1. **Un client care eșuează nu-i oprește pe ceilalți.** Omul a apăsat un
       buton, dar a luat treizeci de decizii.
    2. **Ce eșuează nu lasă urmă.** Un link deschis pentru un mesaj care n-a
       plecat este un drum către nicăieri, deschis 45 de zile — tokenul se vede o
       singură dată.
    3. **Se trimite exact cui a fost pe ecran.** Serverul nu decide singur cine
       mai intră în lot; un email plecat nu se retrage.
    """

    URL = "/api/v1/periods/missing/send-requests"

    def _send(self, api: TestClient, ids: list[str], month: str = MONTH):
        return api.post(f"{self.URL}?referenceMonth={month}", json={"clientIds": ids})

    def test_it_sends_to_everyone_on_the_list(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        login(api_storage, admin.email)
        db.add(Contact(client_id=client_row.id, full_name="Maria", email="maria@alfa.test"))
        db.commit()

        response = self._send(api_storage, [str(client_row.id)])

        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["sentTo"] for row in body["sent"]] == ["maria@alfa.test"]
        assert body["failed"] == []
        assert len(outbox) == 1

    def test_a_client_without_an_address_does_not_stop_the_others(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Al treilea care nu are email nu are voie să anuleze primii doi."""
        login(api_storage, admin.email)
        db.add(Contact(client_id=client_row.id, full_name="Maria", email="maria@alfa.test"))
        mute = Client(organization_id=org.id, name="Fără Email SRL", tax_id="RO777")
        db.add(mute)
        db.flush()
        add_document(db, org, mute, types["FACTURA_INTRARE"])
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=mute.id,
                document_type_id=types["EXTRAS_CONT"].id,
                expected_min_count=1,
            )
        )
        db.commit()

        response = self._send(api_storage, [str(mute.id), str(client_row.id)])

        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["clientId"] for row in body["sent"]] == [str(client_row.id)]
        assert [row["clientId"] for row in body["failed"]] == [str(mute.id)]
        assert "email" in body["failed"][0]["message"].lower()
        assert len(outbox) == 1

    def test_a_failed_client_leaves_no_open_link(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Tokenul se vede o singură dată.

        Un link rămas după un mesaj care n-a plecat este un drum pe care nu-l
        știe nimeni, deschis 45 de zile.
        """
        login(api_storage, admin.email)
        mute = Client(organization_id=org.id, name="Fără Email SRL", tax_id="RO778")
        db.add(mute)
        db.flush()
        add_document(db, org, mute, types["FACTURA_INTRARE"])
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=mute.id,
                document_type_id=types["EXTRAS_CONT"].id,
                expected_min_count=1,
            )
        )
        db.commit()
        before = len(db.scalars(select(ClientUploadLink)).all())

        self._send(api_storage, [str(mute.id)])
        db.expire_all()

        assert len(db.scalars(select(ClientUploadLink)).all()) == before

    def test_a_repeated_id_is_sent_once(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """Aceeași firmă bifată de două ori nu primește două scrisori."""
        login(api_storage, admin.email)
        db.add(Contact(client_id=client_row.id, full_name="Maria", email="maria@alfa.test"))
        db.commit()

        self._send(api_storage, [str(client_row.id), str(client_row.id)])

        assert len(outbox) == 1

    def test_a_client_with_nothing_missing_is_reported_not_sent(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        org: Organization,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        login(api_storage, admin.email)
        complete = Client(organization_id=org.id, name="Complet SRL", tax_id="RO779")
        db.add(complete)
        db.commit()

        response = self._send(api_storage, [str(complete.id)])

        assert response.status_code == 200
        assert response.json()["sent"] == []
        assert outbox == []

    def test_an_unconfigured_provider_refuses_the_whole_batch(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Al treizecilea refuz spune același lucru ca primul.

        Lipsește configurarea, nu adresa unui client — deci nu are rost să
        încercăm restul, iar rezultatul nu are voie să arate ca treizeci de
        clienți cu probleme.
        """
        login(api_storage, admin.email)
        db.add(Contact(client_id=client_row.id, full_name="Maria", email="maria@alfa.test"))
        db.commit()
        monkeypatch.setattr("app.api.v1.periods.build_email_sender", lambda: DisabledEmailSender())

        response = self._send(api_storage, [str(client_row.id)])

        assert response.status_code == 422
        assert "NOTIFICATIONS_ENABLED" in response.json()["message"]

    def test_an_empty_list_is_refused(
        self, api_storage: TestClient, admin: User, client_row: Client
    ) -> None:
        """Un lot gol este o greșeală de ecran, nu o cerere validă."""
        login(api_storage, admin.email)

        assert self._send(api_storage, []).status_code == 422

    def test_another_organizations_client_is_reported_not_sent(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
        outbox: list[EmailMessage],
    ) -> None:
        """§72: nu se confirmă existența, nici măcar printr-un refuz diferit."""
        login(api_storage, admin.email)
        stranger = Organization(name="Alt Cabinet SRL")
        db.add(stranger)
        db.flush()
        theirs = Client(organization_id=stranger.id, name="Terț SRL")
        db.add(theirs)
        db.commit()

        response = self._send(api_storage, [str(theirs.id)])

        assert response.status_code == 200
        assert response.json()["sent"] == []
        assert outbox == []
