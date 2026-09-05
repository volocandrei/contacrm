"""Termenele de depunere, pe API.

Ce apără testele, în ordinea importanței:

1. **Un termen ratat rămâne pe ecran.** Este singurul lucru pe care aplicația
   chiar nu are voie să-l piardă: o declarație nedepusă la timp costă bani, iar
   un ecran care o lasă să iasă din fereastră o ascunde exact când contează.
2. **Depusul nu dispare.** O listă care ar arăta doar restanțele arată identic
   când munca e gata și când clientul nu are nimic configurat.
3. **Marcarea este idempotentă** și nu rescrie cine a depus prima oară.
4. **Termenele sunt ale cabinetului.** Se pot schimba din aplicație, iar
   schimbarea se vede imediat în ce are de depus.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ObligationFrequency
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.obligation import ClientObligation, ObligationType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
URL = "/api/v1/obligations"


@pytest.fixture
def roles(db: Session) -> dict[RoleCode, Role]:
    permissions: dict[str, Permission] = {}
    for perms in ROLE_PERMISSIONS.values():
        for perm in perms:
            permissions.setdefault(perm.value, Permission(code=perm.value))
    db.add_all(permissions.values())
    db.flush()

    created: dict[RoleCode, Role] = {}
    for code, perms in ROLE_PERMISSIONS.items():
        role = Role(
            code=code.value,
            name=ROLE_LABEL[code],
            permissions=[permissions[p.value] for p in perms],
        )
        db.add(role)
        created[code] = role
    db.flush()
    return created


@pytest.fixture
def org(db: Session) -> Organization:
    row = Organization(name="Cabinet Demo SRL")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def vat(db: Session, org: Organization) -> ObligationType:
    row = ObligationType(
        organization_id=org.id,
        code="D300",
        label="D300 — decont TVA",
        frequency=ObligationFrequency.MONTHLY,
        months_after=1,
        deadline_day=25,
    )
    db.add(row)
    db.flush()
    return row


def make_user(
    db: Session, org: Organization, roles: dict[RoleCode, Role], *, email: str, role: RoleCode
) -> User:
    from app.core.security import hash_password

    user = User(
        organization_id=org.id,
        email=email,
        full_name="Ioana Marinescu",
        password_hash=hash_password(PASSWORD),
        roles=[roles[role]],
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    response = api.post("/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD})
    assert response.status_code == 200
    return api


def assign(
    db: Session, client: Client, obligation: ObligationType, *, configured_days_ago: int = 200
) -> None:
    """Leagă clientul de declarație, ca și cum ar fi fost configurată demult.

    Implicit **în urmă**, fiindcă altfel niciun test nu ar avea termene trecute:
    aplicația nu produce termene dinainte de ziua configurării. Un cabinet care
    folosește aplicația de o jumătate de an este cazul obișnuit; cel care tocmai
    a instalat-o are testele lui, în `TestSinceWhenTheApplicationMaySpeak`.
    """
    db.add(
        ClientObligation(
            organization_id=client.organization_id,
            client_id=client.id,
            obligation_type_id=obligation.id,
            created_at=datetime.now(UTC) - timedelta(days=configured_days_ago),
        )
    )
    db.flush()


def fetch(api: TestClient, **params: str) -> list[dict[str, Any]]:
    response = api.get(URL, params=params)
    assert response.status_code == 200, response.text
    payload: list[dict[str, Any]] = response.json()
    return payload


@pytest.mark.usefixtures("as_admin")
class TestWhatIsDue:
    def test_a_client_with_a_declaration_gets_its_deadlines(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)

        rows = fetch(api)

        assert rows, "un client cu declarație configurată trebuie să aibă termene"
        assert {row["code"] for row in rows} == {"D300"}
        assert all(row["clientName"] == "Alfa Conta SRL" for row in rows)

    def test_a_client_without_declarations_has_nothing_due(
        self, api: TestClient, client_row: Client, vat: ObligationType
    ) -> None:
        """Fără atribuire nu există termen. Catalogul singur nu obligă pe nimeni."""
        assert fetch(api) == []

    def test_a_missed_deadline_stays_on_the_screen(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Singurul lucru pe care aplicația nu are voie să-l piardă.

        Fereastra implicită pornește din urmă tocmai de aceea: un termen ratat nu
        se rezolvă trecând timpul.
        """
        assign(db, client_row, vat)

        overdue = [row for row in fetch(api) if row["isOverdue"]]

        assert overdue, "termenele deja trecute și nedepuse trebuie să rămână vizibile"
        assert all(row["filedAt"] is None for row in overdue)

    def test_the_rows_come_in_deadline_order(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)

        deadlines = [row["deadline"] for row in fetch(api)]

        assert deadlines == sorted(deadlines)

    def test_a_reversed_window_is_refused(self, api: TestClient) -> None:
        """Zero rezultate s-ar citi ca „nu am nimic de depus"."""
        response = api.get(URL, params={"since": "2026-10-01", "until": "2026-09-01"})

        assert response.status_code == 422

    def test_another_organizations_deadlines_never_appear(
        self, api: TestClient, db: Session, roles: dict[RoleCode, Role]
    ) -> None:
        """§72: izolarea stă prima și nu este opțională."""
        stranger = Organization(name="Alt Cabinet SRL")
        db.add(stranger)
        db.flush()
        their_client = Client(organization_id=stranger.id, name="Terț SRL")
        their_type = ObligationType(
            organization_id=stranger.id,
            code="D300",
            label="D300",
            frequency=ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
        )
        db.add_all([their_client, their_type])
        db.flush()
        assign(db, their_client, their_type)

        assert fetch(api) == []


