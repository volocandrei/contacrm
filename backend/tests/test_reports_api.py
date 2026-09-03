"""Rapoartele (§84).

Testul care justifică existența acestui endpoint este
`test_nothing_is_left_out_above_the_page_limit`: până acum agregarea se făcea în
browser, peste primele 200 de documente, iar rezultatul era afișat ca și cum ar fi
acoperit tot. Pe setul de development ieșea corect, pentru că sunt mai puține de
200 — exact motivul pentru care greșeala nu se vedea.

Restul verifică ce se întâmplă la margini: ce se numără când lipsește ceva (lună,
client, tip) și ce se răspunde când nu s-a terminat încă nimic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services.report_service import TOP_CLIENTS
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
MONTH = "2026-08"
URL = "/api/v1/reports/summary"


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


@pytest.fixture
def other_org(db: Session) -> Organization:
    row = Organization(name="Alt Cabinet SRL")
    db.add(row)
    db.flush()
    return row


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


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1")
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


@pytest.fixture
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    """Sesiune de administrator pe clientul de test."""
    login(api, admin.email)
    return api


def add_document(
    db: Session,
    org: Organization,
    *,
    client: Client | None = None,
    document_type: DocumentType | None = None,
    reference_month: str | None = MONTH,
    status: DocumentStatus = DocumentStatus.APPROVED,
    is_duplicate: bool = False,
) -> Document:
    document_id = uuid.uuid4()
    prefix = f"organizations/{org.id}/documents/{document_id}"
    document = Document(
        id=document_id,
        organization_id=org.id,
        client_id=client.id if client else None,
        document_type_id=document_type.id if document_type else None,
        status=status,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=f"{prefix}/original/source.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        reference_month=reference_month,
        is_duplicate=is_duplicate,
    )
    if status is DocumentStatus.ARCHIVED:
        # Schema refuza un document arhivat fara nume standardizat si fara copie
        # (`ck_documents_archived_has_filename`). Testul respecta invariantul in
        # loc sa-l ocoleasca: un ARCHIVED inventat, incomplet, ar testa o stare
        # care nu poate exista in realitate.
        document.archived_at = datetime.now(UTC)
        document.stored_filename = "2026-08-14_Facturaintrare_AlfaConta_FCT1.pdf"
        document.archive_key = f"{prefix}/archive/document.pdf"
        document.archive_path = "/ARHIVA/2026/08/Alfa Conta SRL"
    db.add(document)
    db.flush()
    return document


def fetch(api: TestClient, **params: str) -> dict[str, Any]:
    response = api.get(URL, params=params)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def counts(buckets: list[dict[str, Any]]) -> dict[str | None, int]:
    return {bucket["key"]: bucket["count"] for bucket in buckets}


@pytest.mark.usefixtures("as_admin")
class TestCoverage:
    def test_nothing_is_left_out_above_the_page_limit(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Motivul pentru care raportul s-a mutat în backend.

        Interfața cerea primele 200 de documente și le număra acolo. Cu 250, un
        sfert din realitate lipsea din procentul afișat — fără niciun semn că
        lipsește.
        """
        for _ in range(250):
            add_document(db, org, client=client_row)

        assert fetch(api, **{})["total"] == 250

    def test_a_second_organization_is_invisible(
        self, api: TestClient, db: Session, org: Organization, other_org: Organization
    ) -> None:
        """§72 — agregarea nu are voie să vadă peste graniță."""
        add_document(db, org)
        for _ in range(5):
            add_document(db, other_org)

        assert fetch(api, **{})["total"] == 1


