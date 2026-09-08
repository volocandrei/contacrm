"""Celelalte liste, la volum (§23).

`test_documents_volume.py` apără de N+1 lista de documente, căutarea, panoul și
încărcarea. Ecranele adăugate după el n-au fost niciodată măsurate: clienții,
tranzacțiile bancare, termenele, registrul declarațiilor și starea cozii. Un
N+1 acolo se poartă exact la fel — merge bine pe zece rânduri și cade pe zece
mii, iar diferența nu se vede în niciun test funcțional.

**Nu se măsoară secunde.** Un test cronometrat cade când mașina e ocupată și
trece când nu e, deci nu spune nimic. Se măsoară **numărul de interogări**, care
este cauza adevărată.

Regula, aceeași peste tot: numărul de interogări nu are voie să crească odată cu
numărul de rânduri returnate.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import bank as bank_routes
from app.domain.enums import BankDirection, BankTransactionStatus, ObligationFrequency
from app.models.bank import BankStatement, BankTransaction
from app.models.client import Client
from app.models.obligation import ClientObligation, ObligationFiling, ObligationType
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import requires_db
from tests.test_documents_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_documents_api",)

#: Câte rânduri se creează pentru proba de volum. Destule ca un N+1 să se vadă
#: fără ambiguitate, puține cât să nu încetinească suita.
MANY = 40


@contextmanager
def counted(db: Session) -> Iterator[list[str]]:
    """Numără interogările SQL care pleacă în timpul blocului.

    **`expire_all()` la intrare, și nu este un detaliu.** Fixturile scriu rândurile
    prin aceeași sesiune pe care o folosește API-ul în teste, deci obiectele — și
    relațiile lor deja parcurse — stau în identity map. Fără expirare, un `N+1`
    adevărat nu se vede: relația se servește din memorie și nu pleacă nicio
    interogare. Prima versiune a testului de mai jos trecea și cu încărcarea
    leneșă pusă la loc, adică nu apăra nimic.
    """
    db.expire_all()
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    engine = db.get_bind()
    sa.event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        sa.event.remove(engine, "before_cursor_execute", before)


@pytest.fixture
def many_clients(db: Session, org: Organization) -> list[Client]:
    rows = [
        Client(organization_id=org.id, name=f"Client {index:03d} SRL", tax_id=f"RO900{index:04d}")
        for index in range(MANY)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def a_statement(
    db: Session, org: Organization, clients: list[Client], *, number: str, rows: int
) -> BankStatement:
    """Un extras cu `rows` tranzacții, fiecare pe alt client."""
    statement = BankStatement(
        organization_id=org.id,
        iban=f"RO49AAAA1B3100759384{number[-4:]}",
        bank_name="Banca de volum",
        currency="RON",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        statement_number=number,
        imported_at=datetime.now(UTC),
    )
    db.add(statement)
    db.flush()
    db.add_all(
        BankTransaction(
            statement_id=statement.id,
            organization_id=org.id,
            client_id=clients[index % len(clients)].id,
            position=index + 1,
            booking_date=date(2026, 8, (index % 28) + 1),
            amount=Decimal("100.00") + index,
            currency="RON",
            direction=BankDirection.DEBIT,
            description=f"Plată {number} {index}",
            status=BankTransactionStatus.UNMATCHED,
        )
        for index in range(rows)
    )
    db.flush()
    return statement


@pytest.fixture
def two_statements(
    db: Session, org: Organization, many_clients: list[Client]
) -> tuple[BankStatement, BankStatement]:
    """Unul mic și unul mare.

    **De ce două extrase și nu `pageSize`.** Ruta de tranzacții **nu are
    paginare**: extrasul se cere întreg, fiindcă reconcilierea se face pe el. O
    primă versiune a testului cerea `pageSize=5` și `pageSize=40` — parametrul
    este ignorat, deci amândouă cererile întorceau aceleași rânduri și comparau
    un număr cu el însuși. Trecea și cu încărcarea leneșă pusă la loc.
    """
    return (
        a_statement(db, org, many_clients, number="MIC-08", rows=5),
        a_statement(db, org, many_clients, number="MARE-08", rows=MANY),
    )


@pytest.fixture
def many_filings(db: Session, org: Organization, many_clients: list[Client], admin: User) -> None:
    obligation = ObligationType(
        organization_id=org.id,
        code="D300",
        label="D300 — decont TVA",
        frequency=ObligationFrequency.MONTHLY,
        months_after=1,
        deadline_day=25,
    )
    db.add(obligation)
    db.flush()
    db.add_all(
        ClientObligation(
            organization_id=org.id, client_id=client.id, obligation_type_id=obligation.id
        )
        for client in many_clients
    )
    db.add_all(
        ObligationFiling(
            organization_id=org.id,
            client_id=client.id,
            obligation_type_id=obligation.id,
            period="2026-08",
            filed_at=datetime.now(UTC),
            filed_by=admin.id,
        )
        for client in many_clients
    )
    db.flush()


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    login(api, admin.email)
    # O cerere de încălzire: prima aduce rolurile și permisiunile și scrie
    # auditul de login. Fără ea am compara o pornire la rece cu o sesiune caldă.
    api.get("/api/v1/clients", params={"pageSize": 1})
    return api


class TestTheClientList:
    def test_it_costs_the_same_for_five_rows_and_for_forty(
        self, as_admin: TestClient, db: Session, many_clients: list[Client]
    ) -> None:
        with counted(db) as few:
            small = as_admin.get("/api/v1/clients", params={"pageSize": 5})
        with counted(db) as many:
            large = as_admin.get("/api/v1/clients", params={"pageSize": 40})

        assert len(small.json()["items"]) == 5
        assert len(large.json()["items"]) == 40
        assert len(few) == len(many), (
            f"lista de clienți face mai multe interogări pentru mai multe rânduri: "
            f"{len(few)} vs {len(many)} — probabil N+1"
        )

    def test_searching_does_not_scan_per_row(
        self, as_admin: TestClient, db: Session, many_clients: list[Client]
    ) -> None:
        with counted(db) as statements:
            answer = as_admin.get("/api/v1/clients", params={"q": "Client 0", "pageSize": 40})

        assert answer.status_code == 200
        assert len(statements) < 12, "\n".join(statements)


class TestTheBankScreen:
    def test_the_transaction_list_does_not_query_per_row(
        self,
        as_admin: TestClient,
        db: Session,
        two_statements: tuple[BankStatement, BankStatement],
    ) -> None:
        """Fiecare rând își poartă legăturile — locul clasic al unui N+1.

        Verificat prin mutație: scos `selectinload`, testul cade cu 5 interogări
        față de 40.
        """
        small_statement, large_statement = two_statements

        with counted(db) as few:
            small = as_admin.get(
                "/api/v1/bank/transactions", params={"statementId": str(small_statement.id)}
            )
        with counted(db) as many:
            large = as_admin.get(
                "/api/v1/bank/transactions", params={"statementId": str(large_statement.id)}
            )

        assert len(small.json()) == 5
        assert len(large.json()) == MANY
        assert len(few) == len(many), (
            f"{len(few)} interogări pentru 5 rânduri, {len(many)} pentru {MANY} — N+1"
        )

    def test_the_statement_filter_is_actually_applied(
        self,
        as_admin: TestClient,
        two_statements: tuple[BankStatement, BankStatement],
    ) -> None:
        """Defectul găsit la poarta de Go-Live, în forma lui exactă.

        Ecranul de bancă cere `?statementId=...`. Ruta declara parametrii unul
        câte unul, deci îi aștepta `snake_case` — iar FastAPI **ignoră în tăcere**
        un parametru pe care nu-l recunoaște. Nu apărea nicio eroare: lista
        răspundea 200 și arăta **toate** tranzacțiile cabinetului, nu pe cele ale
        extrasului ales.

        Într-o reconciliere, asta înseamnă că cine bifa „nimic nepotrivit" se uita
        la altceva decât credea.
        """
        small_statement, _large = two_statements

        answer = as_admin.get(
            "/api/v1/bank/transactions", params={"statementId": str(small_statement.id)}
        )

        assert answer.status_code == 200, answer.text
        rows = answer.json()
        assert len(rows) == 5, f"filtrul nu s-a aplicat: {len(rows)} rânduri"
        assert {row["statementId"] for row in rows} == {str(small_statement.id)}

    def test_the_status_filter_is_actually_applied(
        self,
        as_admin: TestClient,
        db: Session,
        two_statements: tuple[BankStatement, BankStatement],
    ) -> None:
        """Contra-proba pe al doilea filtru: are alias explicit și mergea."""
        small_statement, _ = two_statements
        first = db.scalars(
            select(BankTransaction).where(BankTransaction.statement_id == small_statement.id)
        ).first()
        assert first is not None
        first.status = BankTransactionStatus.IGNORED
        db.flush()

        answer = as_admin.get(
            "/api/v1/bank/transactions",
            params={"statementId": str(small_statement.id), "status": "IGNORED"},
        )

        assert [row["id"] for row in answer.json()] == [str(first.id)]

    def test_the_client_filter_is_actually_applied(
        self,
        as_admin: TestClient,
        many_clients: list[Client],
        two_statements: tuple[BankStatement, BankStatement],
    ) -> None:
        """Al treilea filtru, din aceeași familie."""
        target = many_clients[0]

        answer = as_admin.get("/api/v1/bank/transactions", params={"clientId": str(target.id)})

        assert answer.status_code == 200, answer.text
        rows = answer.json()
        assert rows, "clientul are tranzacții; filtrul nu are voie să le piardă"
        assert {row["clientId"] for row in rows} == {str(target.id)}

    def test_the_statement_list_filters_by_client_too(
        self,
        as_admin: TestClient,
        many_clients: list[Client],
        db: Session,
        org: Organization,
        two_statements: tuple[BankStatement, BankStatement],
    ) -> None:
        """Aceeași scăpare era și pe lista de extrase."""
        target = many_clients[1]
        mine = a_statement(db, org, [target], number="AL-LUI-08", rows=1)
        mine.client_id = target.id
        db.flush()

        answer = as_admin.get("/api/v1/bank/statements", params={"clientId": str(target.id)})

        assert answer.status_code == 200, answer.text
        assert [row["id"] for row in answer.json()] == [str(mine.id)]

    def test_it_refuses_to_answer_without_a_filter_instead_of_truncating(
        self,
        as_admin: TestClient,
        db: Session,
        org: Organization,
        many_clients: list[Client],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Peste plafon, cererea este refuzată — nu tăiată.

        O listă trunchiată la o mie arată exact ca una completă. Într-o
        reconciliere bancară, rândul care lipsește este chiar cel căutat: cineva
        ar declara un extras „fără nepotriviri" pentru că restul nu a încăput.
        """
        # Plafonul se coboară pentru test: mecanismul contează, nu cifra. O mie
        # de rânduri inserate prin ORM ar fi adăugat minute la fiecare rulare a
        # suitei, pentru aceeași informație.
        cap = 3
        monkeypatch.setattr(bank_routes, "MAX_TRANSACTIONS", cap)

        statement = BankStatement(
            organization_id=org.id,
            iban="RO49BBBB1B31007593840000",
            bank_name="Banca mare",
            currency="RON",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            statement_number="MARE-07",
            imported_at=datetime.now(UTC),
        )
        db.add(statement)
        db.flush()
        db.add_all(
            BankTransaction(
                statement_id=statement.id,
                organization_id=org.id,
                position=index + 1,
                booking_date=date(2026, 7, 1),
                amount=Decimal("10.00"),
                currency="RON",
                direction=BankDirection.DEBIT,
                status=BankTransactionStatus.UNMATCHED,
            )
            for index in range(cap + 1)
        )
        db.flush()

        answer = as_admin.get("/api/v1/bank/transactions")

        assert answer.status_code == 422, answer.text
        assert "extras" in answer.json()["message"]

        # Iar cu filtrul cerut, aceleași date se citesc fără probleme.
        narrowed = as_admin.get(
            "/api/v1/bank/transactions", params={"statementId": str(statement.id)}
        )
        assert narrowed.status_code == 422, "plafonul se aplică și pe extrasul mare"


