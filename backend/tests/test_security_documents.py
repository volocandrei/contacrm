"""Revizuirea de securitate a suprafeței de documente (§72, §73, §74, §80).

Testele individuale există deja, împrăștiate prin suita de documente. Ce lipsea era
o trecere **sistematică**: fiecare rută, verificată pe aceleași trei întrebări.

Diferența contează. Un test punctual verifică ruta pe care ai scris-o azi; sweep-ul
de aici verifică și ruta pe care o va scrie altcineva peste șase luni, pentru că
lista de rute se citește din aplicație, nu din memoria cuiva.

Cele trei întrebări:

1. **Cere autentificare?** Nicio rută de documente nu răspunde fără sesiune.
2. **Se oprește la granița organizației?** Un document din altă firmă nu se
   distinge de unul inexistent — 404, nu 403: un 403 ar confirma că id-ul există.
3. **Scapă ceva intern?** Nicio cale de stocare, nicio cheie, niciun nume de bucket.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.document import DocumentType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"

# Fragmente care nu au voie să apară în niciun răspuns (§73).
INTERNAL_MARKERS = ("organizations/", "storageKey", "archiveKey", "archivePath", "/ARHIVA")


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
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def types(db: Session, org: Organization) -> dict[str, DocumentType]:
    from app.domain.document_types import DEFAULT_DOCUMENT_TYPES

    created: dict[str, DocumentType] = {}
    for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = DocumentType(
            organization_id=org.id,
            code=seed.code,
            label=seed.label,
            sort_order=index,
            required_fields=list(seed.required_fields),
        )
        db.add(row)
        created[seed.code] = row
    db.flush()
    return created


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
def intruder(db: Session, roles: dict[RoleCode, Role]) -> User:
    """Un ADMIN cu drepturi depline — dar în **altă** organizație."""
    other = Organization(name="Alt birou SRL")
    db.add(other)
    db.flush()
    return make_user(db, other, roles, email="strain@contacrm.test", role=RoleCode.ADMIN)


@pytest.fixture
def api_storage(api: TestClient, tmp_path: object) -> TestClient:
    from pathlib import Path

    from app.api.deps import get_storage
    from app.services.storage import LocalStorageProvider

    assert isinstance(tmp_path, Path)
    provider = LocalStorageProvider(tmp_path / "storage")
    api.app.dependency_overrides[get_storage] = lambda: provider  # type: ignore[attr-defined]
    return api


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def upload(api: TestClient, *, content: bytes = PDF, name: str = "factura.pdf") -> str:
    response = api.post(
        "/api/v1/documents/upload",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    document_id: str = response.json()["id"]
    return document_id


# ── Ce rute există ───────────────────────────────────────────────────────────


def document_routes(document_id: str) -> list[tuple[str, str, dict[str, object] | None]]:
    """Fiecare rută care atinge un document anume.

    Lista este scrisă de mână **deliberat**: dacă apare o rută nouă și nimeni nu o
    adaugă aici, `test_the_list_covers_every_route` cade și obligă la o decizie.
    """
    return [
        ("GET", f"/api/v1/documents/{document_id}", None),
        ("PATCH", f"/api/v1/documents/{document_id}", {"updates": []}),
        (
            "POST",
            f"/api/v1/documents/{document_id}/assign-client",
            {"clientId": str(uuid.uuid4())},
        ),
        ("POST", f"/api/v1/documents/{document_id}/approve", {}),
        ("POST", f"/api/v1/documents/{document_id}/reject", {"reason": "test"}),
        ("POST", f"/api/v1/documents/{document_id}/duplicate", {"duplicateOfId": None}),
        ("POST", f"/api/v1/documents/{document_id}/reprocess", {}),
        ("GET", f"/api/v1/documents/{document_id}/preview", None),
        ("GET", f"/api/v1/documents/{document_id}/download", None),
    ]


COLLECTION_ROUTES = [
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v1/documents/next-review"),
    ("GET", "/api/v1/document-types"),
    ("GET", "/api/v1/dashboard"),
    ("GET", "/api/v1/dashboard/counts"),
    ("GET", "/api/v1/periods"),
    ("GET", "/api/v1/periods/missing?referenceMonth=2026-08"),
    ("GET", "/api/v1/audit-logs"),
]

# Rute de colecție care cer un corp.
BODY_ROUTES = [
    (
        "POST",
        "/api/v1/documents/bulk",
        {"ids": [str(uuid.uuid4())], "payload": {"action": "approve"}},
    ),
]

# Rute de documente parametrizate pe altceva decât documentul. Granița lor de
# organizație se verifică prin clientul din cale, nu prin documentul din URL.
CLIENT_SCOPED_ROUTES = [
    ("GET", "/api/v1/clients/{client_id}/documents"),
    ("GET", "/api/v1/clients/{client_id}/periods"),
    ("POST", "/api/v1/clients/{client_id}/periods/2026-08/close"),
    ("POST", "/api/v1/clients/{client_id}/periods/2026-08/reopen"),
]


def call(api: TestClient, method: str, path: str, body: dict[str, object] | None) -> object:
    caller: Callable[..., object] = getattr(api, method.lower())
    return caller(path, json=body) if body is not None else caller(path)


def test_the_list_covers_every_route(api_storage: TestClient) -> None:
    """Sweep-ul nu are voie să rămână în urma aplicației.

    Dacă apare o rută de documente și nu este acoperită aici, testul cade — nu
    pentru că ruta ar fi greșită, ci pentru că nimeni nu a decis dacă are nevoie de
    verificările de mai jos.
    """
    declared = _declared_routes(api_storage)
    # Ceva trebuie să fi fost găsit: un sweep care nu descoperă nicio rută ar trece
    # oricând, și ar da exact încrederea pe care nu o merită.
    assert len(declared) >= 20, f"descoperire suspect de mică: {sorted(declared)}"

    # Formele din sweep, cu parametrul de cale înapoi în formă simbolică.
    covered = {
        (m, p.replace("PLACEHOLDER", "{document_id}")) for m, p, _ in document_routes("PLACEHOLDER")
    }
    covered |= {(method, path.split("?")[0]) for method, path in COLLECTION_ROUTES}
    covered |= {
        (method, template.split("?")[0].replace("2026-08", "{reference_month}"))
        for method, template in CLIENT_SCOPED_ROUTES
    }
    covered |= {("POST", "/api/v1/documents/upload"), ("POST", "/api/v1/documents/bulk")}

    missing = declared - covered
    assert not missing, f"rute neacoperite de revizuirea de securitate: {sorted(missing)}"


def _declared_routes(api: TestClient) -> set[tuple[str, str]]:
    """Rutele de documente și panou, citite din schema OpenAPI a aplicației.

    Schema, nu `app.routes`: routerele incluse nu sunt neapărat aplatizate în listă,
    iar o parcurgere care nu găsește nimic ar face testul să treacă degeaba.
    """
    schema = api.app.openapi()  # type: ignore[attr-defined]
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if (
            "/documents" in path
            or "/dashboard" in path
            or "/periods" in path
            or "/audit-logs" in path
        )
        and method.upper() not in {"HEAD", "OPTIONS"}
    }


# ── 1. Autentificare ─────────────────────────────────────────────────────────


class TestEveryRouteRequiresASession:
    def test_document_routes(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)
        api_storage.post("/api/v1/auth/logout")

        for method, path, body in document_routes(document_id):
            response = call(api_storage, method, path, body)
            assert response.status_code == 401, f"{method} {path}"

    def test_collection_routes(self, api_storage: TestClient) -> None:
        for method, path in COLLECTION_ROUTES:
            response = call(api_storage, method, path, None)
            assert response.status_code == 401, f"{method} {path}"

    def test_client_scoped_routes(self, api_storage: TestClient) -> None:
        for method, template in CLIENT_SCOPED_ROUTES:
            path = template.format(client_id=uuid.uuid4())
            body: dict[str, object] | None = {} if method == "POST" else None
            response = call(api_storage, method, path, body)
            assert response.status_code == 401, f"{method} {path}"

    def test_routes_with_a_body(self, api_storage: TestClient) -> None:
        for method, path, body in BODY_ROUTES:
            response = call(api_storage, method, path, body)
            assert response.status_code == 401, f"{method} {path}"

    def test_upload(self, api_storage: TestClient) -> None:
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
        )
        assert response.status_code == 401


# ── 2. Granița organizației (IDOR) ───────────────────────────────────────────


class TestTheOrganizationBoundaryHolds:
    def test_no_route_reveals_another_organizations_document(
        self,
        api_storage: TestClient,
        admin: User,
        intruder: User,
        types: dict[str, DocumentType],
    ) -> None:
        """404, nu 403: un 403 ar confirma că id-ul există (§72)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)
        api_storage.post("/api/v1/auth/logout")

        login(api_storage, intruder.email)
        for method, path, body in document_routes(document_id):
            response = call(api_storage, method, path, body)
            assert response.status_code == 404, f"{method} {path}"

    def test_the_intruder_sees_an_empty_world_not_an_error(
        self,
        api_storage: TestClient,
        admin: User,
        intruder: User,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)
        api_storage.post("/api/v1/auth/logout")

        login(api_storage, intruder.email)
        assert api_storage.get("/api/v1/documents").json()["total"] == 0
        assert api_storage.get("/api/v1/documents/next-review").json() is None
        assert api_storage.get("/api/v1/dashboard/counts").json()["inbox"] == 0

    def test_another_organizations_client_has_no_documents(
        self,
        api_storage: TestClient,
        admin: User,
        intruder: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        foreign_client = Client(organization_id=intruder.organization_id, name="Firma Străină")
        db.add(foreign_client)
        db.flush()

        login(api_storage, admin.email)
        upload(api_storage)
        for method, template in CLIENT_SCOPED_ROUTES:
            path = template.format(client_id=foreign_client.id)
            body: dict[str, object] | None = {} if method == "POST" else None
            response = call(api_storage, method, path, body)
            assert response.status_code == 404, f"{method} {path}"

    def test_a_client_from_another_organization_cannot_be_attached(
        self,
        api_storage: TestClient,
        admin: User,
        intruder: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        """Nici invers: documentul meu nu poate ajunge la clientul altcuiva."""
        foreign_client = Client(organization_id=intruder.organization_id, name="Firma Străină")
        db.add(foreign_client)
        db.flush()

        login(api_storage, admin.email)
        document_id = upload(api_storage)
        response = api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(foreign_client.id)},
        )
        assert response.status_code == 404


