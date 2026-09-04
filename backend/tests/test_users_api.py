"""Administrarea colegilor din cabinet (M12).

`/users` era doar citire. Singurul mod de a adăuga pe cineva era
`app.cli create-admin`, o comandă gândită pentru **primul** cont al unei baze
goale; iar dacă cineva pleca, contul lui rămânea activ până se ocupa cineva prin
SQL.

Ce se apără aici, în ordinea gravității:

1. **Nimeni nu se poate încuia singur pe dinafară.** Nu te poți dezactiva și nu
   îți poți lua rolul prin care administrezi — amândouă se simt la fel („nu mai
   am acces") și amândouă cer, ca remediu, un terminal.
2. **Granița organizației ține**, iar un utilizator din alt cabinet nu se
   distinge de unul inexistent.
3. **Parola nu apare niciodată** — nici în răspuns, nici în jurnalul de audit.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.permissions import ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.organization import Organization
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/users"
GOOD_PASSWORD = "parola-noua-de-coleg-2026"


def create(api: TestClient, **overrides: object) -> object:
    payload: dict[str, object] = {
        "email": "coleg.nou@contacrm.test",
        "fullName": "Andrei Popescu",
        "role": "OPERATOR",
        "password": GOOD_PASSWORD,
    }
    payload.update(overrides)
    return api.post(URL, json=payload)


class TestAddingAColleague:
    def test_a_new_colleague_can_log_in(self, api: TestClient, admin: User) -> None:
        """Rostul întreg: contul nou trebuie să funcționeze imediat, fără terminal."""
        login(api, admin.email)
        assert create(api).status_code == 201  # type: ignore[union-attr]
        api.post("/api/v1/auth/logout")

        response = api.post(
            "/api/v1/auth/login",
            json={"email": "coleg.nou@contacrm.test", "password": GOOD_PASSWORD},
        )

        assert response.status_code == 200, response.text
        assert response.json()["role"] == "OPERATOR"

    def test_the_address_is_stored_lowercase(self, api: TestClient, admin: User) -> None:
        """Altfel `Ion@` și `ion@` ar fi două conturi, iar al doilea ar trece de unicitate."""
        login(api, admin.email)

        body = create(api, email="Coleg.MAJUSCULE@Contacrm.TEST").json()  # type: ignore[union-attr]

        assert body["email"] == "coleg.majuscule@contacrm.test"

    def test_the_same_address_is_refused(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        create(api)

        response = create(api, fullName="Alt Om")

        assert response.status_code == 409  # type: ignore[union-attr]

    def test_a_short_password_is_refused(self, api: TestClient, admin: User) -> None:
        """Același prag ca la `create-admin`: drumul comod nu produce conturi mai slabe."""
        login(api, admin.email)

        assert create(api, password="scurta").status_code == 422  # type: ignore[union-attr]

    def test_an_unknown_role_is_refused(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        assert create(api, role="SEF_SUPREM").status_code == 422  # type: ignore[union-attr]

    def test_the_password_never_comes_back(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        body = create(api).text  # type: ignore[union-attr]

        assert GOOD_PASSWORD not in body
        assert "password" not in body


class TestNobodyLocksThemselvesOut:
    def test_you_cannot_deactivate_yourself(self, api: TestClient, admin: User) -> None:
        """Sună a „nu mai am acces" și nu se poate repara din aplicație."""
        login(api, admin.email)

        response = api.patch(f"{URL}/{admin.id}", json={"isActive": False})

        assert response.status_code == 422
        assert "alt administrator" in response.json()["message"]

    def test_you_cannot_change_your_own_role(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        response = api.patch(f"{URL}/{admin.id}", json={"role": "VIEWER"})

        assert response.status_code == 422

    def test_you_may_still_rename_yourself(self, api: TestClient, admin: User) -> None:
        """Restricția este despre acces, nu despre orice atingere a propriului cont."""
        login(api, admin.email)

        response = api.patch(f"{URL}/{admin.id}", json={"fullName": "Ioana M. Marinescu"})

        assert response.status_code == 200
        assert response.json()["fullName"] == "Ioana M. Marinescu"


class TestWhenSomeoneLeaves:
    def test_deactivating_stops_the_login(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        admin: User,
    ) -> None:
        colleague = make_user(db, org, roles, email="pleaca@contacrm.test", role=RoleCode.OPERATOR)
        login(api, admin.email)
        assert api.patch(f"{URL}/{colleague.id}", json={"isActive": False}).status_code == 200
        api.post("/api/v1/auth/logout")

        response = api.post(
            "/api/v1/auth/login",
            json={"email": colleague.email, "password": "parola-de-test-1234"},
        )

        assert response.status_code == 401

    def test_there_is_no_delete(self, api: TestClient, admin: User) -> None:
        """Un utilizator apare în audit ca autor: ștergerea lui ar rupe urma."""
        login(api, admin.email)

        assert api.delete(f"{URL}/{admin.id}").status_code == 405

    def test_the_role_can_be_changed(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        admin: User,
    ) -> None:
        colleague = make_user(
            db, org, roles, email="promovat@contacrm.test", role=RoleCode.OPERATOR
        )
        login(api, admin.email)

        body = api.patch(f"{URL}/{colleague.id}", json={"role": "ACCOUNTANT"}).json()

        assert body["role"] == "ACCOUNTANT"


class TestResettingAPassword:
    def test_the_colleague_can_log_in_with_the_new_one(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        admin: User,
    ) -> None:
        colleague = make_user(db, org, roles, email="uituc@contacrm.test", role=RoleCode.OPERATOR)
        login(api, admin.email)
        assert (
            api.post(f"{URL}/{colleague.id}/password", json={"password": GOOD_PASSWORD}).status_code
            == 200
        )
        api.post("/api/v1/auth/logout")

        response = api.post(
            "/api/v1/auth/login", json={"email": colleague.email, "password": GOOD_PASSWORD}
        )

        assert response.status_code == 200

    def test_neither_password_reaches_the_audit(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        admin: User,
    ) -> None:
        """Jurnalul spune că s-a întâmplat, nu ce s-a scris (§33)."""
        colleague = make_user(db, org, roles, email="secret@contacrm.test", role=RoleCode.OPERATOR)
        login(api, admin.email)
        api.post(f"{URL}/{colleague.id}/password", json={"password": GOOD_PASSWORD})

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "USER_PASSWORD_RESET")).one()

        assert GOOD_PASSWORD not in str(entry.detail)
        assert GOOD_PASSWORD not in str(entry.new_value)
        # Se vede însă cine a resetat cui: singurul moment în care cineva capătă
        # acces la contul altcuiva.
        assert entry.user_name == admin.full_name
        assert colleague.email in str(entry.detail)


