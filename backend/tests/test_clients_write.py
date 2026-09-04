"""Adăugarea și modificarea clienților și a contactelor lor (§61).

CRM-ul a fost de la început numai de citire, iar auditul de producție a arătat
consecința: un cabinet nou nu putea adăuga **niciun** client, deci nu putea lega
niciun dosar din OneDrive și niciun email nu putea fi atribuit.

Ce se verifică aici, dincolo de „merge": cele două forme de coliziune care nu
produc nicio eroare, ci doar opresc tăcut preluarea automată — același CUI scris
în două feluri, și aceeași adresă de email la doi clienți.
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
from app.models.client import Client, Contact
from app.models.organization import Organization
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

# Fixture-urile `roles`, `org`, `admin` și `clients` vin din `test_crm_api`; sunt
# aceleași date, iar o a doua copie a lor s-ar despărți de prima la prima
# schimbare.
pytest_plugins = ("tests.test_crm_api",)


def create(api: TestClient, **fields: object) -> object:
    return api.post("/api/v1/clients", json=fields)


# ── Crearea ──────────────────────────────────────────────────────────────────


class TestCreate:
    def test_the_minimum_is_a_name(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Un prospect care nu și-a trimis încă datele are drept la un rând."""
        login(api, admin.email)
        response = create(api, name="Client Nou SRL")

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Client Nou SRL"
        assert body["taxId"] is None
        # ACTIV, nu PROSPECT: cine adaugă un client îi ține contabilitatea.
        assert body["status"] == ClientStatus.ACTIVE.value

        stored = db.scalars(select(Client).where(Client.id == uuid.UUID(body["id"]))).one()
        assert stored.organization_id == org.id

    def test_an_empty_tax_id_is_absent_not_empty(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        """`''` ar intra în indexul unic parțial și al doilea client fără CUI ar cădea."""
        login(api, admin.email)
        assert create(api, name="Fără CUI Unu SRL", taxId="   ").status_code == 201
        assert create(api, name="Fără CUI Doi SRL", taxId="").status_code == 201

        stored = db.scalars(select(Client).where(Client.name.like("Fără CUI%"))).all()
        assert [client.tax_id for client in stored] == [None, None]

    def test_a_name_of_spaces_is_refused(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        response = create(api, name="   ")
        assert response.status_code == 422
        assert "name" in response.json()["details"]

    def test_the_creation_is_written_in_the_audit_log(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        login(api, admin.email)
        body = create(api, name="De Auditat SRL", taxId="RO14399840").json()

        entry = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == body["id"], AuditLog.action == "CLIENT_CREATED"
            )
        ).one()
        assert entry.user_name == admin.full_name
        assert entry.new_value is not None
        assert entry.new_value["tax_id"] == "RO14399840"

    def test_an_accountant_from_another_office_is_refused(
        self, api: TestClient, db: Session, admin: User, roles: dict[RoleCode, Role]
    ) -> None:
        """Altfel un client ar putea fi atribuit unui utilizator care nu are ce căuta."""
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="strain@rival.test", role=RoleCode.ACCOUNTANT)

        login(api, admin.email)
        response = create(api, name="Atribuit Greșit SRL", assignedAccountantId=str(stranger.id))
        assert response.status_code == 422
        assert "assignedAccountantId" in response.json()["details"]


# ── CUI: aceeași firmă scrisă în două feluri ─────────────────────────────────


class TestTaxIdUniqueness:
    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("RO14399840", "RO14399840"),
            # `RO14399840` și `14399840` sunt același cod. Indexul unic din migrare
            # compară textul brut, deci le-ar accepta pe amândouă — iar apoi
            # identificarea automată ar găsi doi candidați și n-ar mai atribui
            # niciun document.
            ("RO14399840", "14399840"),
            ("14399840", "RO 14.399.840"),
        ],
        ids=["identic", "cu-si-fara-RO", "cu-spatii-si-puncte"],
    )
    def test_the_same_company_cannot_be_added_twice(
        self, api: TestClient, admin: User, first: str, second: str
    ) -> None:
        login(api, admin.email)
        assert create(api, name="Prima Intrare SRL", taxId=first).status_code == 201

        response = create(api, name="A Doua Intrare SRL", taxId=second)
        assert response.status_code == 409
        assert "Prima Intrare SRL" in response.json()["message"]

    def test_a_client_keeps_its_own_tax_id_when_edited(self, api: TestClient, admin: User) -> None:
        """Verificarea nu are voie să se lovească de clientul pe care îl modifică."""
        login(api, admin.email)
        created = create(api, name="Se Editează SRL", taxId="RO14399840").json()

        response = api.patch(f"/api/v1/clients/{created['id']}", json={"name": "Alt Nume SRL"})
        assert response.status_code == 200, response.text
        assert response.json()["taxId"] == "RO14399840"


