"""CRM capăt la capăt: clienți, contacte, note, sarcini.

Comportamentul de referință este backendul simulat din
`frontend/src/api/mock/store.ts` — aceleași filtre, aceeași ordonare, aceeași
căutare insensibilă la diacritice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain.enums import ClientStatus, TaskPriority, TaskStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.client import Client, ClientNote, Contact, Tag
from app.models.organization import Organization
from app.models.task import Task
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"


# ── Pregătire ────────────────────────────────────────────────────────────────


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
    organization = Organization(name="Cabinet Contabil Demo SRL", tax_id="RO10000001")
    db.add(organization)
    db.flush()
    return organization


def make_user(
    db: Session,
    org: Organization,
    roles: dict[RoleCode, Role],
    *,
    email: str,
    role: RoleCode,
) -> User:
    user = User(
        organization_id=org.id,
        email=email,
        full_name="Ioana Marinescu" if role is RoleCode.ADMIN else "Utilizator Test",
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
def clients(db: Session, org: Organization, admin: User) -> list[Client]:
    """Include intenționat un nume cu diacritice și un client șters logic."""
    tag = Tag(organization_id=org.id, name="prioritar")
    db.add(tag)
    db.flush()

    rows = [
        Client(
            organization_id=org.id,
            name="Alfa Conta SRL",
            tax_id="RO10000101",
            registration_number="J40/1/2020",
            address="Str. Exemplu 1",
            status=ClientStatus.ACTIVE,
            assigned_accountant_id=admin.id,
            tags=[tag],
        ),
        Client(
            organization_id=org.id,
            name="Șerbănescu Impex SRL",
            tax_id="RO10000102",
            address="Bd. Sintetic 2",
            status=ClientStatus.ACTIVE,
        ),
        Client(
            organization_id=org.id,
            name="Beta Service SRL",
            tax_id="RO10000103",
            address="Str. Demo 3",
            status=ClientStatus.PROSPECT,
        ),
        Client(
            organization_id=org.id,
            name="Gama Ștearsă SRL",
            tax_id="RO10000104",
            status=ClientStatus.INACTIVE,
            deleted_at=datetime.now(UTC),
        ),
    ]
    db.add_all(rows)
    db.flush()
    return rows


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


# ── Lista de clienți ─────────────────────────────────────────────────────────


class TestClientList:
    def test_returns_the_shape_the_frontend_expects(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        body = api.get("/api/v1/clients").json()

        assert set(body) == {"items", "page", "pageSize", "total", "totalPages"}
        first = body["items"][0]
        assert set(first) == {
            "id",
            "name",
            "taxId",
            "registrationNumber",
            "address",
            "status",
            "assignedAccountantId",
            "assignedAccountantName",
            "tags",
            "lastInteractionAt",
            "createdAt",
        }

    def test_excludes_soft_deleted_clients(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        names = {c["name"] for c in api.get("/api/v1/clients").json()["items"]}
        assert "Gama Ștearsă SRL" not in names
        assert len(names) == 3

    def test_sorted_by_name_ignoring_diacritics(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """„Șerbănescu" trebuie să stea la S, nu aruncat la coada alfabetului."""
        login(api, admin.email)
        names = [c["name"] for c in api.get("/api/v1/clients").json()["items"]]
        assert names == ["Alfa Conta SRL", "Beta Service SRL", "Șerbănescu Impex SRL"]

    def test_resolves_the_accountant_name(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        alfa = next(
            c for c in api.get("/api/v1/clients").json()["items"] if c["name"].startswith("Alfa")
        )
        assert alfa["assignedAccountantName"] == "Ioana Marinescu"
        assert alfa["tags"] == ["prioritar"]

    def test_filters_by_status(self, api: TestClient, admin: User, clients: list[Client]) -> None:
        login(api, admin.email)
        body = api.get("/api/v1/clients", params={"status": "PROSPECT"}).json()
        assert [c["name"] for c in body["items"]] == ["Beta Service SRL"]

    def test_rejects_an_unknown_status(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        response = api.get("/api/v1/clients", params={"status": "INEXISTENT"})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_paginates(self, api: TestClient, admin: User, clients: list[Client]) -> None:
        login(api, admin.email)
        body = api.get("/api/v1/clients", params={"page": 2, "pageSize": 2}).json()
        assert body["page"] == 2
        assert body["pageSize"] == 2
        assert body["total"] == 3
        assert body["totalPages"] == 2
        assert len(body["items"]) == 1

    def test_rejects_an_oversized_page(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        assert api.get("/api/v1/clients", params={"pageSize": 10_000}).status_code == 422


class TestClientSearch:
    @pytest.mark.parametrize(
        "needle",
        ["Serbanescu", "șerbănescu", "SERBANESCU", "serban", "Șerbănescu"],
        ids=["fără-diacritice", "cu-diacritice", "majuscule", "parțial", "exact"],
    )
    def test_finds_a_name_with_diacritics_however_it_is_typed(
        self, api: TestClient, admin: User, clients: list[Client], needle: str
    ) -> None:
        """Comportamentul din backendul simulat: «Serban» găsește «Șerban»."""
        login(api, admin.email)
        body = api.get("/api/v1/clients", params={"q": needle}).json()
        assert [c["name"] for c in body["items"]] == ["Șerbănescu Impex SRL"]

    def test_searches_tax_id_and_address_too(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        assert api.get("/api/v1/clients", params={"q": "RO10000101"}).json()["total"] == 1
        assert api.get("/api/v1/clients", params={"q": "Bd. Sintetic"}).json()["total"] == 1

    def test_an_empty_result_is_not_an_error(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        body = api.get("/api/v1/clients", params={"q": "nu-exista-nimic"}).json()
        assert body["items"] == []
        assert body["total"] == 0
        # O listă goală are o pagină, nu zero — altfel paginarea din UI arată „1 / 0".
        assert body["totalPages"] == 1

    def test_a_wildcard_is_treated_as_text_not_as_a_pattern(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        """`%` din input nu trebuie să devină jokerul din LIKE."""
        login(api, admin.email)
        assert api.get("/api/v1/clients", params={"q": "%"}).json()["total"] == 0


# ── Detaliu, contacte, note ──────────────────────────────────────────────────


class TestClientDetail:
    def test_returns_a_client(self, api: TestClient, admin: User, clients: list[Client]) -> None:
        login(api, admin.email)
        response = api.get(f"/api/v1/clients/{clients[0].id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Alfa Conta SRL"

    def test_unknown_id_is_not_found(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        response = api.get(f"/api/v1/clients/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_a_soft_deleted_client_is_not_found(
        self, api: TestClient, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        assert api.get(f"/api/v1/clients/{clients[3].id}").status_code == 404

    def test_contacts_put_the_primary_first(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        db.add_all(
            [
                Contact(client_id=clients[0].id, full_name="Zoe Secundar", role="Contabil"),
                Contact(
                    client_id=clients[0].id,
                    full_name="Ana Principal",
                    role="Administrator",
                    email="ana@alfa.test",
                    is_primary=True,
                ),
            ]
        )
        db.flush()
        login(api, admin.email)

        body = api.get(f"/api/v1/clients/{clients[0].id}/contacts").json()
        assert [c["fullName"] for c in body] == ["Ana Principal", "Zoe Secundar"]
        assert body[0]["isPrimary"] is True
        assert body[0]["email"] == "ana@alfa.test"

    def test_notes_are_newest_first(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        db.add_all(
            [
                ClientNote(
                    client_id=clients[0].id,
                    author_name="Ioana Marinescu",
                    body="Prima notă",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                ClientNote(
                    client_id=clients[0].id,
                    author_name="Andrei Popa",
                    body="A doua notă",
                    created_at=datetime(2026, 6, 1, tzinfo=UTC),
                ),
            ]
        )
        db.flush()
        login(api, admin.email)

        body = api.get(f"/api/v1/clients/{clients[0].id}/notes").json()
        assert [n["body"] for n in body] == ["A doua notă", "Prima notă"]

    def test_contacts_of_an_unknown_client_are_not_found(
        self, api: TestClient, admin: User
    ) -> None:
        login(api, admin.email)
        assert api.get(f"/api/v1/clients/{uuid.uuid4()}/contacts").status_code == 404


# ── Sarcini ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tasks(db: Session, org: Organization, admin: User, clients: list[Client]) -> list[Task]:
    rows = [
        Task(
            organization_id=org.id,
            title="Gata deja",
            status=TaskStatus.DONE,
            completed_at=datetime(2026, 5, 1, tzinfo=UTC),
        ),
        Task(
            organization_id=org.id,
            title="De făcut",
            status=TaskStatus.TODO,
            client_id=clients[0].id,
            assigned_to_id=admin.id,
            priority=TaskPriority.HIGH,
            due_date=date(2026, 9, 15),
        ),
        Task(organization_id=org.id, title="Blocat", status=TaskStatus.BLOCKED),
        Task(organization_id=org.id, title="În lucru", status=TaskStatus.IN_PROGRESS),
    ]
    db.add_all(rows)
    db.flush()
    # Golim identity map-ul: testele trebuie sa vada obiectele asa cum vin din baza
    # de date, nu asa cum le-am construit in Python.
    db.expire_all()
    return rows


class TestTasks:
    def test_ordered_todo_first_done_last(
        self, api: TestClient, admin: User, tasks: list[Task]
    ) -> None:
        login(api, admin.email)
        titles = [t["title"] for t in api.get("/api/v1/tasks").json()]
        assert titles == ["De făcut", "În lucru", "Blocat", "Gata deja"]

    def test_resolves_client_and_assignee_names(
        self, api: TestClient, admin: User, tasks: list[Task]
    ) -> None:
        login(api, admin.email)
        row = next(t for t in api.get("/api/v1/tasks").json() if t["title"] == "De făcut")
        assert row["clientName"] == "Alfa Conta SRL"
        assert row["assignedToName"] == "Ioana Marinescu"
        assert row["dueDate"] == "2026-09-15"

    def test_filters_by_status(self, api: TestClient, admin: User, tasks: list[Task]) -> None:
        login(api, admin.email)
        body = api.get("/api/v1/tasks", params={"status": "BLOCKED"}).json()
        assert [t["title"] for t in body] == ["Blocat"]

    def test_completing_sets_completed_at(
        self, api: TestClient, admin: User, tasks: list[Task]
    ) -> None:
        login(api, admin.email)
        todo = next(t for t in tasks if t.status is TaskStatus.TODO)

        body = api.patch(f"/api/v1/tasks/{todo.id}", json={"status": "DONE"}).json()
        assert body["status"] == "DONE"
        assert body["completedAt"] is not None

    def test_reopening_clears_completed_at(
        self, api: TestClient, admin: User, tasks: list[Task]
    ) -> None:
        """Invariantul din migrare: gata ⇔ are dată de finalizare."""
        login(api, admin.email)
        done = next(t for t in tasks if t.status is TaskStatus.DONE)

        body = api.patch(f"/api/v1/tasks/{done.id}", json={"status": "TODO"}).json()
        assert body["status"] == "TODO"
        assert body["completedAt"] is None

    def test_records_an_audit_entry(
        self, api: TestClient, db: Session, admin: User, tasks: list[Task]
    ) -> None:
        login(api, admin.email)
        todo = next(t for t in tasks if t.status is TaskStatus.TODO)
        api.patch(f"/api/v1/tasks/{todo.id}", json={"status": "IN_PROGRESS"})

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "TASK_UPDATED")).first()
        assert entry is not None
        assert entry.old_value == {"status": "TODO"}
        assert entry.new_value == {"status": "IN_PROGRESS"}

    def test_rejects_an_unknown_status(
        self, api: TestClient, admin: User, tasks: list[Task]
    ) -> None:
        login(api, admin.email)
        response = api.patch(f"/api/v1/tasks/{tasks[0].id}", json={"status": "INVENTAT"})
        assert response.status_code == 422

    def test_unknown_task_is_not_found(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        assert (
            api.patch(f"/api/v1/tasks/{uuid.uuid4()}", json={"status": "DONE"}).status_code == 404
        )


# ── Autorizare și izolare (R10) ──────────────────────────────────────────────


class TestAuthorization:
    def test_clients_require_authentication(self, api: TestClient) -> None:
        assert api.get("/api/v1/clients").status_code == 401

    def test_tasks_require_authentication(self, api: TestClient) -> None:
        assert api.get("/api/v1/tasks").status_code == 401

    def test_viewer_can_read_but_not_move_tasks(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        tasks: list[Task],
    ) -> None:
        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        login(api, viewer.email)

        assert api.get("/api/v1/tasks").status_code == 200
        response = api.patch(f"/api/v1/tasks/{tasks[0].id}", json={"status": "DONE"})
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_clients_of_another_organization_are_invisible(
        self,
        api: TestClient,
        db: Session,
        admin: User,
        clients: list[Client],
        roles: dict[RoleCode, Role],
    ) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO20000002")
        db.add(other)
        db.flush()
        db.add(
            Client(organization_id=other.id, name="Client Străin SRL", status=ClientStatus.ACTIVE)
        )
        db.flush()

        login(api, admin.email)
        names = {c["name"] for c in api.get("/api/v1/clients").json()["items"]}
        assert "Client Străin SRL" not in names

    def test_a_client_of_another_organization_is_not_found_by_id(
        self, api: TestClient, db: Session, admin: User, clients: list[Client]
    ) -> None:
        """NOT_FOUND, nu FORBIDDEN: altfel răspunsul confirmă că id-ul există."""
        other = Organization(name="Alt Cabinet SRL", tax_id="RO20000003")
        db.add(other)
        db.flush()
        foreign = Client(organization_id=other.id, name="Client Străin SRL")
        db.add(foreign)
        db.flush()

        login(api, admin.email)
        assert api.get(f"/api/v1/clients/{foreign.id}").status_code == 404

    def test_a_task_of_another_organization_cannot_be_moved(
        self, api: TestClient, db: Session, admin: User, roles: dict[RoleCode, Role]
    ) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO20000004")
        db.add(other)
        db.flush()
        foreign = Task(organization_id=other.id, title="Sarcină străină")
        db.add(foreign)
        db.flush()

        login(api, admin.email)
        assert api.patch(f"/api/v1/tasks/{foreign.id}", json={"status": "DONE"}).status_code == 404
