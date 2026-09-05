"""Asistentul explică de ce un document stă acolo unde stă (§22).

**Întrebarea zilnică pe care nimic nu o răspundea.** „De ce e la verificare?",
„de ce n-a fost recunoscut clientul?" Răspunsul exista, dar numai deschizând
documentul și citind insignele câmp cu câmp: care are încredere mică, care
lipsește, dacă sumele se adună. La treizeci de documente pe zi, întrebarea se
pune des și răspunsul se caută greu.

**În ordinea gravității:**

1. **Motivele sunt cele de pe ecran**, luate de la `DocumentValidationService`.
   Un al doilea set de reguli, scris pentru un text mai frumos, ar fi început să
   contrazică ecranul în ziua în care unul dintre ele s-ar fi schimbat.
2. **Nu iese conținutul documentului** (§64): se explică *starea*, nu textul citit.
   Un chat este cea mai largă listă posibilă.
3. **Nu se vede peste organizație** (§72): documentul altui cabinet nu există.
4. **Starea se spune în românește**, cu exact cuvântul de pe ecran.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus
from app.domain.permissions import Permission
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import User
from app.services.assistant.base import AssistantContext
from app.services.assistant.tools import allowed_tools
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

URL = "/api/v1/assistant/chat"


def ask(api: TestClient, message: str) -> dict:
    response = api.post(URL, json={"message": message})
    assert response.status_code == 200, response.text
    return dict(response.json())


def add(
    db: Session,
    org: Organization,
    *,
    filename: str,
    status: DocumentStatus,
    client: Client | None = None,
    document_type: DocumentType | None = None,
    ocr_text: str | None = None,
    total: Decimal | None = None,
    subtotal: Decimal | None = None,
    vat: Decimal | None = None,
) -> Document:
    document = Document(
        organization_id=org.id,
        client_id=client.id if client else None,
        document_type_id=document_type.id if document_type else None,
        status=status,
        source=DocumentSource.UPLOAD,
        original_filename=filename,
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        ocr_text=ocr_text,
        subtotal=subtotal,
        vat_amount=vat,
        total_amount=total,
    )
    db.add(document)
    db.flush()
    return document


# ── Ce spune ─────────────────────────────────────────────────────────────────


class TestWhatItExplains:
    def test_it_says_the_state_in_the_words_from_the_screen(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        add(db, org, filename="chitanta-77.pdf", status=DocumentStatus.REVIEW_REQUIRED)
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare chitanta-77.pdf?")

        assert body["used"] == ["explain_document"]
        assert "Necesită verificare" in body["text"]

    def test_it_says_why_the_client_was_not_recognised(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Cel mai frecvent „de ce", și cel cu cea mai concretă ieșire."""
        add(db, org, filename="factura-fara-cui.pdf", status=DocumentStatus.UNMATCHED)
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce nu are client documentul factura-fara-cui.pdf")

        assert "Clientul nu a fost identificat" in body["text"]
        # Și ce are omul de făcut, nu doar ce s-a întâmplat.
        assert "Atribuie-l o dată" in body["text"]

    def test_the_reasons_are_the_ones_the_review_screen_shows(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        client_row: Client,
    ) -> None:
        """Aritmetica ruptă este exact motivul pe care îl arată ecranul."""
        add(
            db,
            org,
            filename="factura-cu-sume-gresite.pdf",
            status=DocumentStatus.REVIEW_REQUIRED,
            client=client_row,
            subtotal=Decimal("100.00"),
            vat=Decimal("19.00"),
            total=Decimal("200.00"),
        )
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare factura-cu-sume-gresite.pdf")

        assert "Sumele nu se potrivesc" in body["text"]

    def test_it_offers_the_way_to_the_document(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        document = add(db, org, filename="extras-08.pdf", status=DocumentStatus.REVIEW_REQUIRED)
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare extras-08.pdf")

        assert any(str(document.id) in link["path"] for link in body["links"])


# ── Ce nu spune ──────────────────────────────────────────────────────────────


class TestWhatItKeepsQuiet:
    def test_it_does_not_pour_out_the_document_text(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """§64: textul citit nu iese în liste, iar un chat este cea mai largă listă.

        Explicăm **starea**, nu conținutul. Un răspuns care ar recita factura ar
        muta datele clientului în istoricul unei conversații.
        """
        secret = "CONTRACT CONFIDENTIAL ACME"
        add(
            db,
            org,
            filename="contract-08.pdf",
            status=DocumentStatus.REVIEW_REQUIRED,
            ocr_text=secret,
        )
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare contract-08.pdf")

        assert secret not in body["text"]

    def test_a_document_from_another_office_does_not_exist(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """§72: nu 'nu ai voie', ci 'nu există' — altfel răspunsul confirmă că există."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        add(db, other, filename="secret-strain.pdf", status=DocumentStatus.REVIEW_REQUIRED)
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare secret-strain.pdf")

        assert "Nu am găsit" in body["text"]

    def test_it_asks_which_one_when_several_match(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        """Mai bine o întrebare decât un răspuns despre documentul greșit."""
        for index in range(3):
            add(db, org, filename=f"factura-{index}.pdf", status=DocumentStatus.REVIEW_REQUIRED)
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare documentul factura")

        assert "mai multe documente" in body["text"]

    def test_it_asks_which_one_when_nothing_was_named(
        self, api: TestClient, db: Session, org: Organization, admin: User
    ) -> None:
        db.commit()
        login(api, admin.email)

        body = ask(api, "de ce e la verificare documentul?")

        assert "Spune-mi care document" in body["text"]


# ── Cine are voie ────────────────────────────────────────────────────────────


def _context(*permissions: Permission) -> AssistantContext:
    return AssistantContext(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        user_name="Cineva",
        permissions=frozenset(permissions),
    )


def test_reading_documents_is_required() -> None:
    """Un rol fără `documents:read` nu află starea unui document prin chat.

    Bariera este înaintea interogării: unealta nici nu se **declară** pentru cine
    n-o poate chema, deci nici modelul de limbaj nu are ce alege.
    """
    assert all(tool.name != "explain_document" for tool in allowed_tools(_context()))

    # Și cu permisiunea apare — fără verificarea asta, cea de sus ar fi trecut
    # și dacă unealta n-ar fi existat deloc.
    with_read = _context(Permission.DOCUMENTS_READ)
    assert any(tool.name == "explain_document" for tool in allowed_tools(with_read))


# ── Cum recunoaște întrebarea ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("de ce e la verificare factura-1023.pdf?", "factura-1023.pdf"),
        ("ce e cu documentul extras cont august", "extras cont august"),
        ("explică-mi documentul chitanta.jpg", "chitanta.jpg"),
        ("de ce e la verificare?", ""),
        # Un nume cu spații nu se poate spune altfel: tăiat la primul spațiu,
        # „28.5 scan.pdf" devine „scan.pdf", care se potrivește cu jumătate din
        # dosar. Ghilimelele sunt modul în care un om spune, natural, că numele
        # este tot ce e înăuntru.
        ("de ce e la verificare „28.5 scan.pdf”?", "28.5 scan.pdf"),
    ],
)
def test_it_finds_which_document_was_meant(question: str, expected: str) -> None:
    """Numele fișierului se recunoaște singur, oriunde ar sta în frază."""
    from app.services.assistant.rules import extract_document

    assert extract_document(question) == expected
