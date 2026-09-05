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
from app.domain.periods import filing_deadline
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.upload_link import ClientUploadLink
from app.models.user import Role, User
from app.services.assistant.tools import previous_month
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
