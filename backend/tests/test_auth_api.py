"""Fluxul de autentificare, capăt la capăt, pe o bază de date reală.

Sar automat când Postgres nu este pornit — vezi `conftest.requires_db`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, REFRESH_COOKIE
from app.core.security import hash_password
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.organization import Organization
from app.models.user import Permission, RefreshToken, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"


# ── Pregătirea datelor ───────────────────────────────────────────────────────


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Contabil Demo SRL", tax_id="RO10000001")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def roles(db: Session) -> dict[RoleCode, Role]:
    permissions = {}
    for role_perms in ROLE_PERMISSIONS.values():
        for perm in role_perms:
            if perm.value not in permissions:
                permissions[perm.value] = Permission(code=perm.value)
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


def make_user(
    db: Session,
    org: Organization,
    roles: dict[RoleCode, Role],
    *,
    email: str,
    role: RoleCode,
    is_active: bool = True,
) -> User:
    user = User(
        organization_id=org.id,
        email=email,
        full_name="Utilizator Test",
        password_hash=hash_password(PASSWORD),
        is_active=is_active,
        roles=[roles[role]],
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


def login(api: TestClient, email: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


# ── Login ────────────────────────────────────────────────────────────────────


class TestLogin:
    def test_returns_the_shape_the_frontend_expects(self, api: TestClient, admin: User) -> None:
        response = login(api, admin.email)
        assert response.status_code == 200

        body = response.json()
        assert set(body) == {
            "id",
            "fullName",
            "email",
            "role",
            "permissions",
            "organizationId",
            "organizationName",
        }
        assert body["email"] == admin.email
        assert body["role"] == "ADMIN"
        assert body["organizationName"] == "Cabinet Contabil Demo SRL"
        assert "documents:approve" in body["permissions"]
        # ADMIN nu poate șterge documente — doar SUPER_ADMIN (R8).
        assert "documents:delete" not in body["permissions"]

    def test_sets_httponly_cookies_and_leaks_no_token_in_the_body(
        self, api: TestClient, admin: User
    ) -> None:
        response = login(api, admin.email)

        cookies = {c.name: c for c in response.cookies.jar}
        assert ACCESS_COOKIE in cookies
        assert REFRESH_COOKIE in cookies

        raw = "\n".join(response.headers.get_list("set-cookie"))
        assert raw.lower().count("httponly") == 2
        assert "samesite=lax" in raw.lower()

        # Tokenul nu trebuie să apară în corp: acolo l-ar putea citi un XSS.
        assert "token" not in response.text.lower()

    def test_email_is_case_insensitive(self, api: TestClient, admin: User) -> None:
        assert login(api, "ADMIN@ContaCRM.test").status_code == 200

    def test_wrong_password_is_rejected(self, api: TestClient, admin: User) -> None:
        response = login(api, admin.email, "gresita")
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_unknown_email_gives_the_same_answer_as_a_wrong_password(
        self, api: TestClient, admin: User
    ) -> None:
        """Altfel formularul de login devine un oracol de enumerare a conturilor."""
        unknown = login(api, "nimeni@contacrm.test")
        wrong = login(api, admin.email, "gresita")

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["message"] == wrong.json()["message"]

    def test_inactive_account_cannot_log_in(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        user = make_user(
            db, org, roles, email="inactiv@contacrm.test", role=RoleCode.VIEWER, is_active=False
        )
        response = login(api, user.email)
        assert response.status_code == 401
        assert "dezactivat" in response.json()["message"]

    def test_records_an_audit_entry(self, api: TestClient, db: Session, admin: User) -> None:
        login(api, admin.email)
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "USER_LOGIN")).first()
        assert entry is not None
        assert entry.user_id == admin.id
        assert entry.organization_id == admin.organization_id
        assert entry.request_id  # legătura cu linia de log a cererii

    def test_updates_last_login(self, api: TestClient, db: Session, admin: User) -> None:
        assert admin.last_login_at is None
        login(api, admin.email)
        db.refresh(admin)
        assert admin.last_login_at is not None

    def test_rejects_a_malformed_email(self, api: TestClient) -> None:
        response = api.post("/api/v1/auth/login", json={"email": "nu-e-email", "password": "x"})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert "email" in response.json()["details"]


# ── /me ──────────────────────────────────────────────────────────────────────


class TestMe:
    def test_requires_authentication(self, api: TestClient) -> None:
        response = api.get("/api/v1/me")
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_returns_the_session_user(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        response = api.get("/api/v1/me")
        assert response.status_code == 200
        assert response.json()["email"] == admin.email

    def test_accepts_a_bearer_token_too(self, api: TestClient, admin: User) -> None:
        """Clienții programatici nu au cookie jar."""
        login_response = login(api, admin.email)
        token = login_response.cookies[ACCESS_COOKIE]
        api.cookies.clear()

        response = api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_rejects_a_forged_token(self, api: TestClient) -> None:
        response = api.get("/api/v1/me", headers={"Authorization": "Bearer nu.este.un.token"})
        assert response.status_code == 401

    def test_a_refresh_token_is_not_accepted_as_an_access_token(
        self, api: TestClient, admin: User
    ) -> None:
        login_response = login(api, admin.email)
        refresh = login_response.cookies[REFRESH_COOKIE]
        api.cookies.clear()

        response = api.get("/api/v1/me", headers={"Authorization": f"Bearer {refresh}"})
        assert response.status_code == 401

    def test_deactivating_an_account_invalidates_the_live_session(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        login(api, admin.email)
        assert api.get("/api/v1/me").status_code == 200

        admin.is_active = False
        db.flush()

        assert api.get("/api/v1/me").status_code == 401


# ── Refresh și rotație ───────────────────────────────────────────────────────


class TestRefresh:
    def test_issues_a_new_pair(self, api: TestClient, admin: User) -> None:
        first = login(api, admin.email).cookies[REFRESH_COOKIE]
        response = api.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        assert response.json()["email"] == admin.email
        assert response.cookies[REFRESH_COOKIE] != first

    def test_rotates_and_revokes_the_used_token(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        login(api, admin.email)
        api.post("/api/v1/auth/refresh")

        tokens = list(db.scalars(select(RefreshToken).where(RefreshToken.user_id == admin.id)))
        assert len(tokens) == 2
        used = next(t for t in tokens if t.revoked_at is not None)
        successor = next(t for t in tokens if t.revoked_at is None)
        assert used.replaced_by_id == successor.token_id
        assert used.family_id == successor.family_id

    def test_reusing_a_rotated_token_revokes_the_whole_family(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        """Un token deja rotit care reapare înseamnă că cineva are o copie."""
        stolen = login(api, admin.email).cookies[REFRESH_COOKIE]
        api.post("/api/v1/auth/refresh")  # rotația face `stolen` inutilizabil

        api.cookies.set(REFRESH_COOKIE, stolen)
        response = api.post("/api/v1/auth/refresh")
        assert response.status_code == 401

        alive = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == admin.id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        assert alive == []

        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "REFRESH_TOKEN_REUSE_DETECTED")
        ).first()
        assert entry is not None

    def test_without_a_refresh_cookie_it_fails(self, api: TestClient) -> None:
        assert api.post("/api/v1/auth/refresh").status_code == 401

    def test_an_expired_token_is_rejected(self, api: TestClient, db: Session, admin: User) -> None:
        login(api, admin.email)
        token = db.scalars(select(RefreshToken).where(RefreshToken.user_id == admin.id)).one()
        token.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.flush()

        assert api.post("/api/v1/auth/refresh").status_code == 401


# ── Logout ───────────────────────────────────────────────────────────────────


class TestLogout:
    def test_clears_cookies_and_revokes_the_session(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        login(api, admin.email)
        response = api.post("/api/v1/auth/logout")

        assert response.status_code == 200
        assert response.json() == {"ok": True}

        alive = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == admin.id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        assert alive == []
        assert api.get("/api/v1/me").status_code == 401

    def test_succeeds_without_a_session(self, api: TestClient) -> None:
        """Altfel un token expirat ar lăsa utilizatorul blocat cu cookie-uri."""
        assert api.post("/api/v1/auth/logout").status_code == 200


# ── Autorizare (R10) ─────────────────────────────────────────────────────────


class TestAuthorization:
    def test_admin_can_list_users(self, api: TestClient, admin: User) -> None:
        login(api, admin.email)
        response = api.get("/api/v1/users")
        assert response.status_code == 200
        assert response.json()[0]["email"] == admin.email

    def test_operator_cannot_list_users(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        user = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        login(api, user.email)

        response = api.get("/api/v1/users")
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_listing_users_requires_authentication(self, api: TestClient) -> None:
        assert api.get("/api/v1/users").status_code == 401

    def test_users_from_another_organization_are_not_visible(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Scurgerea între organizații este breșa gravă din R10."""
        other = Organization(name="Alt Cabinet SRL", tax_id="RO20000002")
        db.add(other)
        db.flush()
        db.add(
            User(
                organization_id=other.id,
                email="strain@altcabinet.test",
                full_name="Utilizator Străin",
                password_hash=hash_password(PASSWORD),
                roles=[roles[RoleCode.ADMIN]],
            )
        )
        db.flush()

        admin = make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)
        login(api, admin.email)

        emails = {u["email"] for u in api.get("/api/v1/users").json()}
        assert emails == {admin.email}

    def test_a_token_from_another_organization_is_rejected(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        from app.core.security import create_access_token

        forged, _ = create_access_token(admin.id, uuid.uuid4(), ["admin:users"])
        response = api.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401