# ── Modificarea ──────────────────────────────────────────────────────────────


class TestUpdate:
    def test_untouched_fields_stay(self, api: TestClient, admin: User) -> None:
        """Un formular care trimite doar statusul nu are voie să golească CUI-ul."""
        login(api, admin.email)
        created = create(
            api, name="Complet SRL", taxId="RO14399840", address="Str. Exemplu 1"
        ).json()

        response = api.patch(
            f"/api/v1/clients/{created['id']}", json={"status": ClientStatus.INACTIVE.value}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == ClientStatus.INACTIVE.value
        assert body["taxId"] == "RO14399840"
        assert body["address"] == "Str. Exemplu 1"

    def test_an_explicit_null_clears_the_field(self, api: TestClient, admin: User) -> None:
        """`null` și „absent" înseamnă lucruri diferite."""
        login(api, admin.email)
        created = create(api, name="Se Golește SRL", registrationNumber="J40/1/2020").json()

        body = api.patch(
            f"/api/v1/clients/{created['id']}", json={"registrationNumber": None}
        ).json()
        assert body["registrationNumber"] is None

    def test_deactivation_keeps_the_client(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """Nu există ștergere: un client cu documente este istorie contabilă."""
        login(api, admin.email)
        target = clients[0]
        api.patch(f"/api/v1/clients/{target.id}", json={"status": ClientStatus.INACTIVE.value})

        db.refresh(target)
        assert target.deleted_at is None
        assert target.status is ClientStatus.INACTIVE

    def test_there_is_no_delete_route(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        assert api.delete(f"/api/v1/clients/{clients[0].id}").status_code == 405

    def test_an_unchanged_save_writes_nothing_to_the_audit_log(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        """Un „salvează" fără modificări nu trebuie să umple istoricul."""
        login(api, admin.email)
        created = create(api, name="Neschimbat SRL").json()
        api.patch(f"/api/v1/clients/{created['id']}", json={"name": "Neschimbat SRL"})

        entries = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == created["id"], AuditLog.action == "CLIENT_UPDATED"
            )
        ).all()
        assert entries == []


# ── Contacte ─────────────────────────────────────────────────────────────────


class TestContacts:
    def test_the_email_is_stored_in_lower_case(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """Potrivirea expeditorului se face pe adresa în litere mici (§8)."""
        login(api, admin.email)
        response = api.post(
            f"/api/v1/clients/{clients[0].id}/contacts",
            json={"fullName": "Maria Ionescu", "email": "Maria.Ionescu@Exemplu.TEST"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["email"] == "maria.ionescu@exemplu.test"

    def test_the_same_address_cannot_belong_to_two_clients(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """Adresele ambigue sunt scoase din harta de preluare, deci documentele
        primite de la adresa aceea nu ar mai ajunge la nimeni — fără nicio eroare."""
        login(api, admin.email)
        first = api.post(
            f"/api/v1/clients/{clients[0].id}/contacts",
            json={"fullName": "Primul", "email": "contact@exemplu.test"},
        )
        assert first.status_code == 201

        second = api.post(
            f"/api/v1/clients/{clients[1].id}/contacts",
            json={"fullName": "Al Doilea", "email": "CONTACT@exemplu.test"},
        )
        assert second.status_code == 409
        assert clients[0].name in second.json()["message"]

    def test_only_one_contact_is_primary(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """Cine bifează „principal" pe altcineva vrea să schimbe, nu o eroare."""
        login(api, admin.email)
        path = f"/api/v1/clients/{clients[0].id}/contacts"
        first = api.post(path, json={"fullName": "Primul", "isPrimary": True}).json()
        second = api.post(path, json={"fullName": "Al Doilea", "isPrimary": True}).json()

        stored = {
            str(contact.id): contact.is_primary
            for contact in db.scalars(select(Contact).where(Contact.client_id == clients[0].id))
        }
        assert stored[first["id"]] is False
        assert stored[second["id"]] is True

    def test_a_contact_of_another_client_is_not_reachable(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        contact = api.post(
            f"/api/v1/clients/{clients[0].id}/contacts", json={"fullName": "Al Lui"}
        ).json()

        response = api.patch(
            f"/api/v1/clients/{clients[1].id}/contacts/{contact['id']}",
            json={"fullName": "Furat"},
        )
        assert response.status_code == 404

    def test_deactivating_a_contact_keeps_it(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        contact = api.post(
            f"/api/v1/clients/{clients[0].id}/contacts",
            json={"fullName": "Plecat", "email": "plecat@exemplu.test"},
        ).json()

        body = api.patch(
            f"/api/v1/clients/{clients[0].id}/contacts/{contact['id']}",
            json={"isActive": False},
        ).json()
        assert body["isActive"] is False
        assert body["email"] == "plecat@exemplu.test"


# ── Cine are voie ────────────────────────────────────────────────────────────


class TestNotes:
    """Notițele interne pe client.

    `GET /clients/:id/notes` exista de la M4 și nu avea pereche: o listă de
    notițe pe care nimeni nu le putea scrie. Modelul avea deja `author_name`
    tocmai pentru ce se cere aici — cine a scris o notă nu trebuie să dispară
    odată cu contul lui.
    """

    def test_a_note_can_be_written_and_read_back(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)

        created = api.post(
            f"/api/v1/clients/{clients[0].id}/notes",
            json={"body": "Am vorbit cu clientul, aduce actele vineri."},
        )
        assert created.status_code == 201, created.text

        listed = api.get(f"/api/v1/clients/{clients[0].id}/notes").json()
        assert listed[0]["body"] == "Am vorbit cu clientul, aduce actele vineri."

    def test_the_author_is_kept_as_text(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """Ca nota să rămână atribuită și după ce contul autorului dispare."""
        login(api, admin.email)

        body = api.post(
            f"/api/v1/clients/{clients[0].id}/notes", json={"body": "Consemnare."}
        ).json()

        assert body["authorName"] == admin.full_name

    def test_an_empty_note_is_refused(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)

        response = api.post(f"/api/v1/clients/{clients[0].id}/notes", json={"body": "   "})
        assert response.status_code == 422

    def test_a_note_on_another_office_client_is_not_found(
        self, api: TestClient, db: Session, roles: dict[RoleCode, Role], clients: list[Client]
    ) -> None:
        """NOT_FOUND, nu FORBIDDEN: răspunsul nu confirmă că id-ul există undeva (§72)."""
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival2.test", role=RoleCode.ADMIN)
        login(api, stranger.email)

        response = api.post(
            f"/api/v1/clients/{clients[0].id}/notes", json={"body": "Nota altcuiva."}
        )
        assert response.status_code == 404

    def test_the_audit_says_a_note_was_written_not_what_it_says(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """Jurnalul nu este o a doua copie a conținutului (§33)."""
        login(api, admin.email)
        secret = "Clientul are probleme cu ANAF, discutat confidențial."
        api.post(f"/api/v1/clients/{clients[0].id}/notes", json={"body": secret})

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "CLIENT_NOTE_ADDED")).one()
        assert secret not in str(entry.detail)
        assert secret not in str(entry.new_value)

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [(RoleCode.ADMIN, True), (RoleCode.ACCOUNTANT, False), (RoleCode.VIEWER, False)],
    )
    def test_writing_a_note_needs_clients_write(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        clients: list[Client],
        role: RoleCode,
        allowed: bool,
    ) -> None:
        user = make_user(
            db, org, roles, email=f"note-{role.value.lower()}@contacrm.test", role=role
        )
        login(api, user.email)

        response = api.post(f"/api/v1/clients/{clients[0].id}/notes", json={"body": "Ceva."})
        assert (response.status_code == 201) is allowed, response.text


class TestPermissions:
    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            (RoleCode.ADMIN, True),
            (RoleCode.ACCOUNTANT, False),
            (RoleCode.OPERATOR, False),
            (RoleCode.VIEWER, False),
        ],
    )
    def test_only_clients_write_may_add_a_client(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        role: RoleCode,
        allowed: bool,
    ) -> None:
        """`clients:write` exista în hartă și nu era folosit de nicio rută."""
        user = make_user(db, org, roles, email=f"{role.value.lower()}@contacrm.test", role=role)
        login(api, user.email)

        response = create(api, name=f"Adăugat de {role.value} SRL")
        assert (response.status_code == 201) is allowed, response.text

    def test_another_office_cannot_edit_a_client(
        self, api: TestClient, db: Session, roles: dict[RoleCode, Role], clients: list[Client]
    ) -> None:
        """NOT_FOUND, nu FORBIDDEN: răspunsul nu confirmă că id-ul există undeva."""
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival.test", role=RoleCode.ADMIN)

        login(api, stranger.email)
        response = api.patch(f"/api/v1/clients/{clients[0].id}", json={"name": "Furat SRL"})
        assert response.status_code == 404
