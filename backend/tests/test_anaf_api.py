"""Rutele de conectare ANAF și de administrare a împuternicirilor (M11).

Aceleași trei lucruri ca la OneDrive, în aceeași ordine a gravității:

1. **Tokenul nu iese niciodată.** Nici întreg, nici trunchiat, nici într-un câmp
   de diagnostic (§73). Un răspuns care îl scapă dă cuiva acces la facturile
   tuturor clienților cabinetului.
2. **Autorizarea nu poate fi furată.** `state` este semnat și legat de
   organizația care l-a pornit.
3. **Ecranul spune adevărul despre configurare** — dacă lipsesc credențialele
   sau cheia de criptare, o spune, în loc să ofere un buton care eșuează.

Plus unul propriu integrării: **o împuternicire aparține unui singur client, iar
un CUI unui singur rând.** Două rânduri pe același CUI ar aduce fiecare factură
de două ori și ar dubla cererile către ANAF, care le numără.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config as core_config
from app.core.crypto import decrypt
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.anaf import AnafConnection, AnafMandate
from app.models.client import Client
from app.models.document import Document
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services.anaf.deps import get_anaf_client
from app.services.storage.local import LocalStorageProvider
from tests.anaf_fake import VALID_CODE, VALID_REFRESH, FakeAnafClient
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-1234"
URL = "/api/v1/integrations/anaf"
TAX_ID = "10000101"


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
def operator(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id=f"RO{TAX_ID}")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def anaf() -> FakeAnafClient:
    return FakeAnafClient()


@pytest.fixture
def api_anaf(api: TestClient, anaf: FakeAnafClient, tmp_path: Path) -> TestClient:
    """Clientul HTTP, cu ANAF și discul înlocuite.

    Fără asta, fiecare test ar cere un certificat digital calificat — adică nu ar
    rula niciodată, nici în CI, nici pe laptop.
    """
    from app.api.deps import get_storage

    app = api.app
    app.dependency_overrides[get_anaf_client] = lambda: anaf  # type: ignore[attr-defined]
    app.dependency_overrides[get_storage] = lambda: LocalStorageProvider(  # type: ignore[attr-defined]
        tmp_path / "storage"
    )
    return api


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integrarea configurată. Testele care verifică lipsa o desfac explicit."""
    monkeypatch.setattr(core_config.settings, "anaf_client_id", "client-id-de-test")
    monkeypatch.setattr(core_config.settings, "anaf_client_secret", "secret-de-test")
    monkeypatch.setattr(core_config.settings, "anaf_environment", "test")


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def connect(api: TestClient) -> dict:  # type: ignore[type-arg]
    """Parcurge fluxul întreg: autorizare, apoi schimbul codului."""
    authorize = api.post(f"{URL}/authorize").json()["authorizeUrl"]
    state = authorize.split("state=")[1].split("&")[0]

    response = api.post(
        f"{URL}/connect",
        json={"code": VALID_CODE, "state": state, "certificateHolder": "Certificat cabinet"},
    )
    assert response.status_code == 200, response.text
    body: dict = response.json()
    return body


def add_mandate(api: TestClient, client_id: uuid.UUID) -> dict:  # type: ignore[type-arg]
    response = api.post(f"{URL}/mandates", json={"clientId": str(client_id)})
    assert response.status_code == 201, response.text
    body: dict = response.json()
    return body


# ── Configurare ──────────────────────────────────────────────────────────────


