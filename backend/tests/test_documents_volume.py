"""Cum se poartă listele când sunt multe documente (§64, §67).

Nu măsurăm secunde: un test cronometrat cade când mașina e ocupată și trece când
nu e, deci nu spune nimic. Măsurăm **numărul de interogări**, care este cauza
adevărată: o listă care face o interogare per rând merge bine pe zece documente și
cade pe zece mii, iar diferența nu se vede în niciun test funcțional.

Regula verificată: numărul de interogări nu are voie să crească odată cu numărul de
rânduri returnate.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"

# Cât de multe documente semănăm. Destule ca o interogare per rând să se vadă
# limpede, destul de puține ca testul să rămână rapid.
SEEDED = 60


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
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    from app.core.security import hash_password

    user = User(
        organization_id=org.id,
        email="admin@contacrm.test",
        full_name="Ioana Marinescu",
        password_hash=hash_password(PASSWORD),
        roles=[roles[RoleCode.ADMIN]],
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def api_storage(api: TestClient, tmp_path: object) -> TestClient:
    from pathlib import Path

    from app.api.deps import get_storage
    from app.services.storage import LocalStorageProvider

    assert isinstance(tmp_path, Path)
    provider = LocalStorageProvider(tmp_path / "storage")
    api.app.dependency_overrides[get_storage] = lambda: provider  # type: ignore[attr-defined]
    return api


@pytest.fixture
def populated(db: Session, org: Organization) -> list[Document]:
    """Documente pe mai mulți clienți și mai multe tipuri.

    Diversitatea contează: o listă care încarcă lene clientul sau tipul face o
    interogare în plus **per valoare distinctă**, nu per rând, iar cu un singur
    client N+1 s-ar ascunde.
    """
    clients = []
    for index in range(6):
        client = Client(organization_id=org.id, name=f"Client {index}", tax_id=f"RO{index}")
        db.add(client)
        clients.append(client)

    types = []
    for index, code in enumerate(("FACTURA_INTRARE", "BON_FISCAL", "CHITANTA")):
        document_type = DocumentType(
            organization_id=org.id,
            code=code,
            label=code.title(),
            sort_order=index,
            required_fields=[],
        )
        db.add(document_type)
        types.append(document_type)
    db.flush()

    documents = []
    for index in range(SEEDED):
        document = Document(
            organization_id=org.id,
            client_id=clients[index % len(clients)].id,
            document_type_id=types[index % len(types)].id,
            status=DocumentStatus.REVIEW_REQUIRED,
            source=DocumentSource.UPLOAD,
            original_filename=f"document-{index}.pdf",
            storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256_hash=f"{index:064d}",
            received_at=datetime.now(UTC) - timedelta(minutes=index),
            supplier_name=f"Furnizor {index % 7} SRL",
        )
        db.add(document)
        documents.append(document)
    db.flush()
    return documents


@contextmanager
def counted(db: Session) -> Iterator[list[str]]:
    """Numără interogările SQL care pleacă în timpul blocului."""
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    engine = db.get_bind()
    sa.event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        sa.event.remove(engine, "before_cursor_execute", before)


def login(api: TestClient, email: str) -> None:
    assert (
        api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


class TestListingDoesNotGrowQueriesWithRows:
    def test_the_query_count_is_the_same_for_five_rows_and_for_fifty(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        login(api_storage, admin.email)
        # O cerere de încălzire: prima aduce rolurile și permisiunile utilizatorului
        # și scrie auditul de login. Fără ea am compara o pornire la rece cu o
        # sesiune caldă, iar diferența nu ar avea nimic de-a face cu numărul de rânduri.
        api_storage.get("/api/v1/documents", params={"pageSize": 1})

        with counted(db) as few:
            small = api_storage.get("/api/v1/documents", params={"pageSize": 5})
        with counted(db) as many:
            large = api_storage.get("/api/v1/documents", params={"pageSize": 50})

        assert len(small.json()["items"]) == 5
        assert len(large.json()["items"]) == 50
        assert len(few) == len(many), (
            f"lista face mai multe interogări pentru mai multe rânduri: "
            f"{len(few)} vs {len(many)} — probabil N+1"
        )

    def test_a_page_costs_a_handful_of_queries_not_one_per_row(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        login(api_storage, admin.email)

        with counted(db) as statements:
            api_storage.get("/api/v1/documents", params={"pageSize": 50})

        # Sesiune, utilizator, numărare, rânduri — o mână, nu 50.
        assert len(statements) < 12, "\n".join(statements)

    def test_search_does_not_scan_per_row(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        login(api_storage, admin.email)

        with counted(db) as statements:
            response = api_storage.get(
                "/api/v1/documents", params={"q": "Furnizor", "pageSize": 50}
            )

        assert response.status_code == 200
        assert len(statements) < 12


class TestTheDashboardStaysCheap:
    def test_the_dashboard_is_a_fixed_number_of_queries(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        """Panoul este primul ecran după login: nu are voie să coste cât arhiva."""
        login(api_storage, admin.email)

        with counted(db) as statements:
            assert api_storage.get("/api/v1/dashboard").status_code == 200

        assert len(statements) < 25, "\n".join(statements)


class TestHeavyColumnsStayOutOfTheList:
    def test_the_ocr_text_is_never_selected_for_a_listing(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        """Textul OCR poate fi de sute de kilobiți per document (§64)."""
        for document in populated[:5]:
            document.ocr_text = "x" * 50_000
        db.flush()

        login(api_storage, admin.email)
        with counted(db) as statements:
            api_storage.get("/api/v1/documents", params={"pageSize": 50})

        listing = [s for s in statements if "FROM documents" in s]
        assert listing, "nicio interogare pe documents?"
        offenders = [s for s in listing if "ocr_text" in s]
        assert not offenders, "textul OCR ajunge in lista: " + " | ".join(offenders)


class TestUploadCostIsIndependentOfHistory:
    def test_uploading_the_sixtieth_document_costs_like_the_first(
        self, api_storage: TestClient, admin: User, db: Session, populated: list[Document]
    ) -> None:
        """Detecția duplicatelor caută după hash, nu compară cu tot ce există."""
        login(api_storage, admin.email)

        content = b"%PDF-1.7\n" + b"0" * 600 + b"\n%%EOF"
        with counted(db) as statements:
            response = api_storage.post(
                "/api/v1/documents/upload",
                files={"file": ("noua.pdf", io.BytesIO(content), "application/pdf")},
            )

        assert response.status_code == 201
        assert len(statements) < 30, "\n".join(statements)