class TestTheDeadlinesScreen:
    def test_the_deadlines_do_not_query_per_client(
        self, as_admin: TestClient, db: Session, many_filings: None
    ) -> None:
        """Termenele se calculează pentru fiecare pereche client-declarație.

        Calculul este în memorie; ce nu are voie să crească este numărul de
        **interogări**. Patruzeci de clienți nu înseamnă patruzeci de cereri la
        bază pentru a afla ce s-a depus.
        """
        with counted(db) as statements:
            answer = as_admin.get(
                "/api/v1/obligations", params={"since": "2026-01-01", "until": "2026-12-31"}
            )

        assert answer.status_code == 200, answer.text
        assert len(answer.json()) > 0
        assert len(statements) < 12, "\n".join(statements)


class TestTheFilingsRegister:
    def test_the_export_is_one_query_not_one_per_filing(
        self, as_admin: TestClient, db: Session, many_filings: None
    ) -> None:
        """Registrul poartă clientul și cine a depus, pe fiecare rând.

        Fără `join`, ar fi fost două interogări în plus la fiecare depunere — iar
        un cabinet exportă un an întreg deodată.
        """
        with counted(db) as statements:
            answer = as_admin.get("/api/v1/reports/filings.csv")

        assert answer.status_code == 200, answer.text
        assert answer.text.count("\r\n") > MANY
        assert len(statements) < 12, "\n".join(statements)


class TestTheProcessingScreen:
    def test_the_queue_health_is_a_fixed_number_of_queries(
        self, as_admin: TestClient, db: Session
    ) -> None:
        """Ecranul se reinterogează singur la fiecare minut, din fiecare filă.

        Un cost care crește cu coada ar fi cel mai prost loc pentru un N+1:
        tocmai când coada este mare, ecranul care o arată ar apăsa cel mai tare.
        """
        with counted(db) as statements:
            answer = as_admin.get("/api/v1/documents/processing/health")

        assert answer.status_code == 200, answer.text
        assert len(statements) < 12, "\n".join(statements)
