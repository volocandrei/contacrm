"""Rutele de conectare OneDrive și de mapare a dosarelor (M9).

Trei lucruri se verifică aici, în ordinea gravității:

1. **Tokenul nu iese niciodată.** Nici întreg, nici trunchiat, nici în vreun
   câmp de diagnostic (§73). Un răspuns care îl scapă dă cuiva acces la toate
   documentele cabinetului.
2. **Consimțământul nu poate fi furat.** `state` este semnat și legat de
   organizația care l-a pornit: fără asta, un link pregătit de altcineva ar
   conecta cabinetului un OneDrive străin, de unde ar citi apoi tot ce intră.
3. **Ecranul spune adevărul despre configurare** — dacă lipsesc credențialele
   sau cheia de criptare, o spune, în loc să ofere un buton care eșuează.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config as core_config
from app.core.crypto import decrypt, encrypt
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.microsoft import DriveFolder, MicrosoftConnection
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services.microsoft.deps import get_drive_client
from app.services.storage.local import LocalStorageProvider
from tests.conftest import requires_db
from tests.drive_fake import VALID_CODE, VALID_REFRESH, FakeDriveClient, file_item, folder_item

pytestmark = requires_db

PASSWORD = "parola-de-test-1234"
URL = "/api/v1/integrations/onedrive"


# ── Fixture-uri ──────────────────────────────────────────────────────────────


@pytest.fixture
def roles(db: Session) -> dict[RoleCode, Role]:
    from app.domain.permissions import Permission as PermissionCode

    permissions = {code.value: Permission(code=code.value) for code in PermissionCode}
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
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


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
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO10000101")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def drive() -> FakeDriveClient:
    return FakeDriveClient()


@pytest.fixture
def api_drive(api: TestClient, drive: FakeDriveClient, tmp_path: Path) -> TestClient:
    """Clientul HTTP, cu Microsoft și discul înlocuite.

    Fără asta, fiecare test ar cere credențiale reale — adică nu ar rula niciodată.
    """
    from app.api.deps import get_storage

    app = api.app
    app.dependency_overrides[get_drive_client] = lambda: drive  # type: ignore[attr-defined]
    app.dependency_overrides[get_storage] = lambda: LocalStorageProvider(  # type: ignore[attr-defined]
        tmp_path / "storage"
    )
    return api


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integrarea configurată. Testele care verifică lipsa o desfac explicit."""
    monkeypatch.setattr(core_config.settings, "ms_client_id", "client-id-de-test")
    monkeypatch.setattr(core_config.settings, "ms_client_secret", "secret-de-test")
    monkeypatch.setattr(core_config.settings, "ms_tenant_id", "common")


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def connect(api: TestClient) -> dict:  # type: ignore[type-arg]
    """Parcurge fluxul întreg: autorizare, apoi schimbul codului."""
    state = api.post(f"{URL}/authorize").json()["authorizeUrl"]
    token = state.split("state=")[1].split("&")[0]

    response = api.post(f"{URL}/connect", json={"code": VALID_CODE, "state": token})
    assert response.status_code == 200, response.text
    body: dict = response.json()
    return body


# ── Configurare ──────────────────────────────────────────────────────────────


