"""API-ul de documente, capăt la capăt.

Contractul verificat este cel pe care ecranele de documente și de verificare îl
consumă deja din backendul simulat.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentErrorCode, DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.audit import AuditLog
from app.models.client import Client
from app.models.document import (
    Document,
    DocumentFieldOverride,
    DocumentProcessingJob,
    DocumentType,
    DocumentVersion,
)
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.user import Permission, Role, User
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512
EXE = b"MZ\x90\x00\x03" + b"\x00" * 512


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
    user = User(
        organization_id=org.id,
        email=email,
        full_name="Ioana Marinescu",
        password_hash=__import__("app.core.security", fromlist=["hash_password"]).hash_password(
            PASSWORD
        ),
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
def storage_provider(tmp_path: Path) -> LocalStorageProvider:
    """Storage izolat, ca testele să nu scrie în `./storage`."""
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def api_storage(api: TestClient, storage_provider: LocalStorageProvider) -> TestClient:
    from app.api.deps import get_storage

    api.app.dependency_overrides[get_storage] = lambda: storage_provider  # type: ignore[attr-defined]
    return api


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _to_review(db: Session, document_id: str) -> None:
    """Aduce documentul in starea in care il va lasa workerul (M5.5)."""
    document = db.get(Document, uuid.UUID(document_id))
    assert document is not None
    document.status = DocumentStatus.PROCESSING
    db.flush()
    document.status = DocumentStatus.REVIEW_REQUIRED
    document.review_required = True
    db.flush()


def upload(api: TestClient, content: bytes = PDF, name: str = "factura.pdf") -> dict:  # type: ignore[type-arg]
    response = api.post(
        "/api/v1/documents/upload",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Upload ───────────────────────────────────────────────────────────────────


class TestUpload:
    def test_creates_a_document_and_returns_the_detail_shape(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        body = upload(api_storage)

        assert body["status"] == "RECEIVED"
        assert body["mimeType"] == "application/pdf"
        assert body["fileSize"] == len(PDF)
        assert len(body["sha256"]) == 64
        assert body["originalFilename"] == "factura.pdf"
        assert body["processingAttempts"] == 0

    def test_the_client_may_be_given_at_upload_time(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Operatorul știe adesea al cui este teancul, înainte de orice extracție.

        Câmpul se numește `clientId`, nu `client_id`: restul contractului este
        camelCase în ambele direcții, iar un singur câmp de formular scris altfel
        ar fi exact excepția pe care nimeni nu o ține minte.
        """
        login(api_storage, admin.email)

        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
            data={"clientId": str(client_row.id)},
        )

        assert response.status_code == 201, response.text
        assert response.json()["clientId"] == str(client_row.id)

    def test_without_a_client_nothing_is_assumed(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Identificarea vine din codul fiscal citit de pe document, nu de aici."""
        login(api_storage, admin.email)
        assert upload(api_storage)["clientId"] is None

    def test_never_exposes_a_storage_path(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Nicio cale internă nu iese prin API (§73)."""
        login(api_storage, admin.email)
        body = upload(api_storage)
        raw = str(body)

        assert "storagePath" not in body
        assert "storageKey" not in body
        assert "organizations/" not in raw

    def test_content_type_sent_by_the_client_is_ignored(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Clientul declară PDF, conținutul e JPEG: câștigă conținutul (§50)."""
        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("minte.pdf", io.BytesIO(JPEG), "application/pdf")},
        )
        assert response.status_code == 201
        assert response.json()["mimeType"] == "image/jpeg"

    def test_an_executable_is_refused(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/upload",
            files={"file": ("virus.pdf", io.BytesIO(EXE), "application/pdf")},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert response.json()["details"]["file"] == ["UNSUPPORTED_FORMAT"]

    def test_a_hostile_filename_does_not_reach_any_path(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        body = upload(api_storage, name="../../etc/passwd")

        document = db.get(Document, uuid.UUID(body["id"]))
        assert document is not None
        assert ".." not in document.storage_key
        assert "passwd" not in document.storage_key

    def test_upload_is_audited(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        body = upload(api_storage)

        entry = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "DOCUMENT_UPLOADED", AuditLog.entity_id == body["id"]
            )
        ).first()
        assert entry is not None
        assert entry.user_id == admin.id

    def test_a_second_identical_upload_is_marked_duplicate(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        first = upload(api_storage, name="a.pdf")
        second = upload(api_storage, name="alt-nume.pdf")

        assert second["isDuplicate"] is True
        assert second["status"] == "DUPLICATE"
        assert second["duplicateOfId"] == first["id"]


# ── Listă ────────────────────────────────────────────────────────────────────


class TestList:
    def test_returns_the_paginated_shape(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        body = api_storage.get("/api/v1/documents").json()
        assert set(body) == {"items", "page", "pageSize", "total", "totalPages"}
        assert set(body["items"][0]) == {
            "id",
            "originalFilename",
            "storedFilename",
            "clientId",
            "clientName",
            "documentTypeCode",
            "documentTypeLabel",
            "source",
            "receivedAt",
            "documentDate",
            "referenceMonth",
            "supplierName",
            "documentNumber",
            "totalAmount",
            "currency",
            "status",
            "confidence",
            "isDuplicate",
            "reviewRequired",
        }

    def test_list_is_lightweight(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Fără OCR, fără câmpuri, fără istoric (§64)."""
        login(api_storage, admin.email)
        upload(api_storage)
        item = api_storage.get("/api/v1/documents").json()["items"][0]

        for absent in ("ocr", "fields", "history", "sha256", "extraction"):
            assert absent not in item

    def test_rejects_a_sort_field_outside_the_whitelist(
        self, api_storage: TestClient, admin: User
    ) -> None:
        login(api_storage, admin.email)
        response = api_storage.get("/api/v1/documents", params={"sort": "ocr_text"})
        assert response.status_code == 422

    def test_rejects_sql_in_the_sort_parameter(self, api_storage: TestClient, admin: User) -> None:
        login(api_storage, admin.email)
        response = api_storage.get("/api/v1/documents", params={"sort": "id; DROP TABLE documents"})
        assert response.status_code == 422

    def test_filters_by_status(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage, name="a.pdf")
        upload(api_storage, name="b.pdf")  # duplicat

        body = api_storage.get("/api/v1/documents", params={"status": "DUPLICATE"}).json()
        assert body["total"] == 1


# ── Detaliu și câmpuri ───────────────────────────────────────────────────────


class TestDetailAndFields:
    def test_detail_carries_every_field_with_its_provenance(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        body = api_storage.get(f"/api/v1/documents/{upload(api_storage)['id']}").json()

        assert set(body["fields"]) == {
            "documentType",
            "documentDate",
            "series",
            "documentNumber",
            "supplierName",
            "supplierTaxId",
            "customerName",
            "customerTaxId",
            "currency",
            "subtotal",
            "vatAmount",
            "totalAmount",
            "referenceMonth",
        }
        # Un document neprocesat are toate câmpurile goale.
        assert body["fields"]["documentDate"] == {
            "value": None,
            "source": "EMPTY",
            "confidence": None,
        }

    def test_editing_a_field_marks_it_manual_and_drops_the_confidence(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        """O valoare corectată de om nu trebuie să pară extrasă de model (§32)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]

        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.field_metadata = {"supplierName": {"source": "AI", "confidence": 0.81}}
        document.supplier_name = "Furnizor Gresit SRL"
        db.flush()

        body = api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "supplierName", "value": "Furnizor Corect SRL"}]},
        ).json()

        assert body["fields"]["supplierName"] == {
            "value": "Furnizor Corect SRL",
            "source": "MANUAL",
            "confidence": None,
        }

    def test_a_correction_is_recorded_with_the_previous_confidence(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.field_metadata = {"documentNumber": {"source": "AI", "confidence": 0.55}}
        document.document_number = "F1"
        db.flush()

        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "documentNumber", "value": "F1023"}]},
        )

        override = db.scalars(
            select(DocumentFieldOverride).where(
                DocumentFieldOverride.document_id == uuid.UUID(document_id)
            )
        ).one()
        assert override.old_value == "F1"
        assert override.new_value == "F1023"
        assert override.previous_confidence == 0.55
        assert override.previous_source == "AI"
        assert override.changed_by == admin.id

    def test_an_unchanged_value_creates_no_history(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        """Un «salvează» fără modificări nu trebuie să umple istoricul."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "series", "value": "BX"}]},
        )
        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "series", "value": "BX"}]},
        )

        overrides = db.scalars(
            select(DocumentFieldOverride).where(
                DocumentFieldOverride.document_id == uuid.UUID(document_id)
            )
        ).all()
        assert len(overrides) == 1

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("documentDate", "nu-e-o-data"),
            ("referenceMonth", "2026-13"),
            ("referenceMonth", "2026-08-14"),
            ("totalAmount", "nu-e-un-numar"),
            ("currency", "PREA-LUNG"),
        ],
    )
    def test_invalid_values_are_refused(
        self,
        api_storage: TestClient,
        admin: User,
        types: dict[str, DocumentType],
        field: str,
        value: str,
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        response = api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": field, "value": value}]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    def test_an_unknown_field_is_refused(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        response = api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "ocrText", "value": "x"}]},
        )
        assert response.status_code == 422

    def test_amounts_travel_as_strings(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Un Decimal serializat ca număr JSON ar trece printr-un float (§72)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        body = api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "totalAmount", "value": "1190.55"}]},
        ).json()

        assert body["fields"]["totalAmount"]["value"] == "1190.55"
        assert body["totalAmount"] == "1190.55"


