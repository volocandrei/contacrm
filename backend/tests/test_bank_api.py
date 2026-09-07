"""Reconcilierea, prin API (§13, §14, §15, §43).

**Ce se apără aici, dincolo de regulile de potrivire** (care au testul lor, pur,
în `test_bank_matching.py`):

1. **Nimic nu se leagă singur.** `/suggestions` propune și **nu scrie**. Este
   diferența dintre un asistent și un sistem care mută bani.
2. **Nu se poate aloca mai mult decât există** — nici din plată, nici din factură.
   Verificarea stă în serviciu, nu în interfață: un al doilea ecran ar ocoli-o.
3. **Starea iese din sume.** Parțial înseamnă `NEEDS_REVIEW`, integral `MATCHED`,
   scoasă legătura înseamnă înapoi la `UNMATCHED`.
4. **Extrasul altui cabinet nu există.** `404`, nu `403`.
5. **Reversibil.** O apăsare greșită se desface dintr-un buton — altfel contabilul
   care știe asta nu mai apasă deloc.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.enums import BankDirection, BankTransactionStatus, DocumentSource, DocumentStatus
from app.models.bank import BankStatement, BankTransaction
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

URL = "/api/v1/bank"


@pytest.fixture
def supplier_invoice(
    db: Session, org: Organization, client_row: Client, types: dict[str, DocumentType]
) -> Document:
    """O factură de la furnizor, de 1190 lei, din 14 august."""
    document = Document(
        organization_id=org.id,
        client_id=client_row.id,
        document_type_id=types["FACTURA_INTRARE"].id,
        status=DocumentStatus.APPROVED,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        document_date=date(2026, 8, 14),
        reference_month="2026-08",
        series="FCT",
        document_number="7001",
        supplier_name="Terț Furnizor SRL",
        supplier_tax_id="RO99887766",
        total_amount=Decimal("1190.00"),
        currency="RON",
    )
    db.add(document)
    db.flush()
    return document


@pytest.fixture
def statement(db: Session, org: Organization, client_row: Client) -> BankStatement:
    row = BankStatement(
        organization_id=org.id,
        client_id=client_row.id,
        bank_name="Banca de Probă",
        iban="RO00TEST0000000000000009",
        statement_number="8",
        currency="RON",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        imported_at=clock.now(),
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def payment(
    db: Session, org: Organization, client_row: Client, statement: BankStatement
) -> BankTransaction:
    """Plata facturii: 1190 lei ieșiți, cu numărul scris în referință."""
    row = BankTransaction(
        statement_id=statement.id,
        organization_id=org.id,
        client_id=client_row.id,
        position=1,
        booking_date=date(2026, 8, 20),
        description="Plata factura",
        amount=Decimal("-1190.00"),
        currency="RON",
        direction=BankDirection.DEBIT,
        counterparty_name="TERT FURNIZOR SRL",
        reference="FCT 7001",
        status=BankTransactionStatus.UNMATCHED,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> None:
    login(api, admin.email)


@pytest.mark.usefixtures("as_admin")
class TestSuggestions:
    def test_the_invoice_is_proposed_with_its_reasons(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Drumul întreg: extras → propunere → motive citibile."""
        answer = api.get(f"{URL}/transactions/{payment.id}/suggestions")

        assert answer.status_code == 200, answer.text
        found = answer.json()
        assert len(found) == 1
        assert found[0]["documentId"] == str(supplier_invoice.id)
        assert "numărul facturii apare în plată" in found[0]["reasons"]
        assert found[0]["amount"] == "1190.00"

    def test_asking_for_suggestions_writes_nothing(
        self, api: TestClient, db: Session, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Diferența dintre un asistent și un sistem care mută bani singur."""
        api.get(f"{URL}/transactions/{payment.id}/suggestions")
        db.flush()

        assert payment.matches == []
        assert payment.status is BankTransactionStatus.UNMATCHED

    def test_an_invoice_of_the_wrong_direction_is_not_proposed(
        self,
        api: TestClient,
        db: Session,
        payment: BankTransaction,
        supplier_invoice: Document,
        types: dict[str, DocumentType],
    ) -> None:
        """O plată nu poate închide o factură emisă. Nici cu numărul potrivit."""
        supplier_invoice.document_type_id = types["FACTURA_IESIRE"].id
        db.flush()

        assert api.get(f"{URL}/transactions/{payment.id}/suggestions").json() == []


@pytest.mark.usefixtures("as_admin")
class TestMatching:
    def test_a_full_match_closes_the_transaction(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        answer = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id)},
        )

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["status"] == "MATCHED"
        assert body["allocated"] == "1190.00"
        assert body["unallocated"] == "0.00"
        assert body["matches"][0]["documentNumber"] == "7001"

    def test_a_partial_payment_leaves_the_transaction_for_a_human(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Parțial nu este nici gata, nici de la capăt.

        `NEEDS_REVIEW` este singura stare care spune adevărul: s-a pus ceva, dar
        nu tot. Marcat `MATCHED`, restul de plată ar fi dispărut din vedere.
        """
        answer = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "500.00"},
        )

        assert answer.json()["status"] == "NEEDS_REVIEW"
        assert answer.json()["unallocated"] == "690.00"

    def test_more_than_the_transaction_is_refused(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Din 1190 nu se pot aloca 2000, oricâte facturi ar exista."""
        answer = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "2000.00"},
        )

        assert answer.status_code == 422
        assert "tranzacți" in answer.json()["message"].lower()

    def test_more_than_the_invoice_is_refused(
        self, api: TestClient, db: Session, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Pe o factură de 1190 nu se pot pune 1190 de două ori.

        Fără regula asta, o factură ar fi apărut plătită de două ori, iar restul
        de plată al furnizorului ar fi ieșit negativ.
        """
        supplier_invoice.total_amount = Decimal("500.00")
        db.flush()

        answer = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "800.00"},
        )

        assert answer.status_code == 422
        assert "factur" in answer.json()["message"].lower()

    def test_matching_the_same_invoice_twice_grows_the_link(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Două rânduri pe aceeași pereche ar fi făcut ca „cât s-a plătit" să
        depindă de câte ori a apăsat cineva."""
        first = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "500.00"},
        )
        second = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "690.00"},
        )

        assert first.status_code == second.status_code == 200
        assert len(second.json()["matches"]) == 1
        assert second.json()["matches"][0]["amount"] == "1190.00"
        assert second.json()["status"] == "MATCHED"

    def test_one_payment_can_close_two_invoices(
        self,
        api: TestClient,
        db: Session,
        payment: BankTransaction,
        supplier_invoice: Document,
        types: dict[str, DocumentType],
        org: Organization,
        client_row: Client,
    ) -> None:
        """Cazul pe care un model unu-la-unu nu îl poate scrie deloc."""
        supplier_invoice.total_amount = Decimal("690.00")
        second = Document(
            organization_id=org.id,
            client_id=client_row.id,
            document_type_id=types["FACTURA_INTRARE"].id,
            status=DocumentStatus.APPROVED,
            source=DocumentSource.UPLOAD,
            original_filename="factura2.pdf",
            storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=512,
            sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            received_at=datetime.now(UTC),
            document_date=date(2026, 8, 15),
            document_number="7002",
            total_amount=Decimal("500.00"),
            currency="RON",
        )
        db.add(second)
        db.flush()

        api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id), "amount": "690.00"},
        )
        answer = api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(second.id), "amount": "500.00"},
        )

        assert answer.json()["status"] == "MATCHED"
        assert len(answer.json()["matches"]) == 2


@pytest.mark.usefixtures("as_admin")
class TestUndoing:
    def test_a_link_can_be_removed(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Fără asta, o apăsare greșită ar cere o intervenție în bază — iar
        contabilul care știe asta nu mai apasă deloc."""
        api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id)},
        )

        answer = api.delete(f"{URL}/transactions/{payment.id}/match/{supplier_invoice.id}")

        assert answer.status_code == 200, answer.text
        assert answer.json()["status"] == "UNMATCHED"
        assert answer.json()["matches"] == []

    def test_a_bank_fee_can_be_marked_as_settled(
        self, api: TestClient, payment: BankTransaction
    ) -> None:
        """Un comision de trei lei nu este „nepotrivit", este lămurit.

        Fără starea asta, lista de nepotrivite nu s-ar goli niciodată — iar o
        listă care nu se golește nu se mai deschide.
        """
        answer = api.post(
            f"{URL}/transactions/{payment.id}/ignore",
            json={"note": "Comision de administrare"},
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["status"] == "IGNORED"
        assert answer.json()["note"] == "Comision de administrare"

    def test_a_settled_transaction_can_come_back(
        self, api: TestClient, payment: BankTransaction
    ) -> None:
        api.post(f"{URL}/transactions/{payment.id}/ignore", json={"note": "greșeală"})

        answer = api.post(f"{URL}/transactions/{payment.id}/reopen")

        assert answer.json()["status"] == "UNMATCHED"
        assert answer.json()["note"] is None

    def test_a_matched_transaction_cannot_be_hidden_as_settled(
        self, api: TestClient, payment: BankTransaction, supplier_invoice: Document
    ) -> None:
        """Altfel o plată ar fi și legată de o factură, și „fără factură"."""
        api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id)},
        )

        answer = api.post(f"{URL}/transactions/{payment.id}/ignore", json={"note": "x"})

        assert answer.status_code == 422