class TestWhatTheScreenIsTold:
    def test_an_unconfigured_integration_says_so(
        self, api_drive: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(core_config.settings, "ms_client_id", "")
        login(api_drive, admin.email)

        body = api_drive.get(URL).json()

        assert body["configured"] is False
        assert body["connected"] is False

    def test_a_configured_but_unconnected_integration(
        self, api_drive: TestClient, admin: User
    ) -> None:
        login(api_drive, admin.email)
        body = api_drive.get(URL).json()

        assert body["configured"] is True
        assert body["encryptionReady"] is True
        assert body["connected"] is False
        assert body["folders"] == []

    def test_authorization_is_refused_without_credentials(
        self, api_drive: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un buton care eșuează este mai rău decât unul care lipsește."""
        monkeypatch.setattr(core_config.settings, "ms_client_secret", "")
        login(api_drive, admin.email)

        response = api_drive.post(f"{URL}/authorize")

        assert response.status_code == 409
        assert "MS_CLIENT" in response.json()["message"]

    def test_authorization_is_refused_without_an_encryption_key(
        self, api_drive: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mai bine refuzăm decât să primim un token pe care nu îl putem păstra
        în siguranță și să-l scriem în clar „doar de data asta"."""
        import app.api.v1.integrations as integrations

        monkeypatch.setattr(integrations, "encryption_available", lambda: False)
        login(api_drive, admin.email)

        response = api_drive.post(f"{URL}/authorize")

        assert response.status_code == 409
        assert "DRIVE_TOKEN_KEY" in response.json()["message"]


# ── Consimțământ ─────────────────────────────────────────────────────────────


class TestConsent:
    def test_the_authorize_url_points_at_microsoft(
        self, api_drive: TestClient, admin: User
    ) -> None:
        login(api_drive, admin.email)
        url = api_drive.post(f"{URL}/authorize").json()["authorizeUrl"]

        assert url.startswith("https://login.microsoftonline.com/")
        assert "client-id-de-test" in url
        # Fără `offline_access` nu există sincronizare automată, doar una manuală
        # la fiecare oră — adică exact ce cabinetul nu a cerut.
        assert "offline_access" in url

    def test_the_secret_never_appears_in_the_authorize_url(
        self, api_drive: TestClient, admin: User
    ) -> None:
        """Adresa ajunge în bara browserului și în istoricul lui."""
        login(api_drive, admin.email)
        url = api_drive.post(f"{URL}/authorize").json()["authorizeUrl"]

        assert "secret-de-test" not in url

    def test_connecting_stores_the_account_and_the_token(
        self, api_drive: TestClient, admin: User, db: Session
    ) -> None:
        login(api_drive, admin.email)

        body = connect(api_drive)

        assert body["connected"] is True
        assert body["accountEmail"] == "contabil@cabinet.test"

        stored = db.scalars(select(MicrosoftConnection)).one()
        # Criptat în bază, dar folosibil: un dump nu dă acces la OneDrive.
        assert stored.refresh_token != VALID_REFRESH
        assert decrypt(stored.refresh_token) == VALID_REFRESH

    def test_a_forged_state_is_refused(self, api_drive: TestClient, admin: User) -> None:
        """Fără semnătură, oricine ar putea porni un consimțământ în numele nostru."""
        login(api_drive, admin.email)

        response = api_drive.post(
            f"{URL}/connect", json={"code": VALID_CODE, "state": "eu.am.inventat-asta"}
        )

        assert response.status_code == 422

    def test_a_state_from_another_organization_is_refused(
        self, api_drive: TestClient, admin: User
    ) -> None:
        """Altfel, un link pregătit de altcineva ar conecta cabinetului OneDrive-ul lui."""
        from datetime import timedelta

        from app.core.security import encode_state

        stolen = encode_state(
            {"organizationId": str(uuid.uuid4()), "userId": str(uuid.uuid4())},
            expires_in=timedelta(minutes=15),
        )
        login(api_drive, admin.email)

        response = api_drive.post(f"{URL}/connect", json={"code": VALID_CODE, "state": stolen})

        assert response.status_code == 403

    def test_microsoft_refusing_the_code_is_not_a_500(
        self, api_drive: TestClient, admin: User
    ) -> None:
        login(api_drive, admin.email)
        state = api_drive.post(f"{URL}/authorize").json()["authorizeUrl"].split("state=")[1]

        response = api_drive.post(
            f"{URL}/connect", json={"code": "cod-gresit", "state": state.split("&")[0]}
        )

        assert response.status_code == 422
        assert response.json()["message"]

    def test_reconnecting_keeps_the_mapped_folders(
        self, api_drive: TestClient, admin: User, db: Session, client_row: Client
    ) -> None:
        """Un token expirat nu are voie să șteargă munca de mapare."""
        login(api_drive, admin.email)
        connect(api_drive)
        api_drive.post(
            f"{URL}/folders",
            json={
                "driveId": "drive-1",
                "itemId": "folder-alfa",
                "path": "/Clienti/Alfa",
                "clientId": str(client_row.id),
            },
        )

        body = connect(api_drive)

        assert len(body["folders"]) == 1
        assert body["folders"][0]["clientName"] == "Alfa Conta SRL"


# ── Ce nu iese niciodată ─────────────────────────────────────────────────────


class TestTheTokenStaysIn:
    def test_no_response_contains_the_token(
        self, api_drive: TestClient, admin: User, client_row: Client
    ) -> None:
        """Sweep peste toate răspunsurile rutei, nu doar peste cele la care ne-am gândit."""
        login(api_drive, admin.email)
        connect(api_drive)
        api_drive.post(
            f"{URL}/folders",
            json={"driveId": "drive-1", "itemId": "f", "path": "/Clienti/Alfa"},
        )

        bodies = [
            api_drive.get(URL).text,
            api_drive.post(f"{URL}/authorize").text,
            api_drive.get(f"{URL}/browse").text,
            api_drive.post(f"{URL}/sync").text,
        ]

        for body in bodies:
            assert VALID_REFRESH not in body
            assert "refreshToken" not in body
            # Nici măcar un fragment: primele caractere ale unui token sunt de
            # ajuns ca să se recunoască într-un log.
            assert VALID_REFRESH[:12] not in body

    def test_the_client_secret_never_leaves(self, api_drive: TestClient, admin: User) -> None:
        login(api_drive, admin.email)
        assert "secret-de-test" not in api_drive.get(URL).text


# ── Dosare ───────────────────────────────────────────────────────────────────


class TestFolders:
    def test_browsing_shows_only_folders(self, api_drive, admin, drive) -> None:
        login(api_drive, admin.email)
        connect(api_drive)
        drive.folders[None] = [folder_item("f1", "Alfa Conta SRL"), folder_item("f2", "Beta SRL")]

        items = api_drive.get(f"{URL}/browse").json()

        assert [item["name"] for item in items] == ["Alfa Conta SRL", "Beta SRL"]
        assert all(item["isTracked"] is False for item in items)

    def test_browsing_descends_into_a_subfolder(self, api_drive, admin, drive) -> None:
        """`parentId` chiar se leagă.

        Un parametru de query nu trece prin `ApiModel`, deci nu primește aliasul
        camelCase de la sine. Fără el, FastAPI căuta `parent_id`, nu găsea nimic
        și răspundea tăcut cu rădăcina: răsfoirea părea că merge, dar nu cobora
        niciodată. Defectul s-a văzut abia rulând serverul.
        """
        login(api_drive, admin.email)
        connect(api_drive)
        drive.folders[None] = [folder_item("d-clienti", "Clienți")]
        drive.folders["d-clienti"] = [folder_item("d-alfa", "Alfa Conta SRL")]

        root = api_drive.get(f"{URL}/browse").json()
        children = api_drive.get(f"{URL}/browse", params={"parentId": "d-clienti"}).json()

        assert [item["name"] for item in root] == ["Clienți"]
        assert [item["name"] for item in children] == ["Alfa Conta SRL"]

    def test_an_already_tracked_folder_is_marked(self, api_drive, admin, drive) -> None:
        """Ca administratorul să nu îl adauge de două ori."""
        login(api_drive, admin.email)
        connect(api_drive)
        drive.folders[None] = [folder_item("f1", "Alfa Conta SRL")]
        api_drive.post(
            f"{URL}/folders",
            json={"driveId": "drive-1", "itemId": "f1", "path": "/Clienti/Alfa Conta SRL"},
        )

        items = api_drive.get(f"{URL}/browse").json()

        assert items[0]["isTracked"] is True

    def test_tracking_the_same_folder_twice_is_refused(self, api_drive, admin) -> None:
        """Al doilea rând ar produce două intake-uri pentru fiecare fișier."""
        login(api_drive, admin.email)
        connect(api_drive)
        payload = {"driveId": "drive-1", "itemId": "f1", "path": "/Clienti/Alfa"}
        api_drive.post(f"{URL}/folders", json=payload)

        assert api_drive.post(f"{URL}/folders", json=payload).status_code == 409

    def test_a_folder_can_be_mapped_to_a_client_later(
        self, api_drive, admin, client_row: Client
    ) -> None:
        login(api_drive, admin.email)
        connect(api_drive)
        created = api_drive.post(
            f"{URL}/folders", json={"driveId": "drive-1", "itemId": "f1", "path": "/Clienti/Alfa"}
        ).json()
        assert created["clientId"] is None

        updated = api_drive.patch(
            f"{URL}/folders/{created['id']}", json={"clientId": str(client_row.id)}
        ).json()

        assert updated["clientName"] == "Alfa Conta SRL"

    def test_a_client_from_another_organization_is_refused(
        self, api_drive, admin, db: Session
    ) -> None:
        """R10 — granița organizației, verificată în interogare."""
        other_org = Organization(name="Alt Cabinet")
        db.add(other_org)
        db.flush()
        stranger = Client(organization_id=other_org.id, name="Străin SRL", tax_id="RO9")
        db.add(stranger)
        db.flush()

        login(api_drive, admin.email)
        connect(api_drive)

        response = api_drive.post(
            f"{URL}/folders",
            json={
                "driveId": "drive-1",
                "itemId": "f1",
                "path": "/x",
                "clientId": str(stranger.id),
            },
        )

        assert response.status_code == 404

    def test_untracking_leaves_the_documents_alone(
        self, api_drive, admin, db: Session, drive
    ) -> None:
        """Documentele intrate sunt probe contabile, nu o copie a unui dosar (R8)."""
        login(api_drive, admin.email)
        connect(api_drive)
        created = api_drive.post(
            f"{URL}/folders", json={"driveId": "drive-1", "itemId": "folder-alfa", "path": "/A"}
        ).json()
        drive.put_files("folder-alfa", [file_item("f1", "factura.pdf")])
        api_drive.post(f"{URL}/sync")

        assert api_drive.delete(f"{URL}/folders/{created['id']}").status_code == 204

        from app.models.document import Document

        assert db.scalars(select(Document)).all()

    def test_a_folder_of_another_organization_is_not_found(
        self, api_drive, admin, db: Session
    ) -> None:
        login(api_drive, admin.email)
        connect(api_drive)

        response = api_drive.patch(f"{URL}/folders/{uuid.uuid4()}", json={"clientId": None})

        assert response.status_code == 404


# ── Sincronizare la cerere ───────────────────────────────────────────────────


class TestSyncNow:
    def test_it_reports_what_came_in(self, api_drive, admin, drive, client_row) -> None:
        login(api_drive, admin.email)
        connect(api_drive)
        api_drive.post(
            f"{URL}/folders",
            json={
                "driveId": "drive-1",
                "itemId": "folder-alfa",
                "path": "/Clienti/Alfa",
                "clientId": str(client_row.id),
            },
        )
        drive.put_files("folder-alfa", [file_item("f1", "12.08 scan.pdf")])

        body = api_drive.post(f"{URL}/sync").json()

        assert body["ingested"] == 1
        assert body["failed"] == 0

    def test_syncing_without_a_connection_is_refused(self, api_drive, admin) -> None:
        login(api_drive, admin.email)
        assert api_drive.post(f"{URL}/sync").status_code == 409


# ── Acces ────────────────────────────────────────────────────────────────────


class TestAccess:
    def test_every_route_needs_a_session(self, api_drive: TestClient) -> None:
        calls = [
            ("GET", URL, None),
            ("POST", f"{URL}/authorize", None),
            ("POST", f"{URL}/connect", {"code": "x", "state": "y"}),
            ("GET", f"{URL}/browse", None),
            ("POST", f"{URL}/folders", {"driveId": "d", "itemId": "i", "path": "/p"}),
            ("POST", f"{URL}/sync", None),
            ("DELETE", URL, None),
        ]
        for method, path, body in calls:
            response = api_drive.request(method, path, json=body)
            assert response.status_code == 401, f"{method} {path}"

    def test_an_operator_cannot_connect_a_drive(
        self, api_drive: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Cine poate conecta un OneDrive poate citi documentele tuturor clienților."""
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        login(api_drive, operator.email)

        assert api_drive.get(URL).status_code == 403
        assert api_drive.post(f"{URL}/authorize").status_code == 403


class TestDisconnecting:
    def test_it_removes_the_token_and_the_folders(
        self, api_drive: TestClient, admin: User, db: Session
    ) -> None:
        login(api_drive, admin.email)
        connect(api_drive)
        api_drive.post(f"{URL}/folders", json={"driveId": "drive-1", "itemId": "f1", "path": "/A"})

        assert api_drive.delete(URL).status_code == 204

        assert db.scalars(select(MicrosoftConnection)).all() == []
        # Cascadă: dosarele nu au ce căuta fără conexiunea prin care se citeau.
        assert db.scalars(select(DriveFolder)).all() == []


def test_the_fake_and_the_real_client_speak_the_same_protocol() -> None:
    """Altfel testele ar valida un contract pe care implementarea reală nu îl are."""
    from app.services.microsoft.base import DriveClient
    from app.services.microsoft.graph import MicrosoftGraphClient

    assert isinstance(FakeDriveClient(), DriveClient)
    assert isinstance(
        MicrosoftGraphClient(client_id="x", client_secret="y", tenant="common"), DriveClient
    )


def test_a_stored_token_survives_a_round_trip() -> None:
    assert decrypt(encrypt(VALID_REFRESH)) == VALID_REFRESH