@pytest.mark.usefixtures("as_admin")
class TestSuccessRate:
    def test_unfinished_work_is_not_a_failure(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Nimic terminat înseamnă `null`, nu zero.

        Zero s-ar citi ca „totul a eșuat", ceea ce este altceva — și exact opusul
        adevărului când sistemul tocmai a primit primele fișiere.
        """
        add_document(db, org, status=DocumentStatus.RECEIVED)
        add_document(db, org, status=DocumentStatus.PROCESSING)

        payload = fetch(api, **{})
        assert payload["successRate"] is None
        assert payload["processed"] == 0
        assert payload["total"] == 2

    def test_documents_still_in_progress_do_not_lower_the_rate(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cineva care tocmai a încărcat un fișier nu strică statistica nimănui."""
        add_document(db, org, status=DocumentStatus.APPROVED)
        add_document(db, org, status=DocumentStatus.ARCHIVED)
        add_document(db, org, status=DocumentStatus.PROCESSING)

        payload = fetch(api, **{})
        assert payload["processed"] == 2
        assert payload["successRate"] == 1.0

    def test_errors_are_what_lowers_the_rate(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        for _ in range(3):
            add_document(db, org, status=DocumentStatus.APPROVED)
        add_document(db, org, status=DocumentStatus.ERROR)

        payload = fetch(api, **{})
        assert payload["failed"] == 1
        assert payload["successRate"] == 0.75


@pytest.mark.usefixtures("as_admin")
class TestWhatIsMissing:
    """Ce lipsește se numără; nu se sare peste."""

    def test_documents_without_a_month_get_their_own_bucket(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Un document fără lună contabilă este exact ce trebuie să vadă cineva."""
        add_document(db, org, reference_month=MONTH)
        add_document(db, org, reference_month=None)

        by_month = counts(fetch(api, **{})["byMonth"])
        assert by_month == {MONTH: 1, None: 1}

    def test_the_undated_bucket_comes_last(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Luna recentă prima, fără lună la coadă — ordinea cronologică rămâne."""
        add_document(db, org, reference_month="2026-06")
        add_document(db, org, reference_month=None)
        add_document(db, org, reference_month="2026-08")

        keys = [bucket["key"] for bucket in fetch(api, **{})["byMonth"]]
        assert keys == ["2026-08", "2026-06", None]

    def test_documents_without_a_client_get_their_own_bucket(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)
        add_document(db, org, client=None)

        by_client = counts(fetch(api, **{})["byClient"])
        assert by_client == {str(client_row.id): 1, None: 1}

    def test_the_absent_bucket_carries_no_label(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cum se scrie „client neidentificat" este treaba interfeței.

        Dacă serverul ar trimite și el formularea, ar exista două surse pentru
        același text și s-ar despărți la prima modificare.
        """
        add_document(db, org, client=None, document_type=None)

        payload = fetch(api, **{})
        assert payload["byClient"][0]["label"] is None
        assert payload["byType"][0]["label"] is None

    def test_statuses_carry_no_label_either(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """`status-badge.tsx` le traduce de mult; nu le traducem a doua oară."""
        add_document(db, org, status=DocumentStatus.APPROVED)

        bucket = fetch(api, **{})["byStatus"][0]
        assert bucket["key"] == DocumentStatus.APPROVED.value
        assert bucket["label"] is None

    def test_the_type_label_comes_from_the_database(
        self, api: TestClient, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Asta serverul chiar o știe — tipurile sunt administrabile (§6)."""
        add_document(db, org, document_type=types["FACTURA_INTRARE"])

        bucket = fetch(api, **{})["byType"][0]
        assert bucket["key"] == "FACTURA_INTRARE"
        assert bucket["label"] == types["FACTURA_INTRARE"].label


@pytest.mark.usefixtures("as_admin")
class TestFilters:
    def test_the_month_range_includes_both_ends(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        for month in ("2026-05", "2026-06", "2026-07", "2026-08"):
            add_document(db, org, reference_month=month)

        payload = fetch(api, fromMonth="2026-06", toMonth="2026-07")
        assert payload["total"] == 2
        assert counts(payload["byMonth"]) == {"2026-07": 1, "2026-06": 1}

    def test_a_month_range_excludes_documents_without_a_month(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Nu se poate spune despre un document fără lună că este într-un interval."""
        add_document(db, org, reference_month=MONTH)
        add_document(db, org, reference_month=None)

        assert fetch(api, fromMonth=MONTH, toMonth=MONTH)["total"] == 1

    def test_filtering_by_client(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)
        add_document(db, org, client=None)

        assert fetch(api, clientId=str(client_row.id))["total"] == 1

    def test_a_reversed_range_is_refused(self, api: TestClient) -> None:
        """Tăcut, ar întoarce zero — care se citește „nu aveți documente"."""
        response = api.get(URL, params={"fromMonth": "2026-08", "toMonth": "2026-06"})
        assert response.status_code == 422
        assert "fromMonth" in response.json()["details"]

    def test_a_malformed_month_is_refused(self, api: TestClient) -> None:
        assert api.get(URL, params={"fromMonth": "august"}).status_code == 422
        assert api.get(URL, params={"fromMonth": "2026-13"}).status_code == 422

    def test_the_filters_are_read_as_camel_case(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Trimise snake_case ar fi ignorate tăcut, iar raportul ar răspunde la
        altă întrebare decât cea pusă."""
        add_document(db, org, reference_month="2026-05")
        add_document(db, org, reference_month="2026-08")

        assert fetch(api, fromMonth="2026-08")["total"] == 1


@pytest.mark.usefixtures("as_admin")
class TestRanking:
    def test_the_client_ranking_is_capped_but_says_so(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Lista este scurtă; numărul real de clienți nu este ascuns."""
        for index in range(TOP_CLIENTS + 5):
            client = Client(organization_id=org.id, name=f"Client {index:02d}")
            db.add(client)
            db.flush()
            for _ in range(index + 1):
                add_document(db, org, client=client)

        payload = fetch(api, **{})
        assert len(payload["byClient"]) == TOP_CLIENTS
        assert payload["clientCount"] == TOP_CLIENTS + 5

    def test_the_ranking_is_ordered_by_count(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        few = Client(organization_id=org.id, name="Puține")
        many = Client(organization_id=org.id, name="Multe")
        db.add_all([few, many])
        db.flush()

        add_document(db, org, client=few)
        for _ in range(3):
            add_document(db, org, client=many)

        assert [b["label"] for b in fetch(api, **{})["byClient"]] == ["Multe", "Puține"]


class TestEmptiness:
    def test_no_documents_is_a_valid_report(self, as_admin: TestClient) -> None:
        """Un cabinet nou nu primește o eroare, ci un raport gol și onest."""
        api = as_admin

        payload = fetch(api, **{})
        assert payload["total"] == 0
        assert payload["successRate"] is None
        assert payload["byMonth"] == []
        assert payload["clientCount"] == 0


class TestAuthorization:
    def test_anonymous_gets_nothing(self, api: TestClient) -> None:
        assert api.get(URL).status_code == 401

    def test_a_viewer_may_count_what_it_may_read(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un raport este o numărătoare peste documente; permisiunea este aceeași."""
        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        login(api, viewer.email)

        assert api.get(URL).status_code == 200