@pytest.mark.usefixtures("as_admin")
class TestIsolation:
    def test_another_offices_transaction_does_not_exist(self, api: TestClient, db: Session) -> None:
        """`404`, nu `403`: un „nu ai voie" confirmă că id-ul există undeva."""
        other = Organization(name="Alt Cabinet SRL", tax_id="RO111222")
        db.add(other)
        db.flush()
        foreign_statement = BankStatement(
            organization_id=other.id,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            imported_at=clock.now(),
        )
        db.add(foreign_statement)
        db.flush()
        foreign = BankTransaction(
            statement_id=foreign_statement.id,
            organization_id=other.id,
            position=1,
            booking_date=date(2026, 8, 10),
            amount=Decimal("-100.00"),
            direction=BankDirection.DEBIT,
        )
        db.add(foreign)
        db.flush()

        assert api.get(f"{URL}/transactions/{foreign.id}/suggestions").status_code == 404
        assert (
            api.post(
                f"{URL}/transactions/{foreign.id}/match",
                json={"documentId": str(uuid.uuid4())},
            ).status_code
            == 404
        )

    def test_the_statement_list_only_shows_my_office(
        self, api: TestClient, statement: BankStatement, db: Session
    ) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO333444")
        db.add(other)
        db.flush()
        db.add(
            BankStatement(
                organization_id=other.id,
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
                imported_at=clock.now(),
            )
        )
        db.flush()

        answer = api.get(f"{URL}/statements")

        assert [row["id"] for row in answer.json()] == [str(statement.id)]


@pytest.mark.usefixtures("as_admin")
class TestTheStatementList:
    def test_it_counts_what_still_needs_a_human(
        self, api: TestClient, statement: BankStatement, payment: BankTransaction
    ) -> None:
        """Singurul număr după care se alege extrasul de deschis."""
        answer = api.get(f"{URL}/statements")

        row = answer.json()[0]
        assert row["transactionCount"] == 1
        assert row["openCount"] == 1

    def test_a_matched_transaction_leaves_the_open_count(
        self,
        api: TestClient,
        statement: BankStatement,
        payment: BankTransaction,
        supplier_invoice: Document,
    ) -> None:
        api.post(
            f"{URL}/transactions/{payment.id}/match",
            json={"documentId": str(supplier_invoice.id)},
        )

        assert api.get(f"{URL}/statements").json()[0]["openCount"] == 0