# ── 3. Nimic intern nu iese ──────────────────────────────────────────────────


class TestNothingInternalLeaves:
    def test_no_document_response_contains_a_storage_location(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)

        for path in (
            f"/api/v1/documents/{document_id}",
            "/api/v1/documents",
            "/api/v1/dashboard",
        ):
            body = api_storage.get(path).text
            for marker in INTERNAL_MARKERS:
                assert marker not in body, f"{marker!r} în {path}"

    def test_a_missing_file_does_not_name_what_is_missing(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        tmp_path: object,
        types: dict[str, DocumentType],
    ) -> None:
        """Un 404 nu are voie să spună ce cheie a căutat."""
        from app.models.document import Document

        login(api_storage, admin.email)
        document_id = upload(api_storage)
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.storage_key = f"organizations/{admin.organization_id}/documents/lipsa/x.pdf"
        db.flush()

        response = api_storage.get(f"/api/v1/documents/{document_id}/preview")
        assert response.status_code == 404
        for marker in INTERNAL_MARKERS:
            assert marker not in response.text

    def test_headers_never_carry_an_internal_path(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)

        response = api_storage.get(f"/api/v1/documents/{document_id}/download")
        joined = " ".join(f"{k}: {v}" for k, v in response.headers.items())
        for marker in INTERNAL_MARKERS:
            assert marker not in joined