class TestWhatTheScreenIsTold:
    def test_an_unconfigured_integration_says_so(
        self, api_anaf: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(core_config.settings, "anaf_client_id", "")
        login(api_anaf, admin.email)

        body = api_anaf.get(URL).json()

        assert body["configured"] is False
        assert body["connected"] is False

    def test_a_configured_but_unconnected_integration(
        self, api_anaf: TestClient, admin: User
    ) -> None:
        login(api_anaf, admin.email)
        body = api_anaf.get(URL).json()

        assert body["configured"] is True
        assert body["encryptionReady"] is True
        assert body["connected"] is False
        assert body["mandates"] == []

    def test_authorising_without_credentials_is_refused(
        self, api_anaf: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(core_config.settings, "anaf_client_secret", "")
        login(api_anaf, admin.email)

        response = api_anaf.post(f"{URL}/authorize")

        assert response.status_code == 409
        assert "ANAF_CLIENT_ID" in response.json()["message"]


# ── Autorizare ───────────────────────────────────────────────────────────────


class TestAuthorisation:
    def test_connecting_stores_the_token_encrypted(
        self, api_anaf: TestClient, admin: User, db: Session
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)

        stored = db.scalars(select(AnafConnection)).one()
        assert stored.refresh_token != VALID_REFRESH
        assert decrypt(stored.refresh_token) == VALID_REFRESH

    def test_the_token_never_leaves(self, api_anaf: TestClient, admin: User) -> None:
        login(api_anaf, admin.email)
        body = connect(api_anaf)

        # Nici întreg, nici trunchiat, nici într-un câmp de diagnostic.
        assert VALID_REFRESH not in str(body)
        assert VALID_REFRESH[:12] not in str(body)

    def test_the_expiry_is_shown(self, api_anaf: TestClient, admin: User) -> None:
        """Reînnoirea cere din nou certificatul: se anunță, nu se descoperă."""
        login(api_anaf, admin.email)

        assert connect(api_anaf)["expiresAt"] is not None

    def test_a_state_from_another_organisation_is_refused(
        self, api_anaf: TestClient, admin: User, db: Session, roles: dict[RoleCode, Role]
    ) -> None:
        """Altfel, un link pregătit de altcineva ar lega certificatul lui de noi."""
        from app.core.security import encode_state

        login(api_anaf, admin.email)
        foreign = encode_state(
            {"organizationId": str(uuid.uuid4()), "userId": str(admin.id)},
            expires_in=timedelta(minutes=5),
        )

        response = api_anaf.post(f"{URL}/connect", json={"code": VALID_CODE, "state": foreign})

        assert response.status_code == 403

    def test_reauthorising_keeps_the_mandates(
        self, api_anaf: TestClient, admin: User, client_row: Client, db: Session
    ) -> None:
        """Cabinetul nu are de ce să le adauge din nou după un an."""
        login(api_anaf, admin.email)
        connect(api_anaf)
        add_mandate(api_anaf, client_row.id)

        body = connect(api_anaf)

        assert len(body["mandates"]) == 1

    def test_disconnecting_removes_the_token_but_not_the_invoices(
        self, api_anaf: TestClient, admin: User, client_row: Client, db: Session
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)
        add_mandate(api_anaf, client_row.id)
        db.add(
            Document(
                organization_id=admin.organization_id,
                client_id=client_row.id,
                status="RECEIVED",
                source="EFACTURA",
                original_filename="3001.xml",
                storage_key="organizations/x/documents/y/original/source.xml",
                mime_type="application/xml",
                file_size=10,
                sha256_hash="a" * 64,
                received_at=datetime.now(UTC),
            )
        )
        db.flush()

        assert api_anaf.delete(URL).status_code == 204

        assert db.scalars(select(AnafConnection)).all() == []
        assert db.scalars(select(AnafMandate)).all() == []
        # Probele contabile rămân (R8).
        assert len(db.scalars(select(Document)).all()) == 1


# ── Împuterniciri ────────────────────────────────────────────────────────────


class TestMandates:
    def test_the_tax_id_comes_from_the_client_normalised(
        self, api_anaf: TestClient, admin: User, client_row: Client
    ) -> None:
        """`RO10000101` și `10000101` sunt același cod; API-ul ANAF îl vrea pe al doilea."""
        login(api_anaf, admin.email)
        connect(api_anaf)

        body = add_mandate(api_anaf, client_row.id)

        assert body["taxId"] == TAX_ID
        assert body["clientName"] == "Alfa Conta SRL"

    def test_a_client_without_a_tax_id_is_refused_with_a_reason(
        self, api_anaf: TestClient, admin: User, db: Session, org: Organization
    ) -> None:
        nameless = Client(organization_id=org.id, name="Fara CUI SRL")
        db.add(nameless)
        db.flush()
        login(api_anaf, admin.email)
        connect(api_anaf)

        response = api_anaf.post(f"{URL}/mandates", json={"clientId": str(nameless.id)})

        assert response.status_code == 422
        assert "nu are CUI" in response.json()["message"]

    def test_the_same_client_cannot_be_added_twice(
        self, api_anaf: TestClient, admin: User, client_row: Client
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)
        add_mandate(api_anaf, client_row.id)

        response = api_anaf.post(f"{URL}/mandates", json={"clientId": str(client_row.id)})

        assert response.status_code == 409

    def test_the_same_tax_id_cannot_be_added_under_another_client(
        self, api_anaf: TestClient, admin: User, client_row: Client, db: Session, org: Organization
    ) -> None:
        """Două rânduri pe același CUI ar aduce fiecare factură de două ori."""
        twin = Client(organization_id=org.id, name="Alfa Conta Punct De Lucru", tax_id=TAX_ID)
        db.add(twin)
        db.flush()
        login(api_anaf, admin.email)
        connect(api_anaf)
        add_mandate(api_anaf, client_row.id)

        response = api_anaf.post(f"{URL}/mandates", json={"clientId": str(twin.id)})

        assert response.status_code == 409

    def test_a_client_from_another_organisation_is_not_found(
        self, api_anaf: TestClient, admin: User, db: Session
    ) -> None:
        """§72: apartenența se verifică, nu se presupune din identificator."""
        other_org = Organization(name="Alt Cabinet SRL")
        db.add(other_org)
        db.flush()
        foreign = Client(organization_id=other_org.id, name="Al Altuia SRL", tax_id="RO20000202")
        db.add(foreign)
        db.flush()
        login(api_anaf, admin.email)
        connect(api_anaf)

        response = api_anaf.post(f"{URL}/mandates", json={"clientId": str(foreign.id)})

        assert response.status_code == 404

    def test_a_mandate_can_be_paused_and_resumed(
        self, api_anaf: TestClient, admin: User, client_row: Client, db: Session
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)
        mandate = add_mandate(api_anaf, client_row.id)
        db.scalars(select(AnafMandate)).one().last_error = "Nu aveți dreptul…"
        db.flush()

        paused = api_anaf.patch(f"{URL}/mandates/{mandate['id']}", json={"isActive": False})
        assert paused.json()["isActive"] is False

        resumed = api_anaf.patch(f"{URL}/mandates/{mandate['id']}", json={"isActive": True})
        # Reactivată, nu mai arată eroarea de acum două luni.
        assert resumed.json()["lastError"] is None

    def test_removing_a_mandate_keeps_the_invoices(
        self, api_anaf: TestClient, admin: User, client_row: Client, db: Session
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)
        mandate = add_mandate(api_anaf, client_row.id)

        assert api_anaf.delete(f"{URL}/mandates/{mandate['id']}").status_code == 204
        assert db.scalars(select(AnafMandate)).all() == []

    def test_a_mandate_cannot_be_added_before_connecting(
        self, api_anaf: TestClient, admin: User, client_row: Client
    ) -> None:
        login(api_anaf, admin.email)

        response = api_anaf.post(f"{URL}/mandates", json={"clientId": str(client_row.id)})

        assert response.status_code == 409


# ── Sincronizare la cerere ───────────────────────────────────────────────────


class TestSyncingOnDemand:
    def test_the_run_brings_the_invoices_in(
        self, api_anaf: TestClient, admin: User, client_row: Client, anaf: FakeAnafClient
    ) -> None:
        login(api_anaf, admin.email)
        connect(api_anaf)
        add_mandate(api_anaf, client_row.id)
        anaf.put_invoice("3001", tax_id=TAX_ID)

        body = api_anaf.post(f"{URL}/sync").json()

        assert body["ingested"] == 1
        assert body["mandates"] == [TAX_ID]

    def test_syncing_without_a_connection_is_refused(
        self, api_anaf: TestClient, admin: User
    ) -> None:
        login(api_anaf, admin.email)

        assert api_anaf.post(f"{URL}/sync").status_code == 409


class TestTheThreeFilesComeOutAgain:
    """Preluarea fără scoatere nu ajută pe nimeni.

    La un control, arhiva cu sigiliul ANAF este dovada că factura a fost
    acceptată — și este singura dintre cele trei care nu se poate reface.
    """

    def _ingested(self, api: TestClient, anaf: FakeAnafClient, client_row: Client) -> dict:
        connect(api)
        add_mandate(api, client_row.id)
        anaf.put_invoice("3001", tax_id=TAX_ID)
        assert api.post(f"{URL}/sync").json()["ingested"] == 1

        listed = api.get("/api/v1/documents", params={"source": "EFACTURA"}).json()
        detail: dict = api.get(f"/api/v1/documents/{listed['items'][0]['id']}").json()
        return detail

    def test_the_detail_lists_all_three(
        self, api_anaf: TestClient, admin: User, client_row: Client, anaf: FakeAnafClient
    ) -> None:
        login(api_anaf, admin.email)

        detail = self._ingested(api_anaf, anaf, client_row)

        kinds = {entry["kind"] for entry in detail["files"]}
        assert kinds == {"original", "anaf_zip", "anaf_pdf"}
        # Eticheta vine de la server: interfața nu ține propria hartă.
        assert any("sigiliul" in entry["label"] for entry in detail["files"])

    def test_the_seal_can_be_downloaded(
        self, api_anaf: TestClient, admin: User, client_row: Client, anaf: FakeAnafClient
    ) -> None:
        login(api_anaf, admin.email)
        detail = self._ingested(api_anaf, anaf, client_row)
        seal = next(entry for entry in detail["files"] if entry["kind"] == "anaf_zip")

        response = api_anaf.get(f"/api/v1/documents/{detail['id']}/files/{seal['id']}")

        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        # Numele îl pune lângă factură în „Descărcări", nu într-un `document.zip`.
        assert "anaf-zip.zip" in response.headers["content-disposition"]

    def test_taking_a_file_out_is_audited(
        self,
        api_anaf: TestClient,
        admin: User,
        client_row: Client,
        anaf: FakeAnafClient,
        db: Session,
    ) -> None:
        from app.models.audit import AuditLog

        login(api_anaf, admin.email)
        detail = self._ingested(api_anaf, anaf, client_row)
        seal = next(entry for entry in detail["files"] if entry["kind"] == "anaf_zip")

        api_anaf.get(f"/api/v1/documents/{detail['id']}/files/{seal['id']}")

        actions = db.scalars(select(AuditLog.action)).all()
        assert "DOCUMENT_FILE_DOWNLOADED" in actions

    def test_a_file_of_another_document_is_not_found(
        self, api_anaf: TestClient, admin: User, client_row: Client, anaf: FakeAnafClient
    ) -> None:
        """§72: fișierul se caută prin document, nu direct după identificator."""
        login(api_anaf, admin.email)
        detail = self._ingested(api_anaf, anaf, client_row)
        seal = next(entry for entry in detail["files"] if entry["kind"] == "anaf_zip")

        response = api_anaf.get(f"/api/v1/documents/{uuid.uuid4()}/files/{seal['id']}")

        assert response.status_code == 404

    def test_an_ordinary_document_has_no_file_list(
        self, api_anaf: TestClient, admin: User, db: Session, org: Organization
    ) -> None:
        """Un singur fișier nu merită o listă: butonul de descărcare îl dă deja."""
        document = Document(
            organization_id=org.id,
            status="RECEIVED",
            source="UPLOAD",
            original_filename="scan.pdf",
            storage_key="organizations/x/documents/y/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="b" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(document)
        db.flush()
        login(api_anaf, admin.email)

        detail = api_anaf.get(f"/api/v1/documents/{document.id}").json()

        assert detail["files"] == []


# ── Autorizare de acces ──────────────────────────────────────────────────────


class TestWhoMayTouchThis:
    def test_an_operator_cannot_see_the_integration(
        self, api_anaf: TestClient, operator: User
    ) -> None:
        login(api_anaf, operator.email)

        assert api_anaf.get(URL).status_code == 403

    def test_an_anonymous_request_is_refused(self, api_anaf: TestClient) -> None:
        assert api_anaf.get(URL).status_code == 401
