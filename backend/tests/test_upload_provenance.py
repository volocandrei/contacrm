"""Pe ce drum a ajuns documentul la cabinet, când îl încarcă un om (§6, §25).

**Cazul real.** Clientul trimite pozele bonurilor pe WhatsApp. Contabilul le
descarcă de pe telefon și le încarcă în fișa clientului. Până acum, toate ajungeau
în evidență ca „încărcat manual" — adevărat despre ultimul pas, tăcut despre
primul. Cronologia clientului spunea „a încărcat cineva un fișier" acolo unde
răspunsul la „de ce nu am primit bonurile?" era „le-ați trimis pe WhatsApp".

**Ce nu se poate declara, și de ce contează mai mult.** Celelalte proveniențe sunt
constatări ale sistemului: „a venit pe email" înseamnă că am citit-o dintr-o cutie
poștală, „din SPV" înseamnă că am descărcat-o de la ANAF. Dacă un om ar putea
scrie oricare dintre ele într-un formular, proveniența ar înceta să fie o
constatare și ar deveni o părere. La un control, diferența este tot ce contează.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource
from app.models.client import Client
from app.models.document import Document
from app.models.user import User
from tests.conftest import requires_db
from tests.test_documents_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_documents_api",)

URL = "/api/v1/documents/upload"

#: Un PDF sintetic, ca în restul testelor de încărcare. Niciun document real (§70).
PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"


def a_file() -> dict[str, tuple[str, io.BytesIO, str]]:
    """Nume unic: detecția de duplicate lucrează pe conținut, nu pe nume."""
    body = PDF + uuid.uuid4().bytes
    return {"file": (f"bon-{uuid.uuid4().hex[:8]}.pdf", io.BytesIO(body), "application/pdf")}


@pytest.fixture
def as_admin(api_storage: TestClient, admin: User) -> TestClient:
    login(api_storage, admin.email)
    return api_storage


def uploaded(db: Session, answer_json: dict[str, object]) -> Document:
    document = db.get(Document, uuid.UUID(str(answer_json["id"])))
    assert document is not None
    return document


class TestDeclaringWhereItCameFrom:
    def test_whatsapp_is_recorded_as_the_way_it_arrived(
        self, as_admin: TestClient, db: Session, client_row: Client
    ) -> None:
        """Motivul pentru care există câmpul."""
        answer = as_admin.post(
            URL, files=a_file(), data={"clientId": str(client_row.id), "source": "WHATSAPP"}
        )

        assert answer.status_code == 201, answer.text
        assert uploaded(db, answer.json()).source is DocumentSource.WHATSAPP

    def test_saying_nothing_still_means_a_plain_upload(
        self, as_admin: TestClient, db: Session
    ) -> None:
        """Contra-proba: fără câmp, comportamentul de dinainte rămâne neschimbat."""
        answer = as_admin.post(URL, files=a_file())

        assert answer.status_code == 201, answer.text
        assert uploaded(db, answer.json()).source is DocumentSource.UPLOAD

    def test_declaring_a_plain_upload_is_allowed_too(
        self, as_admin: TestClient, db: Session
    ) -> None:
        answer = as_admin.post(URL, files=a_file(), data={"source": "UPLOAD"})

        assert answer.status_code == 201, answer.text
        assert uploaded(db, answer.json()).source is DocumentSource.UPLOAD


class TestWhatCannotBeDeclared:
    @pytest.mark.parametrize("claimed", ["EMAIL", "EFACTURA", "ONEDRIVE", "API", "PORTAL"])
    def test_a_provenance_the_system_establishes_is_refused(
        self, as_admin: TestClient, db: Session, claimed: str
    ) -> None:
        """Refuz explicit, nu ignorare tăcută.

        Ignorat, câmpul ar fi lăsat pe cineva să creadă că a marcat documentul ca
        venit din SPV, iar evidența ar fi spus altceva decât ecranul.
        """
        answer = as_admin.post(URL, files=a_file(), data={"source": claimed})

        assert answer.status_code == 422, answer.text
        assert "sistemul" in answer.json()["message"]

    def test_a_word_that_is_not_a_provenance_is_refused(self, as_admin: TestClient) -> None:
        answer = as_admin.post(URL, files=a_file(), data={"source": "PORUMBEL"})

        assert answer.status_code == 422

    def test_nothing_is_stored_when_the_provenance_is_refused(
        self, as_admin: TestClient, db: Session
    ) -> None:
        """Un refuz nu are voie să lase în urmă un document pe jumătate.

        Fișierul a fost deja citit de FastAPI când se verifică proveniența; dacă
        validarea ar fi stat după scriere, un refuz ar fi lăsat un rând orfan.
        """
        before = len(db.query(Document).all())

        as_admin.post(URL, files=a_file(), data={"source": "EFACTURA"})

        assert len(db.query(Document).all()) == before


class TestItShowsUpWhereItMatters:
    def test_the_client_timeline_says_it_came_on_whatsapp(
        self, as_admin: TestClient, client_row: Client
    ) -> None:
        """Locul în care cineva pune întrebarea „dar eu v-am trimis pozele"."""
        answer = as_admin.post(
            URL, files=a_file(), data={"clientId": str(client_row.id), "source": "WHATSAPP"}
        )
        assert answer.status_code == 201, answer.text

        timeline = as_admin.get(f"/api/v1/clients/{client_row.id}/timeline")

        assert timeline.status_code == 200, timeline.text
        assert any("WhatsApp" in str(event.get("detail")) for event in timeline.json()), (
            timeline.text
        )
