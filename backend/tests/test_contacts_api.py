"""Agenda cabinetului — `GET /contacts`.

**Ce a fost de reparat.** Ecranul „Contacte" cerea lista de clienți și apoi
contactele fiecăruia: o cerere per client. Testul care contează cel mai mult este
deci cel care spune că **o singură cerere** aduce contacte din firme diferite.

Restul apără ce face agenda utilizabilă: căutarea prinde și persoana și firma,
contactele dezactivate nu se propun (cineva care a plecat din firmă), iar
granița organizației ține — un contact din alt cabinet nu se distinge de unul
inexistent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.permissions import RoleCode
from app.models.client import Client, Contact
from app.models.organization import Organization
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/contacts"


@pytest.fixture
def agenda(db: Session, org: Organization, clients: list[Client]) -> list[Contact]:
    """Două firme, patru persoane — una dezactivată, două principale."""
    first, second = clients[0], clients[1]
    rows = [
        Contact(
            client_id=first.id,
            full_name="Ioana Marinescu",
            role="Administrator",
            email="ioana@alfa.test",
            phone="0722 111 222",
            whatsapp_number="+40722111222",
            is_primary=True,
        ),
        Contact(
            client_id=first.id,
            full_name="Andrei Georgescu",
            role="Contabil intern",
            email="andrei@alfa.test",
        ),
        Contact(
            client_id=second.id,
            full_name="Maria Șerban",
            role="Director",
            email="maria@beta.test",
            is_primary=True,
        ),
        Contact(
            client_id=second.id,
            full_name="Fost Angajat",
            role="Fost contabil",
            email="fost@beta.test",
            is_active=False,
        ),
    ]
    db.add_all(rows)
    db.commit()
    return rows


class TestTheAddressBook:
    def test_one_request_returns_contacts_across_clients(
        self, api: TestClient, admin: User, agenda: list[Contact], clients: list[Client]
    ) -> None:
        """Rostul întreg al rutei: nu mai e nevoie de o cerere per client."""
        login(api, admin.email)

        response = api.get(URL, params={"pageSize": 50})

        assert response.status_code == 200
        body = response.json()
        firms = {item["clientName"] for item in body["items"]}
        assert firms == {clients[0].name, clients[1].name}
        assert body["total"] == 3  # fără cel dezactivat

    def test_the_primary_contact_comes_first_within_a_firm(
        self, api: TestClient, admin: User, agenda: list[Contact], clients: list[Client]
    ) -> None:
        login(api, admin.email)

        params = {"pageSize": 50, "clientId": str(clients[0].id)}
        items = api.get(URL, params=params).json()["items"]

        assert [item["fullName"] for item in items] == ["Ioana Marinescu", "Andrei Georgescu"]
        assert items[0]["isPrimary"] is True

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("marinescu", {"Ioana Marinescu"}),
            ("serban", {"Maria Șerban"}),  # fără diacritice, ca peste tot
            ("0722", {"Ioana Marinescu"}),
            ("alfa.test", {"Ioana Marinescu", "Andrei Georgescu"}),
        ],
    )
    def test_search_covers_person_phone_and_email(
        self,
        api: TestClient,
        admin: User,
        agenda: list[Contact],
        query: str,
        expected: set[str],
    ) -> None:
        """Cine deschide agenda nu știe în care câmp stă ce caută."""
        login(api, admin.email)

        items = api.get(URL, params={"q": query, "pageSize": 50}).json()["items"]

        assert {item["fullName"] for item in items} == expected

    def test_search_also_covers_the_firm(
        self, api: TestClient, admin: User, agenda: list[Contact], clients: list[Client]
    ) -> None:
        login(api, admin.email)

        items = api.get(URL, params={"q": clients[1].name, "pageSize": 50}).json()["items"]

        assert {item["fullName"] for item in items} == {"Maria Șerban"}

    def test_a_departed_colleague_is_not_offered(
        self, api: TestClient, admin: User, agenda: list[Contact]
    ) -> None:
        """Implicit, agenda nu propune să suni pe cineva care a plecat."""
        login(api, admin.email)

        default = api.get(URL, params={"pageSize": 50}).json()["items"]
        everyone = api.get(URL, params={"pageSize": 50, "includeInactive": "true"}).json()["items"]

        assert "Fost Angajat" not in {item["fullName"] for item in default}
        assert "Fost Angajat" in {item["fullName"] for item in everyone}

    def test_another_office_sees_nothing(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        agenda: list[Contact],
    ) -> None:
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival6.test", role=RoleCode.ADMIN)
        db.commit()
        login(api, stranger.email)

        assert api.get(URL, params={"pageSize": 50}).json()["items"] == []

    def test_reading_the_address_book_needs_clients_read(
        self, api: TestClient, agenda: list[Contact]
    ) -> None:
        assert api.get(URL).status_code == 401
