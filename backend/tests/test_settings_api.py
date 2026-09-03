"""Ecranul de setări (§16, §73).

Testul central este `test_no_sensitive_field_is_ever_exposed`: el se uită la
**fiecare** câmp din `Settings`, nu doar la cele la care ne-am gândit când am
scris ruta. Un endpoint care publică configurare este exact locul unde o cheie
adăugată luna viitoare ajunge pe un ecran fără ca nimeni să observe — iar
protecția nu poate fi „ținem minte să verificăm".

Restul verifică ce trebuia să fie adevărat de la început: că valorile afișate
sunt chiar cele după care rulează procesul.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.settings import EXPOSED, SettingGroup
from app.core.config import Settings
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
URL = "/api/v1/settings"

# Ce nu are voie să iasă niciodată printr-un răspuns HTTP (§73). Numele sunt
# fragmente: `secret` prinde și `SECRET_KEY`, și `CRON_SECRET`, și orice
# `..._SECRET` de mâine.
FORBIDDEN_FRAGMENTS = (
    "secret",
    "password",
    "token",
    "key",
    "database_url",
    "url",
    "path",
    "root",
    "bucket",
    "endpoint",
    "credential",
    "cors",
)

# Câmpuri care conțin un fragment interzis din întâmplare, dar nu sunt secrete.
# Enumerate una câte una, cu motiv — o listă de excepții fără motive devine
# repede o portiță.
ALLOWED_DESPITE_NAME = {
    # Nu este o cale, ci un tipar de structură: `/ARHIVA/{an}/{luna}/{client}/`.
    "ARCHIVE_PATTERN",
}


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


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


@pytest.fixture
def as_admin(
    api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
) -> TestClient:
    user = make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)
    login(api, user.email)
    return api


class TestWhatIsNeverExposed:
    """§73 — configurarea publicată este o listă albă, nu un filtru."""

    def test_no_sensitive_field_is_ever_exposed(self, as_admin: TestClient) -> None:
        """Se uită la fiecare câmp din `Settings`, nu la o listă ținută minte.

        Dacă mâine cineva adaugă `SENTRY_DSN` sau `AI_API_KEY` în configurare și
        îl trece din greșeală în lista albă, testul cade aici — nu în producție.
        """
        keys = {entry["key"] for entry in as_admin.get(URL).json()}

        for field in Settings.model_fields:
            if not any(fragment in field.lower() for fragment in FORBIDDEN_FRAGMENTS):
                continue
            assert field.upper() not in keys, f"{field} nu are voie să fie publicat (§73)"

    def test_the_allowlist_itself_holds_no_secrets(self) -> None:
        """A doua barieră, fără HTTP: chiar și cheile inventate sunt verificate.

        `ARCHIVE_PATTERN` nu corespunde niciunui câmp din `Settings`, deci
        testul de mai sus nu l-ar fi văzut niciodată.
        """
        for key, _, _ in EXPOSED:
            if key in ALLOWED_DESPITE_NAME:
                continue
            for fragment in FORBIDDEN_FRAGMENTS:
                assert fragment not in key.lower(), f"{key} conține „{fragment}"

    def test_no_value_looks_like_a_connection_string(self, as_admin: TestClient) -> None:
        """O valoare nu are voie să conțină credențiale nici din greșeală."""
        for entry in as_admin.get(URL).json():
            value = entry["value"]
            assert "://" not in value, f"{entry['key']} pare o adresă cu credențiale"
            assert "@" not in value, f"{entry['key']} pare să conțină un host cu utilizator"

    def test_the_archive_pattern_is_a_shape_not_a_disk_path(self, as_admin: TestClient) -> None:
        """Structura este utilă administratorului; calea de pe disc nu este.

        `STORAGE_PATH` este `./storage` în development — o cale reală, care nu
        are ce căuta într-un browser.
        """
        values = {entry["key"]: entry["value"] for entry in as_admin.get(URL).json()}

        assert values["ARCHIVE_PATTERN"] == "/ARHIVA/{an}/{luna}/{client}/"
        assert "STORAGE_PATH" not in values
        assert "ARCHIVE_ROOT" not in values


class TestWhatIsExposed:
    def test_the_values_are_the_ones_the_process_runs_on(
        self, as_admin: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asta era falsul: ecranul spunea `local` orice s-ar fi configurat."""
        from app.core import config as core_config

        monkeypatch.setattr(core_config.settings, "storage_provider", "s3")
        monkeypatch.setattr(core_config.settings, "ocr_provider", "google_docai")

        values = {entry["key"]: entry["value"] for entry in as_admin.get(URL).json()}
        assert values["STORAGE_PROVIDER"] == "s3"
        assert values["OCR_PROVIDER"] == "google_docai"

    def test_booleans_are_stable_strings(self, as_admin: TestClient) -> None:
        """`true`/`false`, nu `True`/`False`: interfața nu trebuie să știe Python."""
        values = {entry["key"]: entry["value"] for entry in as_admin.get(URL).json()}
        assert values["AUTO_APPROVE_ENABLED"] in {"true", "false"}
        assert values["NOTIFICATIONS_ENABLED"] in {"true", "false"}

    def test_the_defaults_keep_documents_on_this_machine(self, as_admin: TestClient) -> None:
        """R2 — un administrator trebuie să poată verifica asta dintr-o privire."""
        values = {entry["key"]: entry["value"] for entry in as_admin.get(URL).json()}
        assert values["OCR_PROVIDER"] == "mock"
        assert values["AI_PROVIDER"] == "mock"

    def test_every_group_is_a_known_one(self, as_admin: TestClient) -> None:
        groups = {entry["group"] for entry in as_admin.get(URL).json()}
        assert groups <= {group.value for group in SettingGroup}

    def test_keys_are_unique(self, as_admin: TestClient) -> None:
        keys = [entry["key"] for entry in as_admin.get(URL).json()]
        assert len(keys) == len(set(keys))


class TestAuthorization:
    def test_anonymous_gets_nothing(self, api: TestClient) -> None:
        assert api.get(URL).status_code == 401

    def test_a_reviewer_may_not_read_the_configuration(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """`admin:settings`, nu „oricine e autentificat"."""
        user = make_user(db, org, roles, email="verificator@contacrm.test", role=RoleCode.REVIEWER)
        login(api, user.email)

        assert api.get(URL).status_code == 403
