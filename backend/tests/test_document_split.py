"""Teancul scanat, desfăcut — drumul întreg (§8, §26, §28).

Regulile de detectare au testul lor, pur, în `test_pdf_split.py`. Aici se verifică
ce se întâmplă cu **fișierele și cu documentele**:

1. **Originalul nu se atinge.** Rămâne în stocare, rămâne descărcabil, își schimbă
   doar starea. Un document contabil nu dispare pentru că am înțeles noi ceva
   despre el.
2. **Fiecare bucată are fișierul ei**, cu chiar paginile ei — nu o copie a
   teancului cu un interval scris alături.
3. **Fiecare bucată știe de unde vine.** Peste un an, „de unde a apărut factura
   asta" trebuie să aibă un răspuns.
4. **Nimic nu se taie singur** și nimic nu se taie de două ori.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.models.client import Client
from app.models.document import Document
from app.models.organization import Organization
from app.models.user import User
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


def page_pdf(lines: list[str]) -> bytes:
    """Un PDF de o pagină, cu text real — `pypdf` îl poate citi înapoi."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    # `pypdf` scrie text prin `add_text`; unde nu există, se compune manual un
    # flux de conținut. Varianta simplă și stabilă: un obiect de text minimal.
    from pypdf.generic import DecodedStreamObject, NameObject

    content = "BT /F1 10 Tf 40 800 Td 14 TL\n"
    for line in lines:
        escaped = line.replace("\\", "").replace("(", "").replace(")", "")
        content += f"({escaped}) Tj T*\n"
    content += "ET"

    stream = DecodedStreamObject()
    stream.set_data(content.encode("latin-1", "replace"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    from pypdf.generic import DictionaryObject

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    resources = DictionaryObject()
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = writer._add_object(font)
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def stack_pdf(pages: list[list[str]]) -> bytes:
    """Un teanc: mai multe pagini într-un singur PDF."""
    writer = PdfWriter()
    for lines in pages:
        writer.append(PdfReader(io.BytesIO(page_pdf(lines))))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


#: Trei facturi într-un fișier — teancul pe care îl trimite un client.
THREE_INVOICES = [
    ["FACTURA FISCALA nr. 7001", "Furnizor: Tert Furnizor SRL", "Total: 1190,00"],
    ["FACTURA FISCALA nr. 7002", "Furnizor: Tert Furnizor SRL", "Total: 690,00"],
    ["FACTURA FISCALA nr. 7003", "Furnizor: Alta Firma SRL", "Total: 250,00"],
]


@pytest.fixture
def stack(
    api_storage: TestClient,
    db: Session,
    admin: User,
    org: Organization,
    client_row: Client,
    storage_provider: LocalStorageProvider,
) -> Document:
    """Teancul, urcat ca orice document."""
    login(api_storage, admin.email)
    answer = api_storage.post(
        "/api/v1/documents/upload",
        files={"file": ("scan_001.pdf", io.BytesIO(stack_pdf(THREE_INVOICES)), "application/pdf")},
        data={"clientId": str(client_row.id)},
    )
    assert answer.status_code == 201, answer.text
    document = db.get(Document, uuid.UUID(answer.json()["id"]))
    assert document is not None
    return document


class TestThePreview:
    def test_it_finds_the_three_invoices_and_says_why(
        self, api_storage: TestClient, stack: Document
    ) -> None:
        answer = api_storage.get(f"/api/v1/documents/{stack.id}/split")

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["pageCount"] == 3
        assert body["readable"] is True
        assert body["splittable"] is True
        assert len(body["segments"]) == 3
        assert [s["documentNumber"] for s in body["segments"]] == ["7001", "7002", "7003"]
        # Prima nu este o tăietură; celelalte două spun de ce s-au tăiat.
        assert body["segments"][0]["reasons"] == []
        assert body["segments"][1]["reasons"]

    def test_the_preview_writes_nothing(
        self, api_storage: TestClient, db: Session, stack: Document
    ) -> None:
        """Altfel previzualizarea ar fi chiar tăierea, iar butonul o formalitate."""
        before = db.query(Document).count()

        api_storage.get(f"/api/v1/documents/{stack.id}/split")
        db.flush()

        assert db.query(Document).count() == before
        assert stack.status is not DocumentStatus.SPLIT

    def test_a_single_document_is_not_splittable(
        self, api_storage: TestClient, db: Session, admin: User, client_row: Client
    ) -> None:
        login(api_storage, admin.email)
        single = api_storage.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "factura.pdf",
                    io.BytesIO(stack_pdf([THREE_INVOICES[0]])),
                    "application/pdf",
                )
            },
        )

        answer = api_storage.get(f"/api/v1/documents/{single.json()['id']}/split")

        assert answer.json()["splittable"] is False
        assert len(answer.json()["segments"]) == 1