class TestTheOrganizationBoundary:
    def test_a_user_from_another_office_is_not_found(
        self, api: TestClient, db: Session, roles: dict[RoleCode, Role], admin: User
    ) -> None:
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival5.test", role=RoleCode.ADMIN)
        login(api, admin.email)

        response = api.patch(f"{URL}/{stranger.id}", json={"isActive": False})

        # NOT_FOUND, nu FORBIDDEN: răspunsul nu confirmă că id-ul există (§72).
        assert response.status_code == 404

    def test_an_invented_id_is_not_found(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        assert api.patch(f"{URL}/{uuid.uuid4()}", json={"isActive": False}).status_code == 404


class TestWhoMayTouchThis:
    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            (RoleCode.ADMIN, True),
            (RoleCode.ACCOUNTANT, False),
            (RoleCode.OPERATOR, False),
        ],
    )
    def test_adding_a_colleague_needs_admin_users(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        role: RoleCode,
        allowed: bool,
    ) -> None:
        user = make_user(db, org, roles, email=f"who-{role.value.lower()}@contacrm.test", role=role)
        login(api, user.email)

        response = create(api, email=f"nou-{role.value.lower()}@contacrm.test")

        assert (response.status_code == 201) is allowed, response.text  # type: ignore[union-attr]

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        assert create(api).status_code == 401  # type: ignore[union-attr]


class TestTheRoleMatrix:
    """`/roles` există ca ecranul de administrare să poată răspunde la
    „ce poate face un operator?" **înainte** de a da rolul, nu după."""

    def test_every_role_is_described(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)

        response = api.get("/api/v1/roles")

        assert response.status_code == 200
        body = response.json()
        assert [entry["code"] for entry in body] == [role.value for role in RoleCode]
        assert all(entry["label"] for entry in body)

    def test_the_answer_is_the_backend_map_itself(self, api: TestClient, admin: User) -> None:
        """Nu o listă scrisă de mână care s-ar putea despărți de reguli."""
        login(api, admin.email)

        body = api.get("/api/v1/roles").json()

        for entry in body:
            expected = {p.value for p in ROLE_PERMISSIONS[RoleCode(entry["code"])]}
            assert set(entry["permissions"]) == expected, entry["code"]

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            (RoleCode.ADMIN, True),
            (RoleCode.ACCOUNTANT, False),
            (RoleCode.OPERATOR, False),
            (RoleCode.VIEWER, False),
        ],
    )
    def test_only_who_hands_out_roles_may_read_the_matrix(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        role: RoleCode,
        allowed: bool,
    ) -> None:
        user = make_user(db, org, roles, email=f"m-{role.value.lower()}@contacrm.test", role=role)
        login(api, user.email)

        assert (api.get("/api/v1/roles").status_code == 200) is allowed

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        assert api.get("/api/v1/roles").status_code == 401
