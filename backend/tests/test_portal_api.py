"""Portalul clientului — singura rută publică prin care se poate scrie (M14).

Restul aplicației cere o sesiune. Aici nu, deci fiecare test de mai jos apără o
graniță care în altă parte este apărată de autentificare.

**În ordinea gravității:**

1. **Nu se citește nimic prin link.** Cine îl are poate doar să adauge. Dacă s-ar
   putea citi, un link scurs ar deveni o scurgere de date, nu doar un drum
   nedorit.
2. **Nu se află nimic despre client.** Pagina spune numele cabinetului, nu al
   clientului: un link ajuns din greșeală la altcineva n-are voie să spună cine
   este clientul cabinetului.
3. **Un link mort este mort.** Expirat, revocat, sau al unui client șters — toate
   întorc același 404, fără să spună care dintre ele.
4. **Documentul ajunge la clientul potrivit**, fără ghicit. Este rostul întreg.
5. **Fișierele proaste sunt refuzate** ca peste tot: tipul se ia din octeți.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.document import Document
from app.models.organization import Organization
from app.models.upload_link import ClientUploadLink
from app.models.user import User
from app.services.upload_links import UploadLinkService
from tests.conftest import requires_db
from tests.test_crm_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"


@pytest.fixture
def api_storage(api: TestClient, tmp_path: Path) -> TestClient:
    """API cu storage izolat, ca testele să nu scrie în `./storage`."""
    from app.api.deps import get_storage
    from app.services.storage import LocalStorageProvider

    provider = LocalStorageProvider(tmp_path / "storage")
    api.app.dependency_overrides[get_storage] = lambda: provider  # type: ignore[attr-defined]
    return api


def issue(db: Session, org: Organization, client: Client, admin: User) -> str:
    token = UploadLinkService(db).issue(org.id, client.id, created_by_id=admin.id).token
    db.commit()
    return token


def send(api: TestClient, token: str, *, name: str = "factura.pdf", body: bytes = PDF):
    return api.post(
        f"/api/v1/portal/{token}",
        files={"file": (name, body, "application/pdf")},
    )


class TestWhatTheLinkCanDo:
    def test_a_client_can_send_without_an_account(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Rostul întreg: fără cont, fără parolă, fără aplicație de instalat."""
        token = issue(db, org, clients[0], admin)

        response = send(api_storage, token)

        assert response.status_code == 201, response.text
        assert response.json()["accepted"] is True

    def test_the_document_lands_on_the_right_client(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Apartenența vine din link, nu din ghicit: nu trece prin `UNMATCHED`."""
        token = issue(db, org, clients[0], admin)

        send(api_storage, token, name="extras.pdf")

        document = db.scalars(
            select(Document).where(Document.original_filename == "extras.pdf")
        ).one()
        assert document.client_id == clients[0].id
        assert document.source.value == "PORTAL"
        assert document.status.value != "UNMATCHED"

    def test_the_page_says_who_you_are_sending_to(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        token = issue(db, org, clients[0], admin)

        body = api_storage.get(f"/api/v1/portal/{token}").json()

        assert body["organizationName"] == org.name
        assert body["maxFileSizeMb"] > 0
        assert body["acceptedTypes"]

    def test_sending_the_same_file_twice_is_not_an_error(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Un client care nu e sigur dacă a trimis retrimite. Nu trebuie speriat."""
        token = issue(db, org, clients[0], admin)
        send(api_storage, token, name="acelasi.pdf")

        again = send(api_storage, token, name="acelasi.pdf")

        assert again.status_code == 201
        assert "deja" in again.json()["message"]


class TestWhatTheLinkCannotDo:
    def test_the_client_name_never_leaves(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Cel mai important test de aici.

        Un link ajuns din greșeală la altcineva — retrimis, uitat într-un email —
        n-are voie să spună cine este clientul cabinetului.
        """
        token = issue(db, org, clients[0], admin)

        info = api_storage.get(f"/api/v1/portal/{token}").text
        upload = send(api_storage, token).text

        assert clients[0].name not in info
        assert clients[0].name not in upload
        assert str(clients[0].id) not in info
        assert str(clients[0].id) not in upload

    def test_nothing_can_be_read_through_it(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Nu listează, nu descarcă, nu spune ce s-a trimis deja."""
        token = issue(db, org, clients[0], admin)
        send(api_storage, token, name="secret.pdf")

        # Singurul `GET` care există spune doar cui trimiți și ce se acceptă.
        body = api_storage.get(f"/api/v1/portal/{token}").json()

        assert set(body) == {"organizationName", "maxFileSizeMb", "acceptedTypes"}
        # Și nu există nicio altă cale sub prefixul portalului.
        assert api_storage.get(f"/api/v1/portal/{token}/documents").status_code == 404

    def test_the_upload_response_hides_internals(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Nici id-uri, nici căi de stocare (§73): nu are cine să le folosească."""
        token = issue(db, org, clients[0], admin)

        body = api_storage.post(
            f"/api/v1/portal/{token}", files={"file": ("f.pdf", PDF, "application/pdf")}
        ).json()

        assert set(body) == {"filename", "accepted", "message"}

    @pytest.mark.parametrize(
        "broken",
        ["", "nu-exista", "x" * 43],
    )
    def test_a_wrong_token_says_nothing(self, api_storage: TestClient, broken: str) -> None:
        response = api_storage.get(f"/api/v1/portal/{broken}")
        assert response.status_code == 404

    def test_an_expired_link_is_dead(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        token = issue(db, org, clients[0], admin)
        link = db.scalars(select(ClientUploadLink)).one()
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        assert api_storage.get(f"/api/v1/portal/{token}").status_code == 404
        assert send(api_storage, token).status_code == 404

    def test_a_revoked_link_is_dead(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        token = issue(db, org, clients[0], admin)
        UploadLinkService(db).revoke(org.id, db.scalars(select(ClientUploadLink)).one().id)
        db.commit()

        assert send(api_storage, token).status_code == 404

    def test_a_link_of_a_deleted_client_is_dead(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        token = issue(db, org, clients[0], admin)
        clients[0].deleted_at = datetime.now(UTC)
        db.commit()

        assert send(api_storage, token).status_code == 404

    def test_a_file_that_is_not_what_it_claims_is_refused(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Tipul se ia din octeți, nu din ce declară clientul (§50)."""
        token = issue(db, org, clients[0], admin)

        response = api_storage.post(
            f"/api/v1/portal/{token}",
            files={"file": ("virus.pdf", b"MZ\x90\x00 executabil", "application/pdf")},
        )

        assert response.status_code == 422


class TestTheTrace:
    def test_an_upload_through_the_portal_leaves_a_trace(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Autorul este linkul, nu un utilizator: nimeni nu s-a autentificat."""
        from app.models.audit import AuditLog

        token = issue(db, org, clients[0], admin)
        send(api_storage, token, name="cu-urma.pdf")

        entry = db.scalars(
            select(AuditLog)
            .where(AuditLog.action == "DOCUMENT_UPLOADED")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        assert entry.user_id is None
        assert entry.user_name == "portal client"

    def test_the_link_counts_what_came_through_it(
        self,
        api_storage: TestClient,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
    ) -> None:
        """Contorul spune dacă drumul chiar este folosit sau a rămas o intenție."""
        token = issue(db, org, clients[0], admin)

        send(api_storage, token, name="unu.pdf")
        send(api_storage, token, name="doi.pdf")
        db.expire_all()

        link = db.scalars(select(ClientUploadLink)).one()
        assert link.upload_count == 2
        assert link.last_used_at is not None


class TestIssuing:
    def test_the_token_is_never_stored(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """În bază stă doar hash-ul: o bază citită de altcineva nu dă linkuri."""
        issued = UploadLinkService(db).issue(org.id, clients[0].id, created_by_id=admin.id)
        db.commit()

        link = db.scalars(select(ClientUploadLink)).one()
        assert link.token_hash != issued.token
        assert issued.token not in str(link.token_hash)

    def test_a_link_cannot_outlive_the_maximum(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """Un „link permanent" este exact ce nu vrem."""
        issued = UploadLinkService(db).issue(
            org.id, clients[0].id, created_by_id=admin.id, validity=timedelta(days=3650)
        )

        assert issued.expires_at < datetime.now(UTC) + timedelta(days=181)

    def test_another_office_cannot_revoke_it(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        UploadLinkService(db).issue(org.id, clients[0].id, created_by_id=admin.id)
        db.flush()
        link = db.scalars(select(ClientUploadLink)).one()

        assert UploadLinkService(db).revoke(uuid.uuid4(), link.id) is None


class TestPermissions:
    def test_issuing_needs_a_session(self, api: TestClient, clients: list[Client]) -> None:
        """Deschiderea unui drum public este o decizie a cabinetului, nu a oricui."""
        response = api.post(f"/api/v1/clients/{clients[0].id}/upload-links")
        assert response.status_code == 401

    def test_a_reader_cannot_open_a_way_in(
        self, api: TestClient, db: Session, org: Organization, roles: dict, clients: list[Client]
    ) -> None:
        """Cine doar citește nu deschide o cale publică de scriere."""
        from app.domain.permissions import RoleCode
        from tests.test_crm_api import make_user

        viewer = make_user(db, org, roles, email="nu-deschide@contacrm.test", role=RoleCode.VIEWER)
        db.commit()
        login(api, viewer.email)

        response = api.post(f"/api/v1/clients/{clients[0].id}/upload-links")

        assert response.status_code == 403

    def test_the_accountant_who_chases_documents_can(
        self, api: TestClient, db: Session, org: Organization, roles: dict, clients: list[Client]
    ) -> None:
        """Gardul este `documents:write`, și asta a fost o corectură, nu o scăpare.

        La început am cerut `clients:write`, pe raționamentul că o cale publică de
        scriere este o decizie a cabinetului. În matricea de roluri, `clients:write`
        îl are numai administratorul — iar cel care aleargă după documente este
        contabilul. Cu gardul acela, tocmai omul pentru care s-a făcut funcția nu o
        putea folosi.
        """
        from app.domain.permissions import RoleCode
        from tests.test_crm_api import make_user

        accountant = make_user(
            db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT
        )
        db.commit()
        login(api, accountant.email)

        response = api.post(f"/api/v1/clients/{clients[0].id}/upload-links")

        assert response.status_code == 201, response.text