class TestTheSplit:
    def test_three_invoices_become_three_documents(
        self, api_storage: TestClient, stack: Document
    ) -> None:
        """Rostul întreg."""
        answer = api_storage.post(f"/api/v1/documents/{stack.id}/split")

        assert answer.status_code == 201, answer.text
        assert len(answer.json()) == 3

    def test_each_piece_has_its_own_file_with_its_own_page(
        self,
        api_storage: TestClient,
        db: Session,
        stack: Document,
        storage_provider: LocalStorageProvider,
    ) -> None:
        """Nu o copie a teancului cu un interval scris alături.

        Verificat citind octeții înapoi: fiecare fișier are **o** pagină, iar
        textul de pe ea este al facturii lui.
        """
        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()

        pieces = db.query(Document).filter(Document.split_from_id == stack.id).all()
        assert len(pieces) == 3

        for piece, expected in zip(
            sorted(pieces, key=lambda item: item.page_from or 0),
            ["7001", "7002", "7003"],
            strict=True,
        ):
            with storage_provider.open(piece.storage_key) as handle:
                reader = PdfReader(io.BytesIO(handle.read()))
            assert len(reader.pages) == 1
            assert expected in (reader.pages[0].extract_text() or "")

    def test_each_piece_knows_where_it_came_from(
        self, api_storage: TestClient, db: Session, stack: Document
    ) -> None:
        """Peste un an, „de unde a apărut factura asta" trebuie să aibă un răspuns."""
        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()

        pieces = sorted(
            db.query(Document).filter(Document.split_from_id == stack.id).all(),
            key=lambda item: item.page_from or 0,
        )

        assert [p.page_from for p in pieces] == [1, 2, 3]
        assert [p.page_to for p in pieces] == [1, 2, 3]
        assert all(p.split_from_id == stack.id for p in pieces)

    def test_the_original_is_kept_and_marked(
        self,
        api_storage: TestClient,
        db: Session,
        stack: Document,
        storage_provider: LocalStorageProvider,
    ) -> None:
        """Nu se șterge și nu se rescrie: rămâne proba din care au ieșit celelalte."""
        key = stack.storage_key

        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()
        db.refresh(stack)

        assert stack.status is DocumentStatus.SPLIT
        assert stack.split_at is not None
        assert stack.deleted_at is None
        # Fișierul este acolo, întreg, cu toate cele trei pagini.
        with storage_provider.open(key) as handle:
            assert len(PdfReader(io.BytesIO(handle.read())).pages) == 3

    def test_the_client_is_inherited(
        self, api_storage: TestClient, db: Session, stack: Document, client_row: Client
    ) -> None:
        """Teancul a venit de la cineva anume; bucățile lui sunt tot ale lui."""
        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()

        pieces = db.query(Document).filter(Document.split_from_id == stack.id).all()
        assert all(p.client_id == client_row.id for p in pieces)

    def test_the_pieces_are_queued_for_reading(
        self, api_storage: TestClient, db: Session, stack: Document
    ) -> None:
        """Fiecare bucată se citește singură: tipul și sumele ei nu se moștenesc.

        Fără asta, cele trei facturi ar fi rămas trei fișiere fără date — adică
        exact munca pe care desfacerea trebuia să o economisească.
        """
        from app.models.document import DocumentProcessingJob

        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()

        pieces = db.query(Document).filter(Document.split_from_id == stack.id).all()
        for piece in pieces:
            jobs = (
                db.query(DocumentProcessingJob)
                .filter(DocumentProcessingJob.document_id == piece.id)
                .count()
            )
            assert jobs == 1


class TestWhatIsRefused:
    def test_a_document_that_is_already_a_piece_cannot_be_split(
        self, api_storage: TestClient, db: Session, stack: Document
    ) -> None:
        api_storage.post(f"/api/v1/documents/{stack.id}/split")
        db.flush()
        piece = db.query(Document).filter(Document.split_from_id == stack.id).first()
        assert piece is not None

        answer = api_storage.post(f"/api/v1/documents/{piece.id}/split")

        assert answer.status_code == 422

    def test_a_single_document_cannot_be_split(self, api_storage: TestClient, admin: User) -> None:
        login(api_storage, admin.email)
        single = api_storage.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "factura.pdf",
                    io.BytesIO(stack_pdf([THREE_INVOICES[0]])),
                    "application/pdf",
                )
            },
        )

        answer = api_storage.post(f"/api/v1/documents/{single.json()['id']}/split")

        assert answer.status_code == 422
        assert "un singur document" in answer.json()["details"]["documentId"][0].lower()

    def test_a_non_pdf_cannot_be_split(self, api_storage: TestClient, admin: User) -> None:
        """O factură electronică este un XML: nu are pagini de tăiat."""
        login(api_storage, admin.email)
        xml = api_storage.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "factura.xml",
                    io.BytesIO(b'<?xml version="1.0"?><Invoice/>'),
                    "application/xml",
                )
            },
        )

        answer = api_storage.post(f"/api/v1/documents/{xml.json()['id']}/split")

        assert answer.status_code == 422
        assert "pdf" in answer.json()["message"].lower()

    def test_another_offices_document_does_not_exist(
        self, api_storage: TestClient, db: Session, admin: User
    ) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO555666")
        db.add(other)
        db.flush()
        foreign = Document(
            organization_id=other.id,
            status=DocumentStatus.RECEIVED,
            source=DocumentSource.UPLOAD,
            original_filename="scan.pdf",
            storage_key=f"organizations/{other.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=10,
            sha256_hash="0" * 64,
            received_at=datetime.now(UTC),
        )
        db.add(foreign)
        db.flush()
        login(api_storage, admin.email)

        assert api_storage.get(f"/api/v1/documents/{foreign.id}/split").status_code == 404
        assert api_storage.post(f"/api/v1/documents/{foreign.id}/split").status_code == 404