# ── Conținut ostil ───────────────────────────────────────────────────────────


class TestHostileContent:
    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("executabil", b"MZ\x90\x00\x03" + b"\x00" * 512),
            ("script-shell", b"#!/bin/sh\nrm -rf /\n" + b"0" * 512),
            ("html-cu-script", b"<html><script>alert(1)</script></html>" + b"0" * 512),
            ("svg-cu-script", b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>' * 20),
            ("arhiva-zip", b"PK\x03\x04" + b"\x00" * 512),
            ("gol", b""),
        ],
    )
    def test_content_that_is_not_a_document_is_refused(
        self,
        api_storage: TestClient,
        admin: User,
        types: dict[str, DocumentType],
        name: str,
        content: bytes,
    ) -> None:
        """Tipul se stabilește din octeți, nu din ce declară clientul (§50)."""
        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": (f"{name}.pdf", io.BytesIO(content), "application/pdf")},
        )
        assert response.status_code == 422, f"{name}: {response.status_code}"

    @pytest.mark.parametrize(
        "hostile_name",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\cmd.pdf",
            "/absolut/factura.pdf",
            "C:\\Windows\\factura.pdf",
            "factura\x00.pdf",
            "CON.pdf",
            "  .  .pdf",
            "a" * 400 + ".pdf",
            '<img src=x onerror="alert(1)">.pdf',
        ],
    )
    def test_a_hostile_filename_never_becomes_a_path(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
        hostile_name: str,
    ) -> None:
        """Numele trimis de expeditor se păstrează ca text, dar nu atinge stocarea (R3, R7)."""
        from app.models.document import Document

        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={
                "file": (hostile_name, io.BytesIO(PDF + hostile_name.encode()), "application/pdf")
            },
        )
        assert response.status_code == 201, response.text

        document = db.get(Document, uuid.UUID(response.json()["id"]))
        assert document is not None
        key = document.storage_key
        assert ".." not in key
        assert "\\" not in key
        assert not key.startswith("/")
        assert "\x00" not in key
        # Cheia se **generează**: singura urmă a numelui primit este extensia.
        assert key.endswith("/original/source.pdf")

    def test_the_size_limit_is_enforced_while_reading(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Un fișier peste limită nu are voie să ajungă întreg în memorie."""
        from app.core.config import settings

        oversized = b"%PDF-1.7\n" + b"0" * (settings.max_upload_size_bytes + 1024)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("mare.pdf", io.BytesIO(oversized), "application/pdf")},
        )
        assert response.status_code in {401, 413, 422}

        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("mare.pdf", io.BytesIO(oversized), "application/pdf")},
        )
        assert response.status_code in {413, 422}


class TestTheApiIsOnlyWhereItSaysItIs:
    """Regresie: `api_router` era montat de două ori — cu prefix și fără.

    Autorizarea era aceeași pe ambele căi, deci nu se putea ajunge nicăieri în plus.
    Dar un reverse proxy configurat să protejeze `/api/*` ar fi lăsat descoperit
    exact același API pe `/documents`, iar versionarea nu ar mai fi însemnat nimic.
    """

    @pytest.mark.parametrize(
        "path",
        ["/documents", "/dashboard", "/dashboard/counts", "/document-types", "/clients"],
    )
    def test_the_api_is_not_reachable_without_the_version_prefix(
        self, api_storage: TestClient, path: str
    ) -> None:
        assert api_storage.get(path).status_code == 404

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
    def test_health_stays_reachable_without_the_prefix(
        self, api_storage: TestClient, path: str
    ) -> None:
        """Orchestratorul nu trebuie să știe versiunea API ca să întrebe dacă trăim."""
        assert api_storage.get(path).status_code == 200