@pytest.mark.usefixtures("as_admin")
class TestSinceWhenTheApplicationMaySpeak:
    """Aplicația nu inventează restanțe.

    Un cabinet care instalează azi a depus, evident, și luna trecută — dar
    aplicația nu are de unde ști, fiindcă nu exista. Prima variantă arăta 52 de
    rânduri roșii pe o instalare proaspătă: nu informație, ci o afirmație despre
    ceva ce nu a văzut. Găsit uitându-mă la ecran, nu la cod.
    """

    def test_nothing_is_due_from_before_the_declaration_was_configured(
        self, api: TestClient, client_row: Client, vat: ObligationType
    ) -> None:
        api.put(f"{URL}/clients/{client_row.id}", json={"obligationTypeIds": [str(vat.id)]})

        today = datetime.now(UTC).date()
        rows = fetch(api)

        assert rows, "configurarea de azi trebuie totuși să producă termenele viitoare"
        assert all(date.fromisoformat(row["deadline"]) >= today for row in rows)
        assert not any(row["isOverdue"] for row in rows)

    def test_a_closed_period_whose_deadline_has_not_passed_is_kept(
        self, api: TestClient, client_row: Client, vat: ObligationType
    ) -> None:
        """Se compară cu **termenul**, nu cu perioada.

        Configurat azi, decontul lunii trecute are termen peste câteva săptămâni
        și este al cabinetului.
        """
        api.put(f"{URL}/clients/{client_row.id}", json={"obligationTypeIds": [str(vat.id)]})

        today = datetime.now(UTC).date()
        # Perioada care s-a încheiat cel mai recent, adică luna trecută.
        previous = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

        periods = {row["period"] for row in fetch(api)}
        # Termenul ei este pe 25 luna aceasta: dacă a trecut deja, nu are ce
        # căuta în listă — regula rămâne aceeași, doar calendarul o mută.
        expected = date(today.year, today.month, 25) >= today
        assert (previous in periods) is expected