# ── Flux de aprobare ─────────────────────────────────────────────────────────


class TestWorkflow:
    def _ready(
        self, api: TestClient, db: Session, client_row: Client, types: dict[str, DocumentType]
    ) -> str:
        document_id = upload(api)["id"]
        # Pana la M5.5 nu exista worker; simulam tranzitia pe care o va face el.
        # Aprobarea unui document neprocesat ramane interzisa — vezi testul dedicat.
        _to_review(db, document_id)
        api.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": "F1023"},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                ]
            },
        )
        return document_id

    def test_approving_requires_the_mandatory_fields(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )

        response = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code == 422
        assert "obligatorii" in str(response.json()["details"])

    def test_approving_requires_a_client(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        response = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code == 422
        assert "client" in str(response.json()["details"]).lower()

    def test_a_complete_document_can_be_approved(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = self._ready(api_storage, db, client_row, types)

        body = api_storage.post(f"/api/v1/documents/{document_id}/approve").json()
        # Aprobarea arhivează în același pas: un document aprobat care nu a ajuns
        # în arhivă nu este nicăieri (§10, §11).
        assert body["status"] == "ARCHIVED"
        assert body["reviewRequired"] is False
        assert body["validationIssues"] == []
        assert body["storedFilename"] == "2026-08-14_Facturaintrare_AlfaContaSRL_F1023.pdf"

    def test_approving_twice_is_refused(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Din `ARCHIVED` nu se mai aprobă nimic (§40).

        A doua aprobare ar rescrie o probă contabilă deja arhivată; refuzul explicit
        este mai onest decât un 200 care nu face nimic.
        """
        login(api_storage, admin.email)
        document_id = self._ready(api_storage, db, client_row, types)
        api_storage.post(f"/api/v1/documents/{document_id}/approve")

        second = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert second.status_code == 409

    def test_an_unprocessed_document_cannot_be_approved(
        self,
        api_storage: TestClient,
        admin: User,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Nimic nu ajunge aprobat fara sa fi trecut prin procesare (§40)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        response = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_rejecting_requires_a_reason(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Un document respins fără motiv nu poate fi corectat de nimeni."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        response = api_storage.post(
            f"/api/v1/documents/{document_id}/reject", json={"reason": "   "}
        )
        assert response.status_code == 422

    def test_rejecting_records_the_reason(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        body = api_storage.post(
            f"/api/v1/documents/{document_id}/reject",
            json={"reason": "Document ilizibil."},
        ).json()

        assert body["status"] == "REJECTED"
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "DOCUMENT_REJECTED")).first()
        assert entry is not None and entry.detail == "Document ilizibil."

    def test_assigning_a_client_moves_an_unmatched_document_to_review(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.UNMATCHED
        db.flush()

        body = api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        ).json()
        assert body["status"] == "REVIEW_REQUIRED"
        assert body["clientName"] == "Alfa Conta SRL"

    def test_a_client_from_another_organization_cannot_be_assigned(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        foreign = Client(organization_id=other.id, name="Client Străin SRL")
        db.add(foreign)
        db.flush()

        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        response = api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(foreign.id)},
        )
        assert response.status_code == 404

    def test_history_shows_every_action(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = self._ready(api_storage, db, client_row, types)
        api_storage.post(f"/api/v1/documents/{document_id}/approve")

        history = api_storage.get(f"/api/v1/documents/{document_id}").json()["history"]
        actions = [entry["action"] for entry in history]
        # Aprobarea și arhivarea sunt două intrări distincte: prima este decizia
        # omului, a doua este actul sistemului.
        assert actions == [
            "DOCUMENT_UPLOADED",
            "DOCUMENT_CLIENT_ASSIGNED",
            "DOCUMENT_METADATA_UPDATED",
            "DOCUMENT_APPROVED",
            "DOCUMENT_ARCHIVED",
        ]
        assert all(entry["actor"] == admin.full_name for entry in history)


# ── Autorizare și izolare ────────────────────────────────────────────────────


class TestAuthorization:
    def test_every_route_requires_authentication(self, api_storage: TestClient) -> None:
        assert api_storage.get("/api/v1/documents").status_code == 401
        assert api_storage.get(f"/api/v1/documents/{uuid.uuid4()}").status_code == 401
        assert api_storage.get("/api/v1/document-types").status_code == 401
        assert (
            api_storage.post(
                "/api/v1/documents/upload",
                files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
            ).status_code
            == 401
        )

    def test_a_viewer_can_read_but_not_upload_or_edit(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        login(api_storage, viewer.email)

        assert api_storage.get("/api/v1/documents").status_code == 200
        assert (
            api_storage.post(
                "/api/v1/documents/upload",
                files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")},
            ).status_code
            == 403
        )

    def test_an_operator_can_edit_but_not_approve(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        login(api_storage, operator.email)

        document_id = upload(api_storage)["id"]
        assert (
            api_storage.patch(
                f"/api/v1/documents/{document_id}",
                json={"updates": [{"field": "series", "value": "BX"}]},
            ).status_code
            == 200
        )
        response = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_a_document_of_another_organization_is_not_found(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        """IDOR: schimbarea id-ului în URL nu arată documentul altcuiva (§72)."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        foreign = Document(
            organization_id=other.id,
            status=DocumentStatus.RECEIVED,
            source="UPLOAD",
            original_filename="strain.pdf",
            storage_key="organizations/x/documents/y/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="f" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(foreign)
        db.flush()

        login(api_storage, admin.email)
        assert api_storage.get(f"/api/v1/documents/{foreign.id}").status_code == 404
        assert (
            api_storage.patch(
                f"/api/v1/documents/{foreign.id}",
                json={"updates": [{"field": "series", "value": "X"}]},
            ).status_code
            == 404
        )
        assert api_storage.post(f"/api/v1/documents/{foreign.id}/approve").status_code == 404

    def test_documents_of_another_organization_are_not_listed(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        db.add(
            Document(
                organization_id=other.id,
                status=DocumentStatus.RECEIVED,
                source="UPLOAD",
                original_filename="strain.pdf",
                storage_key="organizations/x/documents/y/original/source.pdf",
                mime_type="application/pdf",
                file_size=10,
                sha256_hash="e" * 64,
                received_at=datetime.now(UTC),
            )
        )
        db.flush()

        body = api_storage.get("/api/v1/documents").json()
        assert body["total"] == 1
        assert body["items"][0]["originalFilename"] == "factura.pdf"


# ── Documentele unui client ──────────────────────────────────────────────────


class TestClientDocuments:
    def test_lists_only_that_client_documents(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        mine = upload(api_storage, name="a.pdf")
        api_storage.post(
            f"/api/v1/documents/{mine['id']}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        upload(api_storage, content=PDF + b"altceva", name="b.pdf")

        body = api_storage.get(f"/api/v1/clients/{client_row.id}/documents").json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == mine["id"]

    def test_the_client_filter_cannot_be_overridden_from_the_query(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Filtrul vine din calea rutei, nu din query."""
        other_client = Client(organization_id=client_row.organization_id, name="Beta SRL")
        db.add(other_client)
        db.flush()

        login(api_storage, admin.email)
        mine = upload(api_storage, name="a.pdf")
        api_storage.post(
            f"/api/v1/documents/{mine['id']}/assign-client",
            json={"clientId": str(client_row.id)},
        )

        body = api_storage.get(
            f"/api/v1/clients/{other_client.id}/documents",
            params={"clientId": str(client_row.id)},
        ).json()
        assert body["total"] == 0

    def test_an_unknown_client_is_not_found(self, api_storage: TestClient, admin: User) -> None:
        login(api_storage, admin.email)
        assert api_storage.get(f"/api/v1/clients/{uuid.uuid4()}/documents").status_code == 404


def test_document_types_are_listed_in_order(
    api_storage: TestClient, admin: User, types: dict[str, DocumentType]
) -> None:
    login(api_storage, admin.email)
    body = api_storage.get("/api/v1/document-types").json()

    assert [t["code"] for t in body][:2] == ["FACTURA_INTRARE", "FACTURA_IESIRE"]
    assert body[0]["requiredFields"] == [
        "documentDate",
        "documentNumber",
        "supplierName",
        "totalAmount",
    ]


# ── Coada de verificare și contoarele din bara laterală (M5.6) ───────────────


def _received_at(db: Session, document_id: str, when: datetime) -> None:
    """Ordinea cronologică se impune explicit: în teste două documente încărcate
    unul după altul pot ajunge la aceeași milisecundă."""
    document = db.get(Document, uuid.UUID(document_id))
    assert document is not None
    document.received_at = when
    db.flush()


class TestReviewQueue:
    def test_returns_the_oldest_waiting_document(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        first = upload(api_storage, name="prima.pdf")["id"]
        second = upload(api_storage, content=PDF + b"a doua", name="a-doua.pdf")["id"]
        _to_review(db, first)
        _to_review(db, second)
        _received_at(db, first, datetime(2026, 1, 1, tzinfo=UTC))
        _received_at(db, second, datetime(2026, 2, 1, tzinfo=UTC))

        assert api_storage.get("/api/v1/documents/next-review").json()["id"] == first

    def test_after_skips_the_document_just_closed(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        first = upload(api_storage, name="prima.pdf")["id"]
        second = upload(api_storage, content=PDF + b"a doua", name="a-doua.pdf")["id"]
        _to_review(db, first)
        _to_review(db, second)
        _received_at(db, first, datetime(2026, 1, 1, tzinfo=UTC))
        _received_at(db, second, datetime(2026, 2, 1, tzinfo=UTC))

        body = api_storage.get("/api/v1/documents/next-review", params={"after": first}).json()
        assert body["id"] == second

    def test_an_empty_queue_is_null_not_an_error(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)  # rămâne în RECEIVED: încă nu așteaptă un om

        response = api_storage.get("/api/v1/documents/next-review")
        assert response.status_code == 200
        assert response.json() is None

    def test_the_route_is_not_read_as_a_document_id(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Regresie: declarată dupa /documents/{id}, ar fi raspuns 422."""
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/documents/next-review").status_code == 200

    def test_documents_from_another_organization_are_not_offered(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        _to_review(db, upload(api_storage)["id"])

        other_org = Organization(name="Alt birou")
        db.add(other_org)
        db.flush()
        intruder = make_user(
            db, other_org, roles, email="strain@contacrm.test", role=RoleCode.ADMIN
        )

        api_storage.post("/api/v1/auth/logout")
        login(api_storage, intruder.email)
        assert api_storage.get("/api/v1/documents/next-review").json() is None


class TestAvailableActions:
    def test_detail_says_what_the_current_user_may_do(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        actions = api_storage.get(f"/api/v1/documents/{document_id}").json()["availableActions"]
        assert {"approve", "reject", "download"} <= set(actions)

    def test_an_operator_is_not_offered_approval(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        operator = make_user(db, org, roles, email="operator@contacrm.test", role=RoleCode.OPERATOR)
        login(api_storage, operator.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        actions = api_storage.get(f"/api/v1/documents/{document_id}").json()["availableActions"]
        assert "approve" not in actions
        # Corectarea câmpurilor este exact munca lui.
        assert "edit" in actions

    def test_what_the_list_refuses_the_route_refuses_too(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        """Lista este ergonomie, dar nu are voie sa contrazica ruta."""
        operator = make_user(
            db, org, roles, email="operator2@contacrm.test", role=RoleCode.OPERATOR
        )
        login(api_storage, operator.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        actions = api_storage.get(f"/api/v1/documents/{document_id}").json()["availableActions"]
        assert "approve" not in actions
        assert api_storage.post(f"/api/v1/documents/{document_id}/approve").status_code == 403

    def test_blockers_are_exactly_the_reasons_the_route_returns(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        blockers = api_storage.get(f"/api/v1/documents/{document_id}").json()["approvalBlockers"]
        assert any("client" in blocker.lower() for blocker in blockers)

        refused = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert refused.status_code == 422
        assert refused.json()["details"]["document"] == blockers


class TestSidebarCounts:
    def test_counts_group_documents_by_what_they_need(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        waiting = upload(api_storage, name="asteapta.pdf")["id"]
        upload(api_storage, content=PDF + b"in inbox", name="inbox.pdf")
        _to_review(db, waiting)

        body = api_storage.get("/api/v1/dashboard/counts").json()
        assert body == {"inbox": 1, "review": 1, "unmatched": 0, "tasks": 0}

    def test_counts_stop_at_the_organization_boundary(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        other_org = Organization(name="Alt birou")
        db.add(other_org)
        db.flush()
        intruder = make_user(
            db, other_org, roles, email="strain2@contacrm.test", role=RoleCode.ADMIN
        )
        api_storage.post("/api/v1/auth/logout")
        login(api_storage, intruder.email)

        assert api_storage.get("/api/v1/dashboard/counts").json()["inbox"] == 0

    def test_counting_requires_a_session(self, api_storage: TestClient) -> None:
        assert api_storage.get("/api/v1/dashboard/counts").status_code == 401


class TestReprocessAvailability:
    """Regresie găsită rulând serverul: lista oferea `reprocess` pe un document care
    își epuizase încercările, iar ruta răspundea 409."""

    def _exhaust(self, db: Session, document_id: str) -> None:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.processing_attempts = settings.max_processing_attempts
        db.flush()

    def test_reprocess_is_not_offered_once_the_attempts_are_spent(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        self._exhaust(db, document_id)

        body = api_storage.get(f"/api/v1/documents/{document_id}").json()
        assert "reprocess" not in body["availableActions"]
        assert api_storage.post(f"/api/v1/documents/{document_id}/reprocess").status_code == 409

    def test_the_reason_is_told_instead_of_the_button_simply_vanishing(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        self._exhaust(db, document_id)

        body = api_storage.get(f"/api/v1/documents/{document_id}").json()
        reason = body["reprocessBlockedReason"]
        assert reason is not None
        refused = api_storage.post(f"/api/v1/documents/{document_id}/reprocess")
        assert refused.json()["message"] == reason

    def test_a_document_that_can_be_reprocessed_has_no_reason(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        body = api_storage.get(f"/api/v1/documents/{document_id}").json()
        assert body["reprocessBlockedReason"] is None
        assert "reprocess" in body["availableActions"]

    def test_accepting_the_request_moves_the_document_into_processing(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        """Răspunsul 202 trebuie să și arate că s-a întâmplat ceva.

        Altfel ecranul, care se ține după status, nu are de unde ști că mai are ce
        aștepta — și rămâne pe datele vechi până la o reîncărcare manuală.
        """
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        response = api_storage.post(f"/api/v1/documents/{document_id}/reprocess")
        assert response.status_code == 202
        assert response.json()["status"] == "PROCESSING"


# ── Arhivare (§10, §11, M5.7) ────────────────────────────────────────────────


class TestArchiving:
    def _approve(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
        *,
        content: bytes = PDF,
        name: str = "factura.pdf",
        number: str = "F1023",
    ) -> dict:  # type: ignore[type-arg]
        document_id = upload(api, content=content, name=name)["id"]
        _to_review(db, document_id)
        api.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": number},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                    {"field": "referenceMonth", "value": "2026-08"},
                ]
            },
        )
        response = api.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code == 200, response.text
        return response.json()

    def test_approval_produces_the_standardised_name(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        assert body["status"] == "ARCHIVED"
        assert body["storedFilename"] == "2026-08-14_Facturaintrare_AlfaContaSRL_F1023.pdf"

    def test_the_archive_path_follows_the_convention(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        document = db.get(Document, uuid.UUID(body["id"]))
        assert document is not None
        assert document.archive_path == "/ARHIVA/2026/08/AlfaContaSRL/"

    def test_the_original_file_is_left_untouched(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
        storage_provider: LocalStorageProvider,
    ) -> None:
        """O probă contabilă nu se rescrie (§16): arhiva este o copie, nu o mutare."""
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        document = db.get(Document, uuid.UUID(body["id"]))
        assert document is not None
        assert storage_provider.exists(document.storage_key)
        assert document.archive_key is not None
        assert storage_provider.exists(document.archive_key)
        assert document.archive_key != document.storage_key

        with (
            storage_provider.open(document.storage_key) as original,
            storage_provider.open(document.archive_key) as archived,
        ):
            assert original.read() == archived.read()

    def test_a_version_row_records_the_archive_copy(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        versions = db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(body["id"]))
        ).all()
        # Originalul a fost înregistrat la încărcare; arhiva se adaugă lângă el,
        # nu în locul lui (§16).
        assert [v.kind for v in versions] == ["original", "archive"]
        assert versions[-1].storage_key != versions[0].storage_key
        assert versions[-1].sha256_hash == body["sha256"]

    def test_a_second_identical_document_gets_a_suffix(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Același client, aceeași lună, aceeași serie și număr → același nume."""
        login(api_storage, admin.email)
        first = self._approve(api_storage, db, client_row, types)
        second = self._approve(
            api_storage, db, client_row, types, content=PDF + b"altul", name="alta.pdf"
        )

        assert second["storedFilename"] != first["storedFilename"]
        assert second["storedFilename"] == first["storedFilename"].replace(".pdf", "_2.pdf")

    def test_the_database_refuses_two_documents_at_the_same_place(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Sufixul se alege în cod, dar unicitatea o garantează un index parțial.

        Fără el, două arhivări simultane ar putea alege același nume: fiecare caută
        înainte să scrie, și amândouă găsesc liber.
        """
        login(api_storage, admin.email)
        first = self._approve(api_storage, db, client_row, types)
        second = self._approve(
            api_storage, db, client_row, types, content=PDF + b"altul", name="alta.pdf"
        )

        intruder = db.get(Document, uuid.UUID(second["id"]))
        assert intruder is not None
        intruder.stored_filename = first["storedFilename"]
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_a_hostile_client_name_cannot_escape_the_archive_root(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        types: dict[str, DocumentType],
    ) -> None:
        hostile = Client(
            organization_id=org.id,
            name="..\\..\\windows\\system32",
            tax_id="RO999",
        )
        db.add(hostile)
        db.flush()

        login(api_storage, admin.email)
        body = self._approve(api_storage, db, hostile, types)

        document = db.get(Document, uuid.UUID(body["id"]))
        assert document is not None
        assert document.archive_path is not None
        assert ".." not in document.archive_path
        assert "\\" not in document.archive_path
        assert len([p for p in document.archive_path.split("/") if p]) == 4
        assert "\\" not in body["storedFilename"]
        assert "/" not in body["storedFilename"]

    def test_the_archive_location_never_leaves_through_the_api(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Nici cheia de stocare, nici calea de arhivă nu sunt treaba clientului (§73)."""
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        serialised = str(body)
        assert "archivePath" not in serialised
        assert "archiveKey" not in serialised
        assert "storageKey" not in serialised
        assert "organizations/" not in serialised

    def test_the_download_uses_the_standardised_name(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        response = api_storage.get(f"/api/v1/documents/{body['id']}/download")
        assert response.status_code == 200
        assert body["storedFilename"] in response.headers["Content-Disposition"]

    def test_archiving_is_recorded_in_the_audit_trail(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        entry = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == body["id"], AuditLog.action == "DOCUMENT_ARCHIVED"
            )
        ).one()
        assert entry.detail == body["storedFilename"]
        assert entry.user_name == admin.full_name

    def test_an_approved_document_is_no_longer_offered_for_approval(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        body = self._approve(api_storage, db, client_row, types)

        assert "approve" not in body["availableActions"]
        # Din arhivă se iese doar printr-o cerere explicită de reprocesare (§40).
        # Nici editarea nu se mai oferă: numele din arhivă codifică datele, deci o
        # corectură făcută pe loc l-ar face să mintă despre conținut.
        assert body["availableActions"] == ["reprocess", "download"]

    def test_a_missing_file_rolls_back_the_approval(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
        storage_provider: LocalStorageProvider,
    ) -> None:
        """Un document nu are voie să rămână aprobat cu arhiva goală.

        Ce se verifică aici este că cererea eșuează și că **nimic** din arhivă nu a
        fost scris. Anularea aprobării în sine o face `get_db`, care dă tranzacția
        înapoi la orice excepție — dar testele împart sesiunea cu aplicația, deci
        rollback-ul acela nu se poate observa de aici.
        """
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": "F1"},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                ]
            },
        )

        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        storage_provider.delete(document.storage_key)

        response = api_storage.post(f"/api/v1/documents/{document_id}/approve")
        assert response.status_code >= 400

        assert document.archive_key is None
        assert document.archive_path is None
        assert document.stored_filename is None
        assert document.archived_at is None
        assert document.error_code is DocumentErrorCode.ARCHIVE_FAILED


class TestArchivedDocumentsAreClosed:
    """Un document arhivat nu se mai corectează pe loc.

    Numele din arhivă codifică data, tipul, clientul, seria și numărul (§10). O
    corectură făcută direct l-ar lăsa să mintă despre conținut, și ar modifica în
    tăcere o probă contabilă deja închisă.
    """

    def _archived(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
    ) -> str:
        document_id = upload(api)["id"]
        _to_review(db, document_id)
        api.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": "F900"},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                ]
            },
        )
        assert api.post(f"/api/v1/documents/{document_id}/approve").status_code == 200
        return document_id

    def test_fields_cannot_be_edited_after_archiving(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = self._archived(api_storage, db, client_row)

        response = api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "supplierName", "value": "Altcineva SRL"}]},
        )
        assert response.status_code == 409
        assert "reprocesare" in response.json()["message"]

    def test_the_client_cannot_be_reassigned_after_archiving(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        other = Client(organization_id=org.id, name="Beta SRL", tax_id="RO2")
        db.add(other)
        db.flush()

        login(api_storage, admin.email)
        document_id = self._archived(api_storage, db, client_row)

        response = api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(other.id)},
        )
        assert response.status_code == 409

    def test_the_stored_name_survives_the_refused_edit(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = self._archived(api_storage, db, client_row)
        before = api_storage.get(f"/api/v1/documents/{document_id}").json()

        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "documentNumber", "value": "F999"}]},
        )

        after = api_storage.get(f"/api/v1/documents/{document_id}").json()
        assert after["storedFilename"] == before["storedFilename"]
        assert after["fields"]["documentNumber"]["value"] == "F900"

    def test_reprocessing_reopens_the_document_for_correction(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Drumul corect: din arhivă se iese printr-o cerere explicită, cu urmă în audit."""
        login(api_storage, admin.email)
        document_id = self._archived(api_storage, db, client_row)

        reopened = api_storage.post(f"/api/v1/documents/{document_id}/reprocess")
        assert reopened.status_code == 202
        assert reopened.json()["status"] == "PROCESSING"
        assert "edit" in reopened.json()["availableActions"]

        assert (
            api_storage.patch(
                f"/api/v1/documents/{document_id}",
                json={"updates": [{"field": "documentNumber", "value": "F999"}]},
            ).status_code
            == 200
        )


# ── Panoul principal ─────────────────────────────────────────────────────────


class TestSearchingInsideDocuments:
    """Căutarea se uita doar la ce e **despre** document, nu la ce scrie în el.

    Numele fișierului, numele standardizat, furnizorul, numărul, numele
    clientului — toate metadate. Textul citit de pe document stă în `ocr_text` de
    la M5 și era singurul lucru care nu se putea căuta, deși este exact ce caută
    un contabil: „unde e factura aia de la Orange din mai".
    """

    def _with_text(self, db: Session, document_id: str, text: str, client: Client) -> None:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.ocr_text = text
        document.client_id = client.id
        db.flush()

    def test_a_word_that_exists_only_in_the_body_is_found(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage, name="scan-oarecare.pdf")["id"]
        self._with_text(db, document_id, "Abonament telefonie Portocala Mobile SA", client_row)

        found = api_storage.get("/api/v1/documents", params={"q": "portocala"}).json()

        assert found["total"] == 1
        assert found["items"][0]["id"] == document_id

    def test_diacritics_do_not_have_to_match(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Textul OCR și ce scrie omul în căsuță diferă aproape întotdeauna prin ele."""
        login(api_storage, admin.email)
        document_id = upload(api_storage, name="scan-diacritice.pdf")["id"]
        self._with_text(db, document_id, "Servicii de distribuție și mentenanță", client_row)

        found = api_storage.get("/api/v1/documents", params={"q": "distributie"}).json()
        assert found["total"] == 1

    def test_the_stem_is_enough(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Configurarea `romanian` aduce rădăcina: „facturi" găsește „factura"."""
        login(api_storage, admin.email)
        document_id = upload(api_storage, name="scan-radacina.pdf")["id"]
        self._with_text(db, document_id, "Factura pentru servicii de consultanta", client_row)

        assert api_storage.get("/api/v1/documents", params={"q": "facturi"}).json()["total"] == 1

    def test_a_word_that_is_nowhere_finds_nothing(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Căutarea trebuie să și refuze, altfel nu este căutare."""
        login(api_storage, admin.email)
        document_id = upload(api_storage, name="scan-gol.pdf")["id"]
        self._with_text(db, document_id, "Text care nu conține cuvântul cerut", client_row)

        assert api_storage.get("/api/v1/documents", params={"q": "elicopter"}).json()["total"] == 0

    def test_a_document_without_text_does_not_break_the_search(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """`to_tsvector(NULL)` este `NULL`: rândul nu se potrivește, nu explodează."""
        login(api_storage, admin.email)
        upload(api_storage, name="fara-text.pdf")

        assert api_storage.get("/api/v1/documents", params={"q": "orice"}).status_code == 200

    def test_the_index_is_actually_usable(self, db: Session) -> None:
        """Un index pe expresie este mort dacă interogarea nu îl scrie identic.

        S-a mai întâmplat în proiectul ăsta: trei indexuri GIN trigram au stat
        nefolosite fiindcă interogarea împacheta coloana într-un `coalesce` pe
        care indexul nu îl avea, iar căutarea scana tot tabelul fără să se
        plângă nimeni.

        Se cere aici planificatorului să prefere indexuri. Dacă expresia din
        `_content_matches` s-ar despărți de cea din migrare, Postgres nu ar avea
        ce folosi și ar rămâne tot la scanare — exact ce prinde testul.
        """
        from app.repositories.document import _content_matches

        statement = select(Document.id).where(_content_matches("portocala"))
        compiled = statement.compile(db.get_bind(), compile_kwargs={"literal_binds": True})

        db.execute(sa_text("SET LOCAL enable_seqscan = off"))
        rows = db.execute(sa_text(f"EXPLAIN {compiled}")).all()
        plan = " | ".join(row[0] for row in rows)

        assert "ix_documents_ocr_text_fts" in plan, plan

    def test_the_body_text_still_never_leaves_in_a_listing(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Se caută în text, dar textul nu iese în listă (§64)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage, name="scan-secret.pdf")["id"]
        self._with_text(db, document_id, "Portocala Mobile SA sold restant 4210 lei", client_row)

        body = api_storage.get("/api/v1/documents", params={"q": "portocala"}).text
        assert "sold restant" not in body


class TestDashboard:
    def test_kpis_count_what_m5_can_actually_measure(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        waiting = upload(api_storage, name="asteapta.pdf")["id"]
        _to_review(db, waiting)

        kpis = api_storage.get("/api/v1/dashboard").json()["kpis"]
        assert kpis["clientsTotal"] == 1
        assert kpis["documentsNeedReview"] == 1
        assert kpis["documentsToday"] == 1
        # Perioadele contabile nu există încă: zero este adevărat, nu o omisiune.
        assert kpis["clientsComplete"] == 0
        assert kpis["clientsMissingDocs"] == 0

    def test_periods_are_empty_until_m6(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/dashboard").json()["periods"] == []

    def test_the_response_says_which_month_the_numbers_describe(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Altfel ecranul o ghicește — și o ghicea, scriind „August 2026" de mână.

        Luna o dau datele, nu calendarul: dacă un cabinet încarcă în octombrie
        documente din august, panoul trebuie să spună august.
        """
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        # Luna în lucru se numără doar pe documente atribuite: unul fără client nu
        # aparține încă niciunei luni contabile.
        document.client_id = client_row.id
        document.reference_month = "2026-08"
        db.flush()

        assert api_storage.get("/api/v1/dashboard").json()["referenceMonth"] == "2026-08"

    def test_without_any_document_no_month_is_invented(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """`null`, nu luna de azi: o instalare nouă nu are încă nicio lună în lucru."""
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/dashboard").json()["referenceMonth"] is None

    def test_the_trend_covers_every_day_even_the_empty_ones(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Un grafic care sare peste zilele goale arată un ritm care nu există."""
        login(api_storage, admin.email)
        upload(api_storage)

        trend = api_storage.get("/api/v1/dashboard").json()["trend"]

        assert len(trend) == 14
        days = [entry["day"] for entry in trend]
        # Zile consecutive, în ordine, fără goluri.
        assert days == sorted(days)
        assert len(set(days)) == 14
        # Documentul de azi se vede în ultima zi.
        assert trend[-1]["count"] == 1

    def test_the_trend_is_all_zeros_on_a_fresh_install(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Zero, nu listă goală: graficul trebuie să aibă ce desena."""
        login(api_storage, admin.email)

        trend = api_storage.get("/api/v1/dashboard").json()["trend"]

        assert len(trend) == 14
        assert {entry["count"] for entry in trend} == {0}

    def test_the_status_distribution_only_lists_what_exists(
        self, api_storage: TestClient, admin: User, db: Session, types: dict[str, DocumentType]
    ) -> None:
        """O felie de zero într-un grafic inelar este o minciună desenată."""
        login(api_storage, admin.email)
        upload(api_storage)

        slices = api_storage.get("/api/v1/dashboard").json()["byStatus"]

        assert all(entry["count"] > 0 for entry in slices)
        assert [entry["count"] for entry in slices] == sorted(
            (entry["count"] for entry in slices), reverse=True
        )

    def test_without_a_month_there_is_no_deadline(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """`null`, nu termenul lunii calendaristice: nu există nicio lună în lucru."""
        login(api_storage, admin.email)
        assert api_storage.get("/api/v1/dashboard").json()["closing"] is None

    def test_the_deadline_falls_in_the_month_after_the_one_being_closed(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Documentele lui august se depun în septembrie, nu în august."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.client_id = client_row.id
        document.reference_month = "2026-08"
        db.flush()

        closing = api_storage.get("/api/v1/dashboard").json()["closing"]
        assert closing["referenceMonth"] == "2026-08"
        assert closing["deadline"] == "2026-09-25"

    def test_a_december_month_rolls_into_the_next_year(self) -> None:
        """Decembrie se depune în ianuarie anul următor, nu în luna 13."""
        from app.api.v1.dashboard import filing_deadline

        assert filing_deadline("2026-12", day=25) == date(2027, 1, 25)

    def test_the_deadline_day_exists_in_february_too(self) -> None:
        """Configurarea mărginește ziua la 28 tocmai ca luna asta să nu rămână fără termen."""
        from app.api.v1.dashboard import filing_deadline

        assert filing_deadline("2027-01", day=28) == date(2027, 2, 28)

    def test_the_clients_who_still_owe_documents_are_named(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Panoul spunea *câți*; ca să fie de folos trebuie să spună **cine**."""
        login(api_storage, admin.email)
        db.add(
            ClientExpectation(
                organization_id=admin.organization_id,
                client_id=client_row.id,
                document_type_id=types["FACTURA_INTRARE"].id,
                expected_min_count=2,
            )
        )
        db.flush()
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.client_id = client_row.id
        document.reference_month = "2026-08"
        document.document_type_id = types["FACTURA_INTRARE"].id
        db.flush()

        closing = api_storage.get("/api/v1/dashboard").json()["closing"]
        assert closing["clientsWaiting"] == 1
        assert closing["laggards"][0]["clientName"] == client_row.name
        assert closing["laggards"][0]["missingCount"] == 1
        # Ce lipsește, în cuvintele tipului de document — nu un cod.
        assert closing["laggards"][0]["missing"] == [types["FACTURA_INTRARE"].label]

    def test_a_month_with_nothing_missing_has_no_laggards(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.client_id = client_row.id
        document.reference_month = "2026-08"
        db.flush()

        closing = api_storage.get("/api/v1/dashboard").json()["closing"]
        assert closing["clientsWaiting"] == 0
        assert closing["laggards"] == []

    def test_a_document_without_a_client_asks_for_attention(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.UNMATCHED
        db.flush()

        attention = api_storage.get("/api/v1/dashboard").json()["attention"]
        assert [item["reason"] for item in attention] == ["UNMATCHED_CLIENT"]
        assert attention[0]["documentId"] == document_id

    def test_a_document_stuck_in_processing_becomes_visible(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        """Fără asta, o cădere de proces nu se vede nicăieri (§43)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.PROCESSING
        db.flush()

        job = db.scalars(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.document_id == uuid.UUID(document_id)
            )
        ).first()
        assert job is not None, "upload-ul trebuie să înregistreze cererea în outbox"
        job.status = "RUNNING"
        job.created_at = datetime.now(UTC) - timedelta(hours=2)
        db.flush()

        reasons = [
            item["reason"] for item in api_storage.get("/api/v1/dashboard").json()["attention"]
        ]
        assert "STUCK_IN_PROCESSING" in reasons

    def test_a_freshly_queued_document_is_not_reported_as_stuck(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        reasons = [
            item["reason"] for item in api_storage.get("/api/v1/dashboard").json()["attention"]
        ]
        assert "STUCK_IN_PROCESSING" not in reasons

    def test_recent_documents_come_newest_first(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        older = upload(api_storage, name="veche.pdf")["id"]
        newer = upload(api_storage, content=PDF + b"noua", name="noua.pdf")["id"]
        db.get(Document, uuid.UUID(older)).received_at = datetime(2026, 1, 1, tzinfo=UTC)  # type: ignore[union-attr]
        db.get(Document, uuid.UUID(newer)).received_at = datetime(2026, 2, 1, tzinfo=UTC)  # type: ignore[union-attr]
        db.flush()

        recent = api_storage.get("/api/v1/dashboard").json()["recentDocuments"]
        assert [d["id"] for d in recent] == [newer, older]

    def test_the_timeline_is_the_audit_trail(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        """Nu există un al doilea jurnal (§33)."""
        login(api_storage, admin.email)
        upload(api_storage)

        timeline = api_storage.get("/api/v1/dashboard").json()["timeline"]
        assert timeline
        assert timeline[0]["kind"] == "DOCUMENTS_RECEIVED"
        assert admin.full_name in timeline[0]["description"]

    def test_the_dashboard_stops_at_the_organization_boundary(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        other_org = Organization(name="Alt birou")
        db.add(other_org)
        db.flush()
        intruder = make_user(
            db, other_org, roles, email="strain3@contacrm.test", role=RoleCode.ADMIN
        )
        api_storage.post("/api/v1/auth/logout")
        login(api_storage, intruder.email)

        body = api_storage.get("/api/v1/dashboard").json()
        assert body["recentDocuments"] == []
        assert body["attention"] == []
        assert body["timeline"] == []
        assert body["kpis"]["documentsToday"] == 0

    def test_the_dashboard_requires_a_session(self, api_storage: TestClient) -> None:
        assert api_storage.get("/api/v1/dashboard").status_code == 401


class TestTodayIsALocalDay:
    def test_a_document_from_yesterday_evening_is_not_counted_today(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        """„Azi" nu înseamnă „ultimele 24 de ore" (§71)."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None

        zone = ZoneInfo(settings.default_timezone)
        yesterday_evening = (datetime.now(zone) - timedelta(days=1)).replace(hour=23, minute=30)
        document.received_at = yesterday_evening.astimezone(UTC)
        db.flush()

        assert api_storage.get("/api/v1/dashboard").json()["kpis"]["documentsToday"] == 0

    def test_a_document_from_this_morning_is_counted(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None

        zone = ZoneInfo(settings.default_timezone)
        this_morning = datetime.now(zone).replace(hour=0, minute=1, second=0, microsecond=0)
        document.received_at = this_morning.astimezone(UTC)
        db.flush()

        assert api_storage.get("/api/v1/dashboard").json()["kpis"]["documentsToday"] == 1


class TestAuditOrdering:
    """Un jurnal care nu se poate ordona nu spune ce s-a întâmplat după ce."""

    def test_entries_written_in_the_same_request_keep_their_order(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        api_storage.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": "F1"},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                ]
            },
        )
        # Aprobarea și arhivarea sunt scrise în **aceeași** tranzacție. Cu `now()`,
        # ambele ar primi timestampul de început al tranzacției și ordinea ar fi
        # arbitrară; cu `clock_timestamp()` sunt două momente distincte.
        api_storage.post(f"/api/v1/documents/{document_id}/approve")

        history = api_storage.get(f"/api/v1/documents/{document_id}").json()["history"]
        actions = [entry["action"] for entry in history]
        assert actions.index("DOCUMENT_APPROVED") < actions.index("DOCUMENT_ARCHIVED")
        assert actions[0] == "DOCUMENT_UPLOADED"

        moments = [entry["at"] for entry in history]
        assert moments == sorted(moments)
        assert len(set(moments)) == len(moments), "două intrări nu pot avea același moment"


# ── Acțiuni în masă (§26) ────────────────────────────────────────────────────


class TestBulkActions:
    def _ready(self, api: TestClient, db: Session, client_row: Client, *, number: str) -> str:
        document_id = upload(api, content=PDF + number.encode(), name=f"{number}.pdf")["id"]
        _to_review(db, document_id)
        api.post(
            f"/api/v1/documents/{document_id}/assign-client",
            json={"clientId": str(client_row.id)},
        )
        api.patch(
            f"/api/v1/documents/{document_id}",
            json={
                "updates": [
                    {"field": "documentType", "value": "FACTURA_INTRARE"},
                    {"field": "documentDate", "value": "2026-08-14"},
                    {"field": "documentNumber", "value": number},
                    {"field": "supplierName", "value": "Furnizor SRL"},
                    {"field": "totalAmount", "value": "1190.00"},
                ]
            },
        )
        return document_id

    def test_one_failure_does_not_undo_the_others(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Operatorul a apăsat un buton, dar a luat trei decizii."""
        login(api_storage, admin.email)
        good = self._ready(api_storage, db, client_row, number="B1")
        other = self._ready(api_storage, db, client_row, number="B2")
        # Al treilea nu are client, deci aprobarea lui va eșua.
        broken = upload(api_storage, content=PDF + b"fara-client", name="fara.pdf")["id"]
        _to_review(db, broken)

        body = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [good, broken, other], "payload": {"action": "approve"}},
        ).json()

        assert set(body["succeeded"]) == {good, other}
        assert [f["id"] for f in body["failed"]] == [broken]
        # Motivul, nu doar numărul: „au eșuat 7 documente" este inutilizabil.
        assert "client" in body["failed"][0]["message"].lower()

        assert api_storage.get(f"/api/v1/documents/{good}").json()["status"] == "ARCHIVED"
        assert api_storage.get(f"/api/v1/documents/{broken}").json()["status"] == "REVIEW_REQUIRED"

    def test_rejecting_in_bulk_requires_a_reason(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        document_id = self._ready(api_storage, db, client_row, number="B3")

        body = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [document_id], "payload": {"action": "reject"}},
        ).json()
        assert body["succeeded"] == []
        assert len(body["failed"]) == 1

        body = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [document_id], "payload": {"action": "reject", "reason": "Ilizibil."}},
        ).json()
        assert body["succeeded"] == [document_id]

    def test_assigning_a_client_in_bulk(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        first = upload(api_storage, content=PDF + b"a", name="a.pdf")["id"]
        second = upload(api_storage, content=PDF + b"b", name="b.pdf")["id"]

        body = api_storage.post(
            "/api/v1/documents/bulk",
            json={
                "ids": [first, second],
                "payload": {"action": "assignClient", "clientId": str(client_row.id)},
            },
        ).json()

        assert set(body["succeeded"]) == {first, second}
        assert api_storage.get(f"/api/v1/documents/{first}").json()["clientId"] == str(
            client_row.id
        )

    def test_an_operator_may_reprocess_but_not_approve(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Permisiunea se verifică pe acțiune, nu pe rută."""
        operator = make_user(
            db, org, roles, email="operator-bulk@contacrm.test", role=RoleCode.OPERATOR
        )
        login(api_storage, operator.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)

        refused = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [document_id], "payload": {"action": "approve"}},
        )
        assert refused.status_code == 403

        allowed = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [document_id], "payload": {"action": "reprocess"}},
        )
        assert allowed.status_code == 200
        assert allowed.json()["succeeded"] == [document_id]

    def test_an_empty_batch_is_refused(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        login(api_storage, admin.email)
        response = api_storage.post(
            "/api/v1/documents/bulk", json={"ids": [], "payload": {"action": "approve"}}
        )
        assert response.status_code == 422

    def test_a_document_from_another_organization_simply_fails(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        roles: dict[RoleCode, Role],
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Nu 404 pe tot lotul: restul documentelor sunt ale utilizatorului."""
        login(api_storage, admin.email)
        mine = self._ready(api_storage, db, client_row, number="B4")

        other_org = Organization(name="Alt birou")
        db.add(other_org)
        db.flush()
        stranger = Document(
            organization_id=other_org.id,
            status=DocumentStatus.REVIEW_REQUIRED,
            source=DocumentSource.UPLOAD,
            original_filename="strain.pdf",
            storage_key=f"organizations/{other_org.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="f" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(stranger)
        db.flush()

        body = api_storage.post(
            "/api/v1/documents/bulk",
            json={"ids": [mine, str(stranger.id)], "payload": {"action": "approve"}},
        ).json()

        assert body["succeeded"] == [mine]
        assert [f["id"] for f in body["failed"]] == [str(stranger.id)]


# ── Jurnalul de audit (§33) ──────────────────────────────────────────────────


class TestAuditLogApi:
    def test_it_lists_what_happened(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        body = api_storage.get("/api/v1/audit-logs").json()
        actions = [entry["action"] for entry in body["items"]]
        assert "DOCUMENT_UPLOADED" in actions
        assert body["total"] >= 2  # login + upload

    def test_it_is_newest_first(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage, name="prima.pdf")
        upload(api_storage, content=PDF + b"a doua", name="a-doua.pdf")

        moments = [entry["at"] for entry in api_storage.get("/api/v1/audit-logs").json()["items"]]
        assert moments == sorted(moments, reverse=True)

    def test_filters_narrow_the_list(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        filtered = api_storage.get("/api/v1/audit-logs?action=DOCUMENT_UPLOADED").json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["action"] == "DOCUMENT_UPLOADED"

        by_entity = api_storage.get("/api/v1/audit-logs?entityType=Document").json()
        assert all(e["entityType"] == "Document" for e in by_entity["items"])

    def test_search_treats_percent_as_text(
        self, api_storage: TestClient, admin: User, types: dict[str, DocumentType]
    ) -> None:
        """Un `%` scris de utilizator înseamnă procent, nu „orice"."""
        login(api_storage, admin.email)
        upload(api_storage)

        assert api_storage.get("/api/v1/audit-logs?q=%25").json()["total"] == 0

    def test_values_never_leave_through_the_api(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Auditul răspunde la „cine, ce, când", nu la „ce scria pe factură"."""
        login(api_storage, admin.email)
        document_id = upload(api_storage)["id"]
        _to_review(db, document_id)
        api_storage.patch(
            f"/api/v1/documents/{document_id}",
            json={"updates": [{"field": "supplierName", "value": "Furnizor Secret SRL"}]},
        )

        body = api_storage.get("/api/v1/audit-logs").text
        assert "Furnizor Secret SRL" not in body
        assert "oldValue" not in body
        assert "newValue" not in body

    def test_it_stops_at_the_organization_boundary(
        self,
        api_storage: TestClient,
        admin: User,
        db: Session,
        roles: dict[RoleCode, Role],
        types: dict[str, DocumentType],
    ) -> None:
        login(api_storage, admin.email)
        upload(api_storage)

        other_org = Organization(name="Alt birou")
        db.add(other_org)
        db.flush()
        intruder = make_user(
            db, other_org, roles, email="strain-audit@contacrm.test", role=RoleCode.ADMIN
        )
        api_storage.post("/api/v1/auth/logout")
        login(api_storage, intruder.email)

        actions = [e["action"] for e in api_storage.get("/api/v1/audit-logs").json()["items"]]
        assert actions == ["USER_LOGIN"]

    def test_an_operator_cannot_read_the_audit_log(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
    ) -> None:
        operator = make_user(
            db, org, roles, email="operator-audit@contacrm.test", role=RoleCode.OPERATOR
        )
        login(api_storage, operator.email)
        assert api_storage.get("/api/v1/audit-logs").status_code == 403
