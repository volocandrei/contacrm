"""Cronologia recepțiilor (M12).

Ecranul „Mesaje" cerea `GET /messages`, o rută care nu a existat niciodată: în
modul simulat mergea, în cel real rămânea gol fără să spună nimic. Auditul de
producție l-a scos. Ce a rămas neobservat este că **jumătate din cronologie
exista deja în date**: fiecare atașament de email, fiecare fișier din OneDrive și
fiecare factură din SPV lasă un `document_intakes` cu expeditorul și momentul.

Ce se apără aici, în ordinea gravității:

1. `raw_payload` **nu iese** — poartă căi din OneDrive și identificatori interni
   ai furnizorului (§73).
2. Granița organizației ține, iar filtrul pe client vine din calea rutei.
3. O recepție respinsă apare cu motivul ei: altfel un atașament care nu a devenit
   document dispare fără urmă, iar cineva îl caută degeaba.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus, IntakeStatus
from app.domain.permissions import RoleCode
from app.models.client import Client
from app.models.document import Document, DocumentIntake
from app.models.organization import Organization
from app.models.user import Role, User
from tests.conftest import requires_db
from tests.test_crm_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

SECRET_PATH = "organizations/secret/documents/scapat"


def _intake(
    db: Session,
    org: Organization,
    *,
    sender: str,
    filename: str,
    source: DocumentSource = DocumentSource.EMAIL,
    status: IntakeStatus = IntakeStatus.ACCEPTED,
    document: Document | None = None,
    rejection: str | None = None,
) -> DocumentIntake:
    intake = DocumentIntake(
        organization_id=org.id,
        source=source,
        status=status,
        sender=sender,
        subject="Documente august",
        original_filename=filename,
        received_at=datetime.now(UTC),
        raw_payload={"drivePath": SECRET_PATH, "size": 1234},
        document_id=document.id if document else None,
        rejection_reason=rejection,
    )
    db.add(intake)
    db.flush()
    return intake


def _document(db: Session, org: Organization, client: Client | None) -> Document:
    document = Document(
        organization_id=org.id,
        client_id=client.id if client else None,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.EMAIL,
        original_filename="factura.pdf",
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/pdf",
        file_size=10,
        sha256_hash="a" * 64,
        received_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    return document


class TestTheTimeline:
    def test_what_arrived_is_listed_newest_first(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        login(api, admin.email)
        _intake(db, org, sender="vechi@client.test", filename="vechi.pdf")
        _intake(db, org, sender="nou@client.test", filename="nou.pdf")

        body = api.get("/api/v1/intakes").json()

        assert body["total"] == 2
        moments = [item["receivedAt"] for item in body["items"]]
        assert moments == sorted(moments, reverse=True)

    def test_each_row_says_who_sent_it(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Rostul ecranului: „de la cine a venit asta și când"."""
        login(api, admin.email)
        _intake(db, org, sender="contabil@alfa.test", filename="factura.pdf")

        item = api.get("/api/v1/intakes").json()["items"][0]

        assert item["sender"] == "contabil@alfa.test"
        assert item["source"] == "EMAIL"

    def test_the_client_comes_from_the_document(
        self, api: TestClient, db: Session, org: Organization, admin: User, clients: list[Client]
    ) -> None:
        """La momentul recepției încă nu se știe al cui este; pe document se știe."""
        login(api, admin.email)
        document = _document(db, org, clients[0])
        _intake(db, org, sender="cineva@test.ro", filename="a.pdf", document=document)

        item = api.get("/api/v1/intakes").json()["items"][0]

        assert item["clientId"] == str(clients[0].id)
        assert item["clientName"] == clients[0].name

    def test_a_rejected_intake_says_why(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Altfel un atașament care nu a devenit document dispare fără urmă."""
        login(api, admin.email)
        _intake(
            db,
            org,
            sender="cineva@test.ro",
            filename="semnatura.png",
            status=IntakeStatus.REJECTED,
            rejection="Tip de fișier neacceptat.",
        )

        item = api.get("/api/v1/intakes").json()["items"][0]

        assert item["status"] == "REJECTED"
        assert item["rejectionReason"] == "Tip de fișier neacceptat."
        assert item["documentId"] is None

    def test_filtering_by_source(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        login(api, admin.email)
        _intake(db, org, sender="a@test.ro", filename="a.pdf", source=DocumentSource.EMAIL)
        _intake(db, org, sender="/Clienti/Alfa", filename="b.pdf", source=DocumentSource.ONEDRIVE)

        body = api.get("/api/v1/intakes", params={"source": "ONEDRIVE"}).json()

        assert body["total"] == 1
        assert body["items"][0]["source"] == "ONEDRIVE"


class TestWhatMustNotLeak:
    def test_the_raw_payload_never_leaves(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Poartă căi de stocare și identificatori interni ai furnizorului (§73)."""
        login(api, admin.email)
        _intake(db, org, sender="cineva@test.ro", filename="a.pdf")

        body = api.get("/api/v1/intakes").text

        assert SECRET_PATH not in body
        assert "rawPayload" not in body
        assert "drivePath" not in body

    def test_another_office_sees_nothing(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        login(api, make_user(db, org, roles, email="al.nostru@test.ro", role=RoleCode.ADMIN).email)
        _intake(db, org, sender="cineva@test.ro", filename="a.pdf")
        api.post("/api/v1/auth/logout")

        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival3.test", role=RoleCode.ADMIN)
        login(api, stranger.email)

        assert api.get("/api/v1/intakes").json()["total"] == 0

    def test_a_client_from_another_office_is_not_found(
        self, api: TestClient, db: Session, roles: dict[RoleCode, Role], clients: list[Client]
    ) -> None:
        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()
        stranger = make_user(db, other, roles, email="admin@rival4.test", role=RoleCode.ADMIN)
        login(api, stranger.email)

        assert api.get(f"/api/v1/clients/{clients[0].id}/intakes").status_code == 404

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        assert api.get("/api/v1/intakes").status_code == 401


class TestPerClient:
    def test_only_that_client_arrivals(
        self, api: TestClient, db: Session, org: Organization, admin: User, clients: list[Client]
    ) -> None:
        login(api, admin.email)
        mine = _document(db, org, clients[0])
        theirs = _document(db, org, clients[1])
        _intake(db, org, sender="a@test.ro", filename="al-meu.pdf", document=mine)
        _intake(db, org, sender="b@test.ro", filename="al-lui.pdf", document=theirs)

        body = api.get(f"/api/v1/clients/{clients[0].id}/intakes").json()

        assert body["total"] == 1
        assert body["items"][0]["originalFilename"] == "al-meu.pdf"

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [(RoleCode.ADMIN, True), (RoleCode.OPERATOR, True), (RoleCode.VIEWER, True)],
    )
    def test_anyone_who_sees_documents_sees_where_they_came_from(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, Role],
        role: RoleCode,
        allowed: bool,
    ) -> None:
        user = make_user(
            db, org, roles, email=f"intake-{role.value.lower()}@contacrm.test", role=role
        )
        login(api, user.email)

        assert (api.get("/api/v1/intakes").status_code == 200) is allowed
