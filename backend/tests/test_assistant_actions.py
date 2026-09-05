"""Propunerile asistentului.

**Linia care nu se trece.** Asistentul pregătește; omul apasă. Fiecare test de
aici verifică o parte din granița asta:

1. O propunere **nu execută nimic** — după întrebare, baza este neatinsă.
2. Propunerea poartă **id-uri verificate**, nu nume ghicite: butonul cheamă ruta
   obișnuită, iar ruta primește exact ce așteaptă.
3. **Rolul contează la fel ca peste tot**: cine nu poate crea o sarcină nu
   primește nici propunerea de a crea una.
4. Ce se propune **există**: nu se pregătește o atribuire când nu e nimic de
   atribuit.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.permissions import RoleCode
from app.models.client import Client
from app.models.organization import Organization
from app.models.task import Task
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/assistant/chat"


def ask(api: TestClient, message: str) -> dict:
    response = api.post(URL, json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


class TestPreparingATask:
    def test_it_prepares_but_does_not_create(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        """Rostul întreg: după întrebare, nicio sarcină nouă în bază."""
        login(api, admin.email)
        before = db.scalar(select(func.count()).select_from(Task))

        body = ask(api, "notează să sun la Alfa vineri")

        assert body["used"] == ["propose_task"]
        action = body["actions"][0]
        assert action["kind"] == "create_task"
        assert action["payload"]["title"] == "să sun la Alfa vineri"
        assert db.scalar(select(func.count()).select_from(Task)) == before

    def test_the_prepared_payload_is_what_the_route_expects(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        """Butonul cheamă ruta obișnuită; dacă forma nu se potrivește, cade acolo."""
        login(api, admin.email)
        action = ask(api, "notează de verificat extrasele")["actions"][0]

        created = api.post("/api/v1/tasks", json=action["payload"])

        assert created.status_code == 201, created.text
        assert created.json()["title"] == "de verificat extrasele"
        assert created.json()["assignedToName"] == admin.full_name

    def test_a_role_that_cannot_write_gets_no_proposal(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un buton pe care apăsarea l-ar refuza este mai rău decât absența lui."""
        viewer = make_user(db, org, roles, email="doar-citeste@contacrm.test", role=RoleCode.VIEWER)
        db.commit()
        login(api, viewer.email)

        body = ask(api, "notează să sun la Alfa")

        # VIEWER nu are `tasks:write`; unealta nici nu apare în lista lui.
        assert body["actions"] == []
        assert "tasks:write" in body["text"] or body["used"] == []


class TestPreparingAnAssignment:
    def test_it_says_when_there_is_nothing_to_assign(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """Nu se pregătește o acțiune fără obiect."""
        login(api, admin.email)

        body = ask(api, f"atribuie documentele lui {clients[0].name}")

        assert body["actions"] == []
        assert "Nu există documente neatribuite" in body["text"]

    def test_an_unknown_client_is_not_guessed(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        body = ask(api, "atribuie documentele lui Firma Inexistenta SRL")

        assert body["actions"] == []
        assert "Nu am găsit" in body["text"]


class TestDraftingTheRequest:
    def test_it_writes_the_message_with_real_numbers(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """Fără așteptări configurate nu are ce cere — și o spune, nu inventează."""
        login(api, admin.email)

        body = ask(api, f"scrie solicitarea pentru {clients[0].name}")

        assert body["used"] == ["draft_request"]
        assert "documente lipsă" in body["text"] or "Bună ziua" in body["text"]
        # Un draft nu este o acțiune: nu are ce confirma nimeni, textul se copiază.
        assert body["actions"] == []
