"""Cifrele cu care se deschide ziua (§20).

Panoul numără, de la M5, ce **s-a întâmplat**: documente sosite, în procesare, cu
erori. Nu spunea nimic despre ce mai are cabinetul de **făcut** — cine n-a fost
întrebat și cine a fost dar tace. Iar dimineața nu începe uitându-te la ce a
intrat, ci la ce mai ai de recuperat.

**În ordinea gravității:**

1. **Cine n-a fost întrebat** este cifra care schimbă ziua: oamenii aceia nu
   trimit din senin.
2. **Cine tace după ce a fost întrebat** este cea de-a doua: acolo nu mai ceri,
   ci suni.
3. **Cine a răspuns nu apare în niciuna.** Un panou care ar cere să insiști pe un
   client care tocmai a trimis ajunge să nu mai fie citit.
4. **Aceleași cifre ca ecranul „Documente lipsă"**, din aceeași sursă: două
   moduri de a le număra ar fi dat, într-o zi, două răspunsuri.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus, DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.user import User
from app.services.upload_links import UploadLinkService
from tests.conftest import requires_db
from tests.test_periods_api import MONTH, add_document, login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


@pytest.fixture
def gaps(
    db: Session,
    org: Organization,
    client_row: Client,
    types: dict[str, DocumentType],
    expectations: dict[str, ClientExpectation],
) -> None:
    """O lună începută și neterminată, pe un client activ.

    Un document a sosit — deci luna există; restul lipsește — deci mai e de
    cerut. Clientul este activ, altfel raportul îl lasă deoparte pe bună dreptate.
    """
    client_row.status = ClientStatus.ACTIVE
    add_document(db, org, client_row, types["FACTURA_INTRARE"])
    db.commit()


def kpis(api: TestClient) -> dict[str, int]:
    response = api.get("/api/v1/dashboard")
    assert response.status_code == 200, response.text
    return dict(response.json()["kpis"])


def ask(api: TestClient, client_row: Client) -> str:
    """Cere documentele, ca din ecran, și întoarce tokenul din mesaj."""
    response = api.post(f"/api/v1/clients/{client_row.id}/document-request?referenceMonth={MONTH}")
    assert response.status_code == 200, response.text
    url = str(response.json()["uploadUrl"])
    return url.rsplit("/", 1)[-1]


class TestWhatIsLeftToDo:
    def test_a_client_nobody_asked_is_counted(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        login(api_storage, admin.email)

        assert kpis(api_storage)["clientsNotAsked"] == 1
        assert kpis(api_storage)["clientsAwaitingReply"] == 0

    def test_after_asking_the_client_moves_to_waiting(
        self, api_storage: TestClient, admin: User, client_row: Client, gaps: None
    ) -> None:
        """Nu mai e de cerut, e de așteptat. Două acțiuni diferite."""
        login(api_storage, admin.email)
        ask(api_storage, client_row)

        after = kpis(api_storage)
        assert after["clientsNotAsked"] == 0
        assert after["clientsAwaitingReply"] == 1

    def test_a_client_who_answered_is_in_neither(
        self,
        api_storage: TestClient,
        db: Session,
        admin: User,
        client_row: Client,
        gaps: None,
    ) -> None:
        """Un panou care cere să insiști pe cine tocmai a trimis nu mai e citit."""
        login(api_storage, admin.email)
        token = ask(api_storage, client_row)
        sent = api_storage.post(
            f"/api/v1/portal/{token}",
            files={
                "file": ("raspuns.pdf", b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF", "application/pdf")
            },
        )
        assert sent.status_code == 201, sent.text

        after = kpis(api_storage)
        assert after["clientsNotAsked"] == 0
        assert after["clientsAwaitingReply"] == 0

    def test_a_client_with_nothing_missing_is_not_chased(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
        types: dict[str, DocumentType],
        gaps: None,
    ) -> None:
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        add_document(db, org, client_row, types["EXTRAS_CONT"])
        db.commit()
        login(api_storage, admin.email)

        after = kpis(api_storage)
        assert after["clientsNotAsked"] == 0
        assert after["clientsAwaitingReply"] == 0


class TestWhenThereIsNoMonth:
    def test_an_empty_office_asks_nothing_of_anyone(
        self, api_storage: TestClient, db: Session, admin: User
    ) -> None:
        """Fără nicio lună în lucru nu se inventează muncă."""
        db.commit()
        login(api_storage, admin.email)

        after = kpis(api_storage)
        assert after["clientsNotAsked"] == 0
        assert after["clientsAwaitingReply"] == 0


def test_the_numbers_agree_with_the_missing_documents_screen(
    api_storage: TestClient, db: Session, org: Organization, admin: User, gaps: None
) -> None:
    """Aceeași sursă, aceleași cifre.

    Două moduri de a număra „cine n-a fost întrebat" ar fi dat, într-o zi, două
    răspunsuri — iar cel de pe panou ar fi fost cel crezut.
    """
    second = Client(
        organization_id=org.id, name="Beta Tăcut SRL", tax_id="RO7", status=ClientStatus.ACTIVE
    )
    db.add(second)
    db.flush()
    for code, minimum in (("FACTURA_INTRARE", 2), ("EXTRAS_CONT", 1)):
        db.add(
            ClientExpectation(
                organization_id=org.id,
                client_id=second.id,
                document_type_id=db.query(DocumentType).filter_by(code=code).one().id,
                expected_min_count=minimum,
            )
        )
    db.add(
        Document(
            organization_id=org.id,
            client_id=second.id,
            status=DocumentStatus.REVIEW_REQUIRED,
            source=DocumentSource.UPLOAD,
            original_filename="ceva.pdf",
            storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=512,
            sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            received_at=datetime.now(UTC),
            reference_month=MONTH,
        )
    )
    db.commit()
    login(api_storage, admin.email)

    report = api_storage.get(f"/api/v1/periods/missing?referenceMonth={MONTH}").json()
    never = sum(1 for row in report if row["requestedAt"] is None)

    assert kpis(api_storage)["clientsNotAsked"] == never
    assert never == 2


def test_a_revoked_link_still_counts_as_asked(
    api_storage: TestClient,
    db: Session,
    org: Organization,
    admin: User,
    client_row: Client,
    gaps: None,
) -> None:
    """O cerere trimisă s-a trimis.

    Faptul că i-am închis între timp drumul nu înseamnă că n-am întrebat — iar
    dacă ar reveni la „necerut", cabinetul ar cere a doua oară aceluiași om.
    """
    login(api_storage, admin.email)
    ask(api_storage, client_row)
    link = UploadLinkService(db).for_client(org.id, client_row.id)[0]
    assert (
        api_storage.delete(f"/api/v1/clients/{client_row.id}/upload-links/{link.id}").status_code
        == 204
    )

    after = kpis(api_storage)
    assert after["clientsNotAsked"] == 0
    assert after["clientsAwaitingReply"] == 1
