"""Starea cozii de procesare, ca ecran (§7, §36).

**Ce lipsea.** „De ce nu s-a procesat documentul urcat acum douăzeci de minute?"
nu avea unde să primească un răspuns. Documentul stătea în `RECEIVED`, ecranul nu
arăta nicio eroare — fiindcă nu era niciuna — iar singurul semn că workerul
murise era o coadă care creștea și pe care nu o vedea nimeni. Se descoperea a
doua zi, la o sută de documente neprocesate.

**Cifra care contează** nu este câte cereri sunt în coadă, ci de când așteaptă
cea mai veche. Treizeci de cereri într-o dimineață aglomerată sunt normale și se
golesc singure; una singură care așteaptă de patruzeci de minute nu are nicio
explicație bună. Testul care apără asta este
`test_the_wait_is_measured_from_the_oldest_not_the_newest`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentProcessingJob
from app.models.organization import Organization
from app.models.user import User
from app.services.processing_health import FAILURE_WINDOW, RECENT_FAILURES
from tests.conftest import requires_db
from tests.test_documents_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_documents_api",)

URL = "/api/v1/documents/processing/health"


def a_document(
    db: Session,
    org: Organization,
    *,
    client: Client | None = None,
    filename: str = "factura.pdf",
) -> Document:
    row = Document(
        organization_id=org.id,
        client_id=client.id if client is not None else None,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.UPLOAD,
        original_filename=filename,
        storage_key=f"k/{uuid.uuid4()}",
        mime_type="application/pdf",
        file_size=1024,
        sha256_hash=uuid.uuid4().hex.ljust(64, "0"),
        received_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def a_job(
    db: Session,
    document: Document,
    *,
    status: str,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    attempt: int = 1,
) -> DocumentProcessingJob:
    row = DocumentProcessingJob(
        document_id=document.id,
        job_type="EXTRACTION",
        status=status,
        attempt=attempt,
        idempotency_key=f"{document.id}:{attempt}:{uuid.uuid4().hex[:8]}",
        error_code=error_code,
        error_detail=error_detail,
        started_at=started_at,
        finished_at=finished_at,
    )
    db.add(row)
    db.flush()
    if created_at is not None:
        # `created_at` are `server_default`; se rescrie după inserare, ca testul
        # să poată vorbi despre o cerere veche fără să aștepte.
        row.created_at = created_at
        db.flush()
    return row


@pytest.fixture
def other_org(db: Session) -> Organization:
    """Alt cabinet, cu coada lui."""
    row = Organization(name="Alt Cabinet SRL", tax_id="RO303030")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    login(api, admin.email)
    return api


def health(api: TestClient) -> dict[str, object]:
    answer = api.get(URL)
    assert answer.status_code == 200, answer.text
    result: dict[str, object] = answer.json()
    return result


class TestTheNumbers:
    def test_an_empty_queue_says_so_without_a_wait(self, as_admin: TestClient) -> None:
        answer = health(as_admin)

        assert answer["queued"] == 0
        assert answer["waitingSeconds"] is None

    def test_a_queued_request_is_counted(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        a_job(db, a_document(db, org), status="PENDING")

        assert health(as_admin)["queued"] == 1

    def test_the_wait_is_measured_from_the_oldest_not_the_newest(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Testul pentru care există ecranul.

        Măsurată de la cea mai nouă, așteptarea ar fi rămas mereu mică: fiecare
        document urcat ar fi „resetat" cifra, iar o coadă blocată de o oră ar fi
        arătat sănătoasă atâta timp cât mai intra ceva în ea.
        """
        a_job(db, a_document(db, org), status="PENDING", created_at=datetime.now(UTC))
        a_job(
            db,
            a_document(db, org),
            status="PENDING",
            created_at=datetime.now(UTC) - timedelta(minutes=40),
        )

        waiting = health(as_admin)["waitingSeconds"]

        assert isinstance(waiting, int)
        assert waiting >= 40 * 60

    def test_a_request_that_started_a_second_ago_is_not_stuck(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Un job pornit acum lucrează. Numărat ca blocat, ar alarma degeaba."""
        a_job(db, a_document(db, org), status="RUNNING", started_at=datetime.now(UTC))

        answer = health(as_admin)

        assert answer["running"] == 1
        assert answer["stuck"] == 0

    def test_a_request_running_for_too_long_is_stuck(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Procesul care o ținea a murit; `recover-processing` o readuce în coadă."""
        a_job(
            db,
            a_document(db, org),
            status="RUNNING",
            started_at=datetime.now(UTC) - timedelta(hours=6),
        )

        assert health(as_admin)["stuck"] == 1

    def test_a_finished_request_counts_as_nothing(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Contra-proba: fără ea, orice cifră ar putea număra tot tabelul."""
        a_job(
            db,
            a_document(db, org),
            status="SUCCEEDED",
            finished_at=datetime.now(UTC),
        )

        answer = health(as_admin)

        assert (answer["queued"], answer["running"], answer["failedRecently"]) == (0, 0, 0)


class TestTheFailures:
    def test_a_failure_is_listed_with_the_filename_and_the_reason(
        self, as_admin: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Cine deschide ecranul caută „factura de la Alfa", nu un identificator."""
        document = a_document(db, org, client=client_row, filename="factura-alfa.pdf")
        a_job(
            db,
            document,
            status="FAILED",
            finished_at=datetime.now(UTC),
            error_code="EXTRACTION_FAILED",
            error_detail="Fișierul nu conține text și nu s-a putut citi.",
        )

        rows = health(as_admin)["recentFailures"]

        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["originalFilename"] == "factura-alfa.pdf"
        assert rows[0]["clientName"] == client_row.name
        assert rows[0]["errorCode"] == "EXTRACTION_FAILED"
        assert "nu conține text" in str(rows[0]["errorDetail"])

    def test_an_old_failure_does_not_crowd_out_todays(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Un eșec de acum o săptămână a fost deja văzut sau deja nu mai contează."""
        a_job(
            db,
            a_document(db, org),
            status="FAILED",
            finished_at=datetime.now(UTC) - FAILURE_WINDOW - timedelta(hours=1),
            error_code="EXTRACTION_FAILED",
        )

        answer = health(as_admin)

        assert answer["failedRecently"] == 0
        assert answer["recentFailures"] == []

    def test_the_list_stops_at_a_readable_length(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """Ecranul răspunde la „ce s-a stricat acum", nu ține loc de jurnal."""
        for index in range(RECENT_FAILURES + 5):
            a_job(
                db,
                a_document(db, org, filename=f"f{index}.pdf"),
                status="FAILED",
                finished_at=datetime.now(UTC),
                error_code="EXTRACTION_FAILED",
            )

        answer = health(as_admin)

        assert answer["failedRecently"] == RECENT_FAILURES + 5
        assert len(answer["recentFailures"]) == RECENT_FAILURES  # type: ignore[arg-type]

    def test_no_traceback_ever_reaches_the_screen(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        """§53: pe un ecran de cabinet, un traceback nu se citește — și uneori
        spune mai mult decât are voie."""
        a_job(
            db,
            a_document(db, org),
            status="FAILED",
            finished_at=datetime.now(UTC),
            error_code="EXTRACTION_FAILED",
            error_detail="Fișierul nu conține text.",
        )

        assert "Traceback" not in str(health(as_admin)["recentFailures"])


class TestIsolation:
    def test_another_offices_queue_is_not_visible(
        self, as_admin: TestClient, db: Session, other_org: Organization
    ) -> None:
        """Fiecare cifră se numără prin documentul cererii, nu pe tabelul de joburi.

        Tabelul acela nu are organizație — o cerere aparține unui document, iar
        documentul unui cabinet. Numărate direct, cifrele ar fi fost ale întregii
        instalări, iar un cabinet ar fi văzut coada altuia.
        """
        a_job(db, a_document(db, other_org), status="PENDING")
        a_job(
            db,
            a_document(db, other_org),
            status="FAILED",
            finished_at=datetime.now(UTC),
            error_code="EXTRACTION_FAILED",
        )

        answer = health(as_admin)

        assert answer["queued"] == 0
        assert answer["failedRecently"] == 0
        assert answer["recentFailures"] == []

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        api.post("/api/v1/auth/logout")

        assert api.get(URL).status_code == 401
