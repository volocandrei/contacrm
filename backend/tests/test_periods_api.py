"""API-ul perioadelor contabile (§18, §19).

Ce se verifică aici, dincolo de forma răspunsului: că nimic nu se stochează care se
poate calcula. Contoarele și statusul se derivă la citire, deci un document care își
schimbă luna sau clientul mută instantaneu progresul — fără niciun pas de
„recalculare" pe care cineva ar putea să-l uite.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import AccountingPeriod, ClientExpectation
from app.models.user import Permission, Role, User
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"
MONTH = "2026-08"


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
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def expectations(
    db: Session, org: Organization, client_row: Client, types: dict[str, DocumentType]
) -> dict[str, ClientExpectation]:
    """De la clientul ăsta se așteaptă două facturi de intrare și un extras."""
    created: dict[str, ClientExpectation] = {}
    for code, minimum in (("FACTURA_INTRARE", 2), ("EXTRAS_CONT", 1)):
        row = ClientExpectation(
            organization_id=org.id,
            client_id=client_row.id,
            document_type_id=types[code].id,
            expected_min_count=minimum,
        )
        db.add(row)
        created[code] = row
    db.flush()
    return created


@pytest.fixture
def storage_provider(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def api_storage(api: TestClient, storage_provider: LocalStorageProvider) -> TestClient:
    from app.api.deps import get_storage

    api.app.dependency_overrides[get_storage] = lambda: storage_provider  # type: ignore[attr-defined]
    return api


def login(api: TestClient, email: str) -> None:
    assert (
        api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def add_document(
    db: Session,
    org: Organization,
    client_row: Client,
    document_type: DocumentType,
    *,
    reference_month: str = MONTH,
    status: DocumentStatus = DocumentStatus.REVIEW_REQUIRED,
) -> Document:
    document = Document(
        organization_id=org.id,
        client_id=client_row.id,
        document_type_id=document_type.id,
        status=status,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        reference_month=reference_month,
    )
    db.add(document)
    db.flush()
    return document


# ── Lista de perioade ────────────────────────────────────────────────────────


class TestListing:
    def test_a_month_without_documents_is_not_invented(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Absența unei luni înseamnă că nu s-a întâmplat nimic în ea."""
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/periods").json() == []

    def test_a_month_exists_as_soon_as_a_document_lands_in_it(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        login(api_storage, admin.email)

        periods = api_storage.get("/api/v1/periods").json()
        assert len(periods) == 1
        assert periods[0]["referenceMonth"] == MONTH
        assert periods[0]["clientName"] == client_row.name
        # Nimeni nu a atins-o administrativ, deci nu are încă rând propriu.
        assert periods[0]["id"] is None
        assert periods[0]["openedAt"] is None

    def test_the_checklist_counts_what_actually_arrived(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        login(api_storage, admin.email)

        period = api_storage.get("/api/v1/periods").json()[0]
        by_type = {item["documentType"]: item for item in period["checklist"]}
        assert by_type["FACTURA_INTRARE"]["receivedCount"] == 2
        assert by_type["FACTURA_INTRARE"]["isSatisfied"] is True
        assert by_type["EXTRAS_CONT"]["receivedCount"] == 0
        assert by_type["EXTRAS_CONT"]["isSatisfied"] is False

    def test_an_extra_invoice_does_not_cover_a_missing_statement(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Regula după care se închide luna: dacă minte, se închide o lună goală."""
        for _ in range(10):
            add_document(db, org, client_row, types["FACTURA_INTRARE"])
        login(api_storage, admin.email)

        period = api_storage.get("/api/v1/periods").json()[0]
        assert period["receivedCount"] == 10
        assert period["satisfiedCount"] == 2
        assert period["expectedCount"] == 3
        assert period["status"] != "COMPLETE"

    def test_a_full_checklist_makes_the_month_complete(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["EXTRAS_CONT"])
        login(api_storage, admin.email)

        period = api_storage.get("/api/v1/periods").json()[0]
        assert period["status"] == "COMPLETE"
        assert period["satisfiedCount"] == period["expectedCount"]

    def test_duplicates_and_rejects_do_not_cover_an_obligation(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["EXTRAS_CONT"], status=DocumentStatus.DUPLICATE)
        add_document(db, org, client_row, types["FACTURA_INTRARE"], status=DocumentStatus.REJECTED)
        login(api_storage, admin.email)

        period = api_storage.get("/api/v1/periods").json()
        assert period == [] or period[0]["satisfiedCount"] == 0

    def test_moving_a_document_to_another_month_moves_the_progress(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Contoarele nu se stochează, deci nu au cum să rămână în urmă."""
        document = add_document(db, org, client_row, types["EXTRAS_CONT"])
        login(api_storage, admin.email)
        assert (
            api_storage.get(f"/api/v1/periods?referenceMonth={MONTH}").json()[0]["satisfiedCount"]
            == 1
        )

        document.reference_month = "2026-07"
        db.flush()

        assert api_storage.get(f"/api/v1/periods?referenceMonth={MONTH}").json() == []
        moved = api_storage.get("/api/v1/periods?referenceMonth=2026-07").json()
        assert moved[0]["satisfiedCount"] == 1

    def test_filters_narrow_the_list(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["FACTURA_INTRARE"], reference_month="2026-07")
        login(api_storage, admin.email)

        assert len(api_storage.get("/api/v1/periods").json()) == 2
        assert len(api_storage.get(f"/api/v1/periods?referenceMonth={MONTH}").json()) == 1
        assert len(api_storage.get(f"/api/v1/periods?clientId={client_row.id}").json()) == 2

    def test_an_invalid_month_is_refused(self, api_storage: TestClient, admin: User) -> None:
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/periods?referenceMonth=2026-13").status_code == 422
        assert api_storage.get("/api/v1/periods?referenceMonth=../..").status_code == 422


# ── Documente lipsă ──────────────────────────────────────────────────────────


class TestMissingReport:
    def test_only_clients_that_are_actually_short(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Un raport care listează și clienții în regulă nu se mai citește."""
        complete = Client(organization_id=org.id, name="Beta Complet SRL", tax_id="RO2")
        db.add(complete)
        db.flush()
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=complete.id,
                document_type_id=types["EXTRAS_CONT"].id,
                expected_min_count=1,
            )
        )
        db.flush()
        add_document(db, org, complete, types["EXTRAS_CONT"])
        add_document(db, org, client_row, types["FACTURA_INTRARE"])

        login(api_storage, admin.email)
        report = api_storage.get(f"/api/v1/periods/missing?referenceMonth={MONTH}").json()

        assert [entry["period"]["clientName"] for entry in report] == [client_row.name]
        missing = {item["documentType"] for item in report[0]["missing"]}
        assert missing == {"FACTURA_INTRARE", "EXTRAS_CONT"}

    def test_the_month_is_required(self, api_storage: TestClient, admin: User) -> None:
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/periods/missing").status_code == 422


# ── Închiderea lunii ─────────────────────────────────────────────────────────


class TestClosing:
    def _complete(
        self, db: Session, org: Organization, client_row: Client, types: dict[str, DocumentType]
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["EXTRAS_CONT"])

    def test_a_complete_month_can_be_closed(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        self._complete(db, org, client_row, types)
        login(api_storage, admin.email)

        response = api_storage.post(
            f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "FINALIZED"
        assert response.json()["closedAt"] is not None

    def test_an_incomplete_month_is_refused(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Închiderea este declarația că luna e gata; peste un checklist incomplet
        ar fi goală de sens."""
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        login(api_storage, admin.email)

        response = api_storage.post(
            f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={}
        )
        assert response.status_code == 409
        assert "lipsesc" in response.json()["message"].lower()

    def test_but_a_human_may_insist(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """Există motive legitime — un client care chiar nu a avut extras de cont —
        iar sistemul nu le cunoaște."""
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        login(api_storage, admin.email)

        response = api_storage.post(
            f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={"force": True}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "FINALIZED"

    def test_closing_twice_is_refused(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        self._complete(db, org, client_row, types)
        login(api_storage, admin.email)
        path = f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close"

        assert api_storage.post(path, json={}).status_code == 200
        assert api_storage.post(path, json={}).status_code == 409

    def test_a_closed_month_can_be_reopened(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        self._complete(db, org, client_row, types)
        login(api_storage, admin.email)
        api_storage.post(f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={})

        response = api_storage.post(f"/api/v1/clients/{client_row.id}/periods/{MONTH}/reopen")
        assert response.status_code == 200
        assert response.json()["closedAt"] is None
        assert response.json()["status"] == "COMPLETE"

    def test_both_acts_leave_a_trace(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        from sqlalchemy import select

        self._complete(db, org, client_row, types)
        login(api_storage, admin.email)
        api_storage.post(f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={})
        api_storage.post(f"/api/v1/clients/{client_row.id}/periods/{MONTH}/reopen")

        actions = [
            row.action
            for row in db.scalars(
                select(AuditLog).where(AuditLog.entity_type == "AccountingPeriod")
            ).all()
        ]
        assert actions == ["PERIOD_CLOSED", "PERIOD_REOPENED"]

    def test_an_operator_cannot_close_a_month(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        """A declara o lună gata este un act contabil, nu o consultare."""
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        login(api_storage, operator.email)

        response = api_storage.post(
            f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={}
        )
        assert response.status_code == 403


# ── Izolare ──────────────────────────────────────────────────────────────────


class TestIsolation:
    def test_periods_stop_at_the_organization_boundary(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])

        other = Organization(name="Alt birou")
        db.add(other)
        db.flush()
        intruder = make_user(db, other, roles, email="strain@contacrm.test", role=RoleCode.ADMIN)

        login(api_storage, intruder.email)
        assert api_storage.get("/api/v1/periods").json() == []
        assert api_storage.get(f"/api/v1/periods/missing?referenceMonth={MONTH}").json() == []
        assert (
            api_storage.post(
                f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={}
            ).status_code
            == 404
        )

    def test_every_route_requires_a_session(
        self, api_storage: TestClient, client_row: Client
    ) -> None:
        assert api_storage.get("/api/v1/periods").status_code == 401
        assert api_storage.get(f"/api/v1/periods/missing?referenceMonth={MONTH}").status_code == 401
        assert api_storage.get(f"/api/v1/clients/{client_row.id}/periods").status_code == 401
        assert (
            api_storage.post(
                f"/api/v1/clients/{client_row.id}/periods/{MONTH}/close", json={}
            ).status_code
            == 401
        )


# ── Legătura cu documentele ──────────────────────────────────────────────────


class TestDocumentsTouchPeriods:
    def test_uploading_and_processing_puts_the_document_in_a_month(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
        expectations: dict[str, ClientExpectation],
        storage_provider: LocalStorageProvider,
    ) -> None:
        """Luna se derivă din data documentului (ADR-008), fără să o ceară nimeni."""
        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("factura.pdf", io.BytesIO(PDF), "application/octet-stream")},
            data={"client_id": str(client_row.id)},
        )
        document_id = response.json()["id"]

        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.PROCESSING
        db.flush()

        from app.services.document_processing import DocumentProcessingService
        from app.services.extraction.mock import MockDocumentExtractionProvider

        DocumentProcessingService(db, storage_provider, MockDocumentExtractionProvider()).process(
            admin.organization_id, uuid.UUID(document_id)
        )

        db.refresh(document)
        assert document.reference_month is not None
        # Proveniența spune adevărul: derivată de o regulă, nu citită de model.
        assert document.field_metadata["referenceMonth"]["source"] == "DERIVED"

        from sqlalchemy import select as sa_select

        period = db.scalars(
            sa_select(AccountingPeriod).where(AccountingPeriod.client_id == client_row.id)
        ).first()
        assert period is not None, "luna trebuie să existe ca rând după procesare"
        assert period.reference_month == document.reference_month