@pytest.mark.usefixtures("as_admin")
class TestMarkingAFiling:
    def _first(self, api: TestClient) -> dict[str, Any]:
        rows = fetch(api)
        assert rows
        return rows[0]

    def test_marking_it_filed_shows_up_in_the_list(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)
        row = self._first(api)

        response = api.post(
            f"{URL}/filings",
            json={
                "clientId": str(client_row.id),
                "obligationTypeId": str(vat.id),
                "period": row["period"],
            },
        )
        assert response.status_code == 201, response.text

        after = next(entry for entry in fetch(api) if entry["period"] == row["period"])
        assert after["filedAt"] is not None
        assert after["filedByName"] == "Ioana Marinescu"
        assert after["isOverdue"] is False

    def test_a_filed_period_stays_in_the_list(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """O listă care ar ascunde depusele arată identic cu una goală.

        „Totul e gata" și „clientul nu are nimic configurat" cer lucruri opuse.
        """
        assign(db, client_row, vat)
        before = len(fetch(api))
        row = self._first(api)

        api.post(
            f"{URL}/filings",
            json={
                "clientId": str(client_row.id),
                "obligationTypeId": str(vat.id),
                "period": row["period"],
            },
        )

        assert len(fetch(api)) == before

    def test_marking_twice_does_not_create_a_second_filing(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Două apăsări pe același buton nu sunt două depuneri."""
        assign(db, client_row, vat)
        row = self._first(api)
        body = {
            "clientId": str(client_row.id),
            "obligationTypeId": str(vat.id),
            "period": row["period"],
        }

        first = api.post(f"{URL}/filings", json=body)
        second = api.post(f"{URL}/filings", json=body)

        assert first.status_code == 201
        assert second.status_code == 201
        # Aceeași depunere, nu una nouă: cine a depus rămâne cine a depus.
        #
        # Comparate ca **momente**, nu ca text: prima trece prin obiectul abia
        # creat (UTC), a doua prin cel recitit din baza de date, care vine în
        # fusul conexiunii. Același instant, două scrieri — un test pe șiruri ar
        # fi căzut pentru un motiv care nu are legătură cu ce apără.
        assert datetime.fromisoformat(first.json()["filedAt"]) == datetime.fromisoformat(
            second.json()["filedAt"]
        )

    def test_unmarking_puts_it_back_as_not_filed(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Cineva a apăsat pe rândul greșit."""
        assign(db, client_row, vat)
        row = self._first(api)
        body = {
            "clientId": str(client_row.id),
            "obligationTypeId": str(vat.id),
            "period": row["period"],
        }
        api.post(f"{URL}/filings", json=body)

        response = api.request("DELETE", f"{URL}/filings", params=body)

        assert response.status_code == 204
        after = next(entry for entry in fetch(api) if entry["period"] == row["period"])
        assert after["filedAt"] is None

    def test_unmarking_something_never_filed_is_a_404(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)

        response = api.request(
            "DELETE",
            f"{URL}/filings",
            params={
                "clientId": str(client_row.id),
                "obligationTypeId": str(vat.id),
                "period": "2026-01",
            },
        )

        assert response.status_code == 404

    def test_a_client_of_another_organization_is_a_404_not_a_403(
        self, api: TestClient, db: Session, vat: ObligationType
    ) -> None:
        """§72: existența nu se confirmă nici măcar printr-un refuz."""
        stranger = Organization(name="Alt Cabinet SRL")
        db.add(stranger)
        db.flush()
        theirs = Client(organization_id=stranger.id, name="Terț SRL")
        db.add(theirs)
        db.flush()

        response = api.post(
            f"{URL}/filings",
            json={
                "clientId": str(theirs.id),
                "obligationTypeId": str(vat.id),
                "period": "2026-08",
            },
        )

        assert response.status_code == 404


@pytest.mark.usefixtures("as_admin")
class TestMarkingManyAtOnce:
    """Un cabinet depune D300 pentru douăzeci de clienți într-o singură ședință.

    Bifate una câte una, asta înseamnă douăzeci de apăsări și douăzeci de
    reîncărcări ale listei.
    """

    def test_a_stack_of_filings_goes_in_at_once(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)
        rows = fetch(api)[:3]
        assert len(rows) == 3

        response = api.post(
            f"{URL}/filings/bulk",
            json={
                "filings": [
                    {
                        "clientId": row["clientId"],
                        "obligationTypeId": row["obligationTypeId"],
                        "period": row["period"],
                    }
                    for row in rows
                ]
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["marked"] == 3
        assert response.json()["failed"] == []
        filed = {row["period"] for row in fetch(api) if row["filedAt"] is not None}
        assert {row["period"] for row in rows} <= filed

    def test_one_bad_row_does_not_stop_the_others(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Omul a apăsat un buton, dar a confirmat douăzeci de depuneri."""
        assign(db, client_row, vat)
        good = fetch(api)[0]

        response = api.post(
            f"{URL}/filings/bulk",
            json={
                "filings": [
                    {
                        "clientId": good["clientId"],
                        "obligationTypeId": str(uuid.uuid4()),
                        "period": good["period"],
                    },
                    {
                        "clientId": good["clientId"],
                        "obligationTypeId": good["obligationTypeId"],
                        "period": good["period"],
                    },
                ]
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["marked"] == 1
        assert len(body["failed"]) == 1

    def test_marking_the_same_row_twice_stays_one_filing(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Cine a depus rămâne cine a depus."""
        assign(db, client_row, vat)
        row = fetch(api)[0]
        entry = {
            "clientId": row["clientId"],
            "obligationTypeId": row["obligationTypeId"],
            "period": row["period"],
        }

        api.post(f"{URL}/filings/bulk", json={"filings": [entry]})
        first = next(e for e in fetch(api) if e["period"] == row["period"])["filedAt"]
        api.post(f"{URL}/filings/bulk", json={"filings": [entry]})

        after = next(e for e in fetch(api) if e["period"] == row["period"])["filedAt"]
        assert after == first

    def test_an_empty_stack_is_refused(self, api: TestClient) -> None:
        """Un teanc gol este o greșeală de ecran, nu o cerere validă."""
        assert api.post(f"{URL}/filings/bulk", json={"filings": []}).status_code == 422

    def test_an_operator_may_not_mark_a_stack_either(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        operator = make_user(
            db, org, roles, email="operator2@contacrm.test", role=RoleCode.OPERATOR
        )
        api.post("/api/v1/auth/login", json={"email": operator.email, "password": PASSWORD})

        response = api.post(
            f"{URL}/filings/bulk",
            json={
                "filings": [
                    {
                        "clientId": str(uuid.uuid4()),
                        "obligationTypeId": str(uuid.uuid4()),
                        "period": "2026-08",
                    }
                ]
            },
        )

        assert response.status_code == 403


@pytest.mark.usefixtures("as_admin")
class TestTheCatalogue:
    def test_the_deadline_belongs_to_the_office_not_to_the_application(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        """Aplicația nu pretinde că știe legea.

        Cine constată că un termen este altul îl schimbă din aplicație, iar
        schimbarea se vede imediat în ce are de depus — fără deploy.
        """
        assign(db, client_row, vat)
        before = {row["period"]: row["deadline"] for row in fetch(api)}

        response = api.patch(f"{URL}/types/{vat.id}", json={"deadlineDay": 15})
        assert response.status_code == 200, response.text

        after = {row["period"]: row["deadline"] for row in fetch(api)}
        moved = [period for period in before if after.get(period) != before[period]]
        assert moved, "schimbarea zilei trebuie să mute termenele"
        assert all(entry["deadline"].endswith("-15") for entry in fetch(api))

    def test_a_deactivated_declaration_stops_producing_deadlines(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)
        assert fetch(api)

        api.patch(f"{URL}/types/{vat.id}", json={"isActive": False})

        assert fetch(api) == []

    def test_a_deactivated_declaration_stays_in_the_catalogue(
        self, api: TestClient, vat: ObligationType
    ) -> None:
        """Una care dispare când o dezactivezi nu se mai poate reactiva."""
        api.patch(f"{URL}/types/{vat.id}", json={"isActive": False})

        codes = [row["code"] for row in api.get(f"{URL}/types").json()]

        assert "D300" in codes

    def test_the_code_cannot_be_changed(self, api: TestClient, vat: ObligationType) -> None:
        """Codul leagă depunerile deja existente. Redenumit, ar rupe istoricul."""
        response = api.patch(f"{URL}/types/{vat.id}", json={"code": "ALTCEVA"})

        assert response.status_code == 200
        assert api.get(f"{URL}/types").json()[0]["code"] == "D300"


@pytest.mark.usefixtures("as_admin")
class TestWhoFilesWhat:
    def test_the_set_is_replaced_not_appended(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        vat: ObligationType,
    ) -> None:
        """Ce se trimite înapoi este starea de pe ecran.

        O rută care doar adaugă ar face imposibilă scoaterea unei declarații.
        """
        other = ObligationType(
            organization_id=org.id,
            code="D112",
            label="D112",
            frequency=ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
        )
        db.add(other)
        db.flush()

        api.put(
            f"{URL}/clients/{client_row.id}",
            json={"obligationTypeIds": [str(vat.id), str(other.id)]},
        )
        response = api.put(
            f"{URL}/clients/{client_row.id}", json={"obligationTypeIds": [str(other.id)]}
        )

        assert response.status_code == 200
        assert [row["code"] for row in response.json()] == ["D112"]

    def test_an_empty_set_clears_everything(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)

        response = api.put(f"{URL}/clients/{client_row.id}", json={"obligationTypeIds": []})

        assert response.json() == []
        assert fetch(api) == []


class TestPermissions:
    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        assert api.get(URL).status_code == 401

    def test_an_operator_may_read_but_not_mark(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Marcarea unei depuneri este o decizie contabilă, nu una de operare."""
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        api.post("/api/v1/auth/login", json={"email": operator.email, "password": PASSWORD})

        assert api.get(URL).status_code == 200
        assert (
            api.post(
                f"{URL}/filings",
                json={
                    "clientId": str(uuid.uuid4()),
                    "obligationTypeId": str(uuid.uuid4()),
                    "period": "2026-08",
                },
            ).status_code
            == 403
        )


@pytest.mark.usefixtures("as_admin")
class TestTheWindowItself:
    def test_an_explicit_window_narrows_the_list(
        self, api: TestClient, db: Session, client_row: Client, vat: ObligationType
    ) -> None:
        assign(db, client_row, vat)
        today = datetime.now(UTC).date()

        rows = fetch(
            api,
            since=today.isoformat(),
            until=(today + timedelta(days=1)).isoformat(),
        )

        assert all(
            today <= date.fromisoformat(row["deadline"]) <= today + timedelta(days=1)
            for row in rows
        )
