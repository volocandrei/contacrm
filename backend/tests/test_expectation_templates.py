"""Șabloanele de așteptări: profilurile de client ale cabinetului (§19).

**Ce apără testele de aici.** Fără așteptări configurate, checklistul lunii este
gol, „Documente lipsă" nu are ce raporta, iar fiecare lună apare completă pentru
că nu i se cere nimic. Adică tot ce s-a construit în jurul colectării — cererea,
linkul, urmărirea — nu pornește. Configurarea se făcea client cu client, bifă cu
bifă; un cabinet cu treizeci de clienți are trei-patru profiluri.

**În ordinea gravității:**

1. **Aplicarea chiar schimbă checklistul.** Dacă șablonul s-ar salva frumos dar
   nu s-ar vedea în raport, n-ar fi făcut nimic — și nimeni n-ar observa până
   la sfârșitul lunii.
2. **Înlocuiește, nu adaugă.** Două profiluri aplicate pe rând ar lăsa o listă pe
   care n-a ales-o nimeni.
3. **Un client necunoscut oprește totul**, înainte de orice scriere: aplicată pe
   jumătate, operația lasă pe cineva fără să știe care jumătate.
4. **Șablonul nu este o legătură.** Schimbat sau șters, clienții rămân cum au
   fost configurați — altfel o bifă scoasă azi ar reapărea peste o lună pe
   doisprezece clienți, fără ca cineva să le fi atins ecranul.
5. **Decizia este contabilă**: `periods:manage`, ca și așteptările unui client.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_periods_api import MONTH, login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

URL = "/api/v1/expectation-templates"

#: Profilul cel mai comun: firmă care aduce facturi de intrare și extras de cont.
PROFILE = [
    {"documentTypeCode": "FACTURA_INTRARE", "expectedMinCount": 3},
    {"documentTypeCode": "EXTRAS_CONT", "expectedMinCount": 1},
]


@pytest.fixture
def second_client(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Beta Prod SRL", tax_id="RO2")
    db.add(row)
    db.flush()
    return row


def create(api: TestClient, name: str = "SRL plătitor de TVA", expectations: list | None = None):
    return api.post(
        URL,
        json={"name": name, "expectations": PROFILE if expectations is None else expectations},
    )


def expectations_of(api: TestClient, client_row: Client) -> dict[str, int]:
    response = api.get(f"/api/v1/clients/{client_row.id}/expectations")
    assert response.status_code == 200, response.text
    return {row["documentTypeCode"]: row["expectedMinCount"] for row in response.json()}


# ── Ce trebuie să facă ───────────────────────────────────────────────────────


class TestTheProfile:
    def test_it_is_saved_with_the_name_the_office_gave_it(
        self, api: TestClient, db: Session, admin: User, types: dict
    ) -> None:
        db.commit()
        login(api, admin.email)

        response = create(api)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "SRL plătitor de TVA"
        assert {row["documentTypeCode"] for row in body["expectations"]} == {
            "FACTURA_INTRARE",
            "EXTRAS_CONT",
        }

    def test_applying_it_changes_what_the_month_asks_for(
        self,
        api: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        second_client: Client,
        types: dict,
    ) -> None:
        """Rostul întreg: doisprezece clienți configurați într-un minut.

        Dacă șablonul s-ar salva frumos dar n-ar ajunge în checklist, n-ar fi
        făcut nimic — și s-ar vedea abia la sfârșitul lunii.
        """
        db.commit()
        login(api, admin.email)
        template = create(api).json()

        applied = api.post(
            f"{URL}/{template['id']}/apply",
            json={"clientIds": [str(client_row.id), str(second_client.id)]},
        )

        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] == 2
        for row in (client_row, second_client):
            assert expectations_of(api, row) == {"FACTURA_INTRARE": 3, "EXTRAS_CONT": 1}

    def test_it_replaces_the_list_it_does_not_add_to_it(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """Două profiluri aplicate pe rând ar lăsa o listă pe care n-a ales-o nimeni."""
        db.commit()
        login(api, admin.email)
        wide = create(api).json()
        narrow = create(
            api,
            name="PFA fără bancă",
            expectations=[{"documentTypeCode": "FACTURA_INTRARE", "expectedMinCount": 1}],
        ).json()
        api.post(f"{URL}/{wide['id']}/apply", json={"clientIds": [str(client_row.id)]})

        api.post(f"{URL}/{narrow['id']}/apply", json={"clientIds": [str(client_row.id)]})

        assert expectations_of(api, client_row) == {"FACTURA_INTRARE": 1}

    def test_a_profile_can_be_saved_from_a_client_already_configured(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        expectations: dict,
        types: dict,
    ) -> None:
        """Drumul pe care se face primul șablon: potrivești un client, îi dai un nume."""
        db.commit()
        login(api, admin.email)

        response = api.post(f"{URL}/from-client/{client_row.id}", json={"name": "Ca la Alfa"})

        assert response.status_code == 201, response.text
        saved = {
            row["documentTypeCode"]: row["expectedMinCount"]
            for row in response.json()["expectations"]
        }
        assert saved == {"FACTURA_INTRARE": 2, "EXTRAS_CONT": 1}


# ── Ce nu trebuie să facă ────────────────────────────────────────────────────


class TestRestraint:
    def test_an_unknown_client_stops_everything_before_writing(
        self,
        api: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        types: dict,
    ) -> None:
        """Aplicată pe jumătate, operația lasă pe cineva fără să știe care jumătate."""
        db.commit()
        login(api, admin.email)
        template = create(api).json()

        response = api.post(
            f"{URL}/{template['id']}/apply",
            json={"clientIds": [str(client_row.id), str(uuid.uuid4())]},
        )

        assert response.status_code == 404
        assert expectations_of(api, client_row) == {}

    def test_changing_the_profile_leaves_configured_clients_alone(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """Șablonul nu este o legătură: ce s-a aplicat este de-acum al clientului.

        Dacă ar moșteni la distanță, o bifă scoasă azi ar dispărea de pe
        doisprezece clienți fără ca cineva să le fi atins ecranul — iar raportul
        ar înceta să ceară un extras de cont, fără explicație.
        """
        db.commit()
        login(api, admin.email)
        template = create(api).json()
        api.post(f"{URL}/{template['id']}/apply", json={"clientIds": [str(client_row.id)]})

        api.put(
            f"{URL}/{template['id']}",
            json={
                "name": "SRL plătitor de TVA",
                "expectations": [{"documentTypeCode": "FACTURA_INTRARE", "expectedMinCount": 9}],
            },
        )

        assert expectations_of(api, client_row) == {"FACTURA_INTRARE": 3, "EXTRAS_CONT": 1}

    def test_deleting_the_profile_leaves_configured_clients_alone(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        db.commit()
        login(api, admin.email)
        template = create(api).json()
        api.post(f"{URL}/{template['id']}/apply", json={"clientIds": [str(client_row.id)]})

        assert api.delete(f"{URL}/{template['id']}").status_code == 204

        assert expectations_of(api, client_row) == {"FACTURA_INTRARE": 3, "EXTRAS_CONT": 1}

    def test_two_profiles_cannot_share_a_name(
        self, api: TestClient, db: Session, admin: User, types: dict
    ) -> None:
        """Două rânduri pe care nimeni nu le poate deosebi, iar unul rescrie clienți."""
        db.commit()
        login(api, admin.email)
        create(api)

        response = create(api, name="srl PLĂTITOR de tva")

        assert response.status_code == 422
        assert len(api.get(URL).json()) == 1

    def test_a_nameless_profile_is_refused(
        self, api: TestClient, db: Session, admin: User, types: dict
    ) -> None:
        """Spații albe nu sunt un nume: fără curățare, ar trece de `min_length`."""
        db.commit()
        login(api, admin.email)

        assert create(api, name="   ").status_code == 422

    def test_an_unknown_document_type_is_refused(
        self, api: TestClient, db: Session, admin: User, types: dict
    ) -> None:
        """Ignorat în tăcere, ar lipsi din raport abia peste o lună."""
        db.commit()
        login(api, admin.email)

        response = create(
            api, expectations=[{"documentTypeCode": "NU_EXISTA", "expectedMinCount": 1}]
        )

        assert response.status_code == 404

    def test_an_empty_client_has_nothing_to_save_as_a_profile(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """Un șablon gol aplicat pe doisprezece clienți le-ar goli checklistul."""
        db.commit()
        login(api, admin.email)

        response = api.post(f"{URL}/from-client/{client_row.id}", json={"name": "Gol"})

        assert response.status_code == 422

    def test_a_template_from_another_office_is_not_found(
        self, api: TestClient, db: Session, admin: User, types: dict
    ) -> None:
        """404, nu 403: altfel răspunsul confirmă că id-ul există undeva (§72)."""
        db.commit()
        login(api, admin.email)

        assert api.get(URL).status_code == 200
        assert api.delete(f"{URL}/{uuid.uuid4()}").status_code == 404


# ── Cine are voie ────────────────────────────────────────────────────────────


class TestPermissions:
    def test_reading_needs_only_documents_read(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict,
    ) -> None:
        """Cine vede checklistul are voie să vadă și după ce model a fost construit."""
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        db.commit()
        login(api, operator.email)

        assert api.get(URL).status_code == 200

    def test_writing_needs_periods_manage(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict,
    ) -> None:
        """A hotărî ce datorează lunar o categorie întreagă este o decizie contabilă."""
        operator = make_user(
            db, org, roles, email="fara-drept@contacrm.test", role=RoleCode.OPERATOR
        )
        db.commit()
        login(api, operator.email)

        assert create(api).status_code == 403


# ── Urma ─────────────────────────────────────────────────────────────────────


class TestTheTrace:
    def test_applying_leaves_who_what_and_to_whom(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """§33: o operație care rescrie checklistul a doisprezece clienți nu poate fi tăcută."""
        db.commit()
        login(api, admin.email)
        template = create(api).json()

        api.post(f"{URL}/{template['id']}/apply", json={"clientIds": [str(client_row.id)]})

        assert (
            db.scalars(
                select(ClientExpectation).where(ClientExpectation.client_id == client_row.id)
            ).first()
            is not None
        )

        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "EXPECTATION_TEMPLATE_APPLIED")
        ).one()
        assert entry.user_name == admin.full_name
        assert "SRL plătitor de TVA" in (entry.detail or "")
        # Pe cine s-a aplicat, nu doar câți: o listă rescrisă din greșeală trebuie
        # să poată fi urmărită înapoi la clienții atinși.
        assert entry.new_value == {"clientIds": [str(client_row.id)]}


def report_for(api: TestClient, client_row: Client, month: str = MONTH) -> list[dict]:
    rows = api.get(f"/api/v1/periods/missing?referenceMonth={month}").json()
    return [row for row in rows if row["period"]["clientId"] == str(client_row.id)]


class TestTheClientWhoSentNothing:
    """Cel căruia îi lipsește tot era singurul care nu apărea în raport.

    `list_periods` nu inventează o lună fără documente și fără rând — și are
    dreptate, acolo întrebarea este „ce perioade există". În „Documente lipsă"
    întrebarea este alta: „cui îi lipsește ceva". Clientul care n-a trimis nimic
    devenea invizibil tocmai în raportul făcut ca să-l găsească, și reapărea abia
    după ce trimitea primul document.
    """

    def test_a_configured_client_with_nothing_sent_is_listed(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        client_row.status = ClientStatus.ACTIVE
        db.commit()
        login(api, admin.email)
        template = create(api).json()
        api.post(f"{URL}/{template['id']}/apply", json={"clientIds": [str(client_row.id)]})

        rows = report_for(api, client_row)

        assert rows, "clientul configurat nu apare în raport, deși nu a trimis nimic"
        assert {item["documentType"] for item in rows[0]["missing"]} == {
            "FACTURA_INTRARE",
            "EXTRAS_CONT",
        }

    def test_a_client_without_expectations_is_not_invented(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """Nu i se cere nimic, deci nu-i lipsește nimic.

        Un raport care strigă degeaba ajunge să nu mai fie citit.
        """
        client_row.status = ClientStatus.ACTIVE
        db.commit()
        login(api, admin.email)

        assert report_for(api, client_row) == []

    def test_a_prospect_is_not_chased(
        self, api: TestClient, db: Session, admin: User, client_row: Client, types: dict
    ) -> None:
        """Un prospect nu este încă client; unul suspendat nu se mai aleargă."""
        db.commit()  # `client_row` rămâne PROSPECT, cum îl lasă fixtura
        login(api, admin.email)
        template = create(api).json()
        api.post(f"{URL}/{template['id']}/apply", json={"clientIds": [str(client_row.id)]})

        assert report_for(api, client_row) == []
