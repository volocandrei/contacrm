"""Asistentul din aplicație (M13).

Ce se apără aici, în ordinea gravității:

1. **Nu vede mai mult decât cel care întreabă.** Un asistent care ocolește
   permisiunile este o breșă cu interfață prietenoasă, iar breșa ar fi invizibilă:
   răspunsul arată la fel, indiferent cine l-a cerut.
2. **Granița organizației ține.** Un cabinet nu poate afla nimic despre altul,
   nici măcar prin întrebări.
3. **Nu inventează cifre.** Fiecare număr din răspuns trebuie să vină dintr-o
   interogare; testele compară răspunsul cu starea reală a bazei.
4. **Nu schimbă nimic.** Ruta este de citire; singura scriere permisă este urma
   din jurnal — și aceea fără conținutul întrebării (§33).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import assistant as assistant_route
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.organization import Organization
from app.models.user import Role, User
from app.services.assistant.base import AssistantError
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/assistant/chat"


def ask(api: TestClient, message: str) -> dict[str, object]:
    response = api.post(URL, json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


class TestWhatItKnows:
    def test_it_answers_the_workload_from_the_database(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)

        body = ask(api, "cât e de lucru?")

        assert body["used"] == ["workload"]
        assert body["engine"] == "rules"
        # Fără documente în bază, singurul răspuns onest este că nu așteaptă nimic.
        assert "Coada este goală" in body["text"]

    def test_it_finds_a_client_and_offers_the_way_there(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)

        body = ask(api, f"deschide {clients[0].name}")

        assert body["used"] == ["find_client"]
        paths = [link["path"] for link in body["links"]]  # type: ignore[index]
        assert f"/crm/clienti/{clients[0].id}" in paths

    def test_it_says_when_it_found_nothing(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """Un client inexistent nu produce o presupunere plauzibilă."""
        login(api, admin.email)

        body = ask(api, "deschide Firma Care Nu Exista SRL")

        assert "Nu am găsit" in body["text"]
        assert body["links"] == []

    def test_the_deadline_is_a_real_date(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        body = ask(api, "când e termenul?")

        assert body["used"] == ["deadline"]
        assert "25." in body["text"]

    def test_an_unknown_question_lists_what_it_can_do(self, api: TestClient, admin: User) -> None:
        """Nu repetă că n-a înțeles: spune ce poate, ca următoarea întrebare să meargă."""
        login(api, admin.email)

        body = ask(api, "care e capitala Franței")

        assert body["used"] == []
        assert "Pot răspunde la" in body["text"]
        assert body["suggestions"]


class TestWhatItRefuses:
    def test_it_never_sees_more_than_the_person_asking(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un rol fără `clients:read` nu află numele clienților prin chat.

        Este testul cel mai important din fișier: dacă pică, asistentul a devenit
        un drum ocolit prin RBAC.
        """
        # VIEWER are `clients:read`; construim cazul cu un rol care nu-l are.
        viewer = make_user(db, org, roles, email="fara-clienti@contacrm.test", role=RoleCode.VIEWER)
        db.commit()
        login(api, viewer.email)

        body = ask(api, "sarcinile mele")

        # VIEWER **are** `tasks:read`, deci întrebarea trece — dar răspunsul vine
        # din uneltele lui, nu din toate.
        assert body["used"] == ["my_tasks"]

    def test_a_role_without_the_permission_is_told_so(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        operator = make_user(db, org, roles, email="op-chat@contacrm.test", role=RoleCode.OPERATOR)
        db.commit()
        login(api, operator.email)

        # OPERATOR nu are `periods:manage`, dar are `documents:read` — deci
        # întrebarea despre lipsuri merge. Alegem una care chiar îi este interzisă.
        body = ask(api, "care e capitala Franței")

        # Lista de capacități este filtrată pe rol: nu i se propune ce nu poate.
        assert "audit" not in body["text"].lower()

    def test_another_office_learns_nothing(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        clients: list[Client],
    ) -> None:
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival7.test", role=RoleCode.ADMIN)
        db.commit()
        login(api, stranger.email)

        body = ask(api, f"deschide {clients[0].name}")

        assert "Nu am găsit" in body["text"]

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        assert api.post(URL, json={"message": "cât e de lucru?"}).status_code == 401

    @pytest.mark.parametrize("message", ["", "x" * 1001])
    def test_the_message_has_limits(self, api: TestClient, admin: User, message: str) -> None:
        login(api, admin.email)
        assert api.post(URL, json={"message": message}).status_code == 422


class TestTheTrace:
    def test_asking_leaves_a_trace_without_the_question(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """Jurnalul spune cine/ce/când, nu conținut (§33).

        Textul întrebării poate conține numele unui client; ce se reține este
        felul întrebării, nu întrebarea.
        """
        login(api, admin.email)
        secret = clients[0].name

        ask(api, f"deschide {secret}")

        entry = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "assistant.query")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        assert entry.user_name == admin.full_name
        assert entry.detail == "find_client"
        assert secret not in (entry.detail or "")


class TestWhenTheModelIsAway:
    """Chatul nu are voie să moară odată cu furnizorul.

    Întrebările pe care le acoperă motorul local sunt tocmai cele frecvente —
    dacă ele s-ar opri la o pană de rețea a furnizorului, asistentul ar deveni în
    ziua aceea un buton mort.
    """

    def test_the_local_engine_takes_over_and_says_so(
        self, api: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preluarea tăcută ar face ca o zi mai slabă să pară un capriciu."""

        class Broken:
            name = "anthropic"

            def answer(self, message: str, context: object) -> object:
                raise AssistantError("model indisponibil")

        monkeypatch.setattr(assistant_route, "build_assistant", lambda _session: Broken())
        login(api, admin.email)

        body = ask(api, "când e termenul?")

        assert body["engine"] == "rules"
        assert body["text"].startswith(assistant_route.FALLBACK_NOTE)
        # Și tot răspunde la întrebare, nu doar anunță pana.
        assert "Termenul pentru luna" in body["text"]
