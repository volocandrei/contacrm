"""Extrasul de cont, dintr-un fișier de internet banking (§11, §12).

**Ce se apără aici, în ordinea gravității.**

1. **Separatorul zecimal.** `1.234,56` și `1,234.56` sunt aceeași sumă scrisă de
   două programe. Ghicit greșit, din 1.234 de lei rămâne un leu și douăzeci și
   trei de bani — iar asta nu se vede: extrasul se importă, rândurile sunt acolo,
   totalul este pur și simplu altul.
2. **Coloana de dată.** „Data" se potrivește exact, nu pe „conține": altfel ar
   fi înghițit „Data valutei", iar toate tranzacțiile ar fi ajuns cu una sau două
   zile alături — o eroare uniformă, invizibilă în total, care mută operațiuni
   dintr-o lună în alta.
3. **Un rând stricat nu oprește fișierul.** Un extras cu două rânduri ilizibile
   din trei sute trebuie să intre cu 298, iar cele două să fie numite.
4. **Același extras de două ori nu dublează nimic.**
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import BankDirection, ImportOutcome
from app.models.bank import BankStatement, BankTransaction
from app.models.organization import Organization
from app.models.user import User
from app.services.bank_import import BankImportService, parse, parse_amount, parse_date
from tests.conftest import requires_db
from tests.test_periods_api import login  # noqa: F401 — încarcă fixtures

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


#: Sfarsitul de linie pe care il scriu exporturile de Windows.
CRLF = chr(13) + chr(10)

#: Un export cum îl scrie o bancă românească: `;`, zecimale cu virgulă,
#: mii cu punct, două coloane pentru sensul banilor.
BANCA_RO = "\r\n".join(
    [
        "Data;Data valutei;Descriere;Debit;Credit;Moneda;Beneficiar;IBAN;Referinta",
        "14.08.2026;15.08.2026;Plata factura;1.190,00;;RON;TERT FURNIZOR SRL;"
        "RO49AAAA1B31007593840000;FCT 7001",
        "18.08.2026;18.08.2026;Incasare;;4.500,50;RON;ALFA CONTA SRL;"
        "RO12BBBB1B31007593840001;FCT 118",
        "20.08.2026;20.08.2026;Comision administrare;3,50;;RON;;;",
    ]
)

#: Alt export, în engleză: `,`, o singură coloană cu semn, altă ordine de dată.
BANCA_EN = "\n".join(
    [
        "Booking Date,Description,Amount,Currency",
        "2026-08-14,Payment invoice FCT 7001,-1190.00,RON",
        "2026-08-18,Incoming transfer,4500.50,RON",
    ]
)


class TestReadingTheAmount:
    """Cel mai scump loc în care se poate greși tăcut."""

    def test_the_romanian_format_is_read_as_thousands_and_decimals(self) -> None:
        assert parse_amount("1.190,00") == Decimal("1190.00")
        assert parse_amount("1.234.567,89") == Decimal("1234567.89")

    def test_the_english_format_too(self) -> None:
        assert parse_amount("1,190.00") == Decimal("1190.00")
        assert parse_amount("1234567.89") == Decimal("1234567.89")

    def test_a_single_separator_with_three_digits_after_it_is_thousands(self) -> None:
        """`1.234` sunt o mie două sute treizeci și patru, nu un leu și 234 de bani.

        Este cazul care nu se poate deduce din reguli generale, iar greșeala
        schimbă suma de o mie de ori.
        """
        assert parse_amount("1.234") == Decimal("1234")
        assert parse_amount("1,234") == Decimal("1234")

    def test_two_digits_after_the_separator_are_money(self) -> None:
        assert parse_amount("12,50") == Decimal("12.50")
        assert parse_amount("12.50") == Decimal("12.50")

    def test_a_negative_amount_keeps_its_sign(self) -> None:
        assert parse_amount("-1.190,00") == Decimal("-1190.00")

    def test_what_cannot_be_read_is_absent_not_zero(self) -> None:
        """Zero este o afirmație: „tranzacție de zero lei". Absența este alta."""
        assert parse_amount("") is None
        assert parse_amount("n/a") is None
        assert parse_amount(None) is None


class TestReadingTheDate:
    def test_the_formats_the_banks_write(self) -> None:
        for raw in ("14.08.2026", "14/08/2026", "2026-08-14", "14-08-2026"):
            assert parse_date(raw) == date(2026, 8, 14)

    def test_a_date_that_cannot_be_read_is_absent(self) -> None:
        assert parse_date("saptamana trecuta") is None
        assert parse_date(None) is None


class TestReadingTheFile:
    def test_a_romanian_export_is_read_whole(self) -> None:
        rows, problems = parse(BANCA_RO)

        assert not problems
        assert len(rows) == 3
        assert rows[0].booking_date == date(2026, 8, 14)
        assert rows[0].amount == Decimal("-1190.00")
        assert rows[0].direction is BankDirection.DEBIT
        assert rows[0].counterparty_name == "TERT FURNIZOR SRL"
        assert rows[0].reference == "FCT 7001"

    def test_the_debit_column_becomes_a_negative_amount(self) -> None:
        """Semnul are o singură sursă de adevăr: suma. Direcția se derivă din ea."""
        rows, _ = parse(BANCA_RO)

        assert rows[1].amount == Decimal("4500.50")
        assert rows[1].direction is BankDirection.CREDIT

    def test_the_value_date_does_not_steal_the_booking_date(self) -> None:
        """Potrivirea „conține" ar fi mutat toate tranzacțiile cu o zi.

        Uniform, deci invizibil în total — și suficient ca operațiunile de la
        sfârșitul lunii să cadă în luna următoare.
        """
        rows, _ = parse(BANCA_RO)

        assert rows[0].booking_date == date(2026, 8, 14)
        assert rows[0].value_date == date(2026, 8, 15)

    def test_the_value_date_does_not_steal_it_even_when_it_comes_first(self) -> None:
        """Aceeași capcană, cu coloanele în ordinea inversă.

        Testul de mai sus trece și cu o potrivire pe „conține", fiindcă „Data"
        apare prima în fișier și își ia locul înainte. Aici „Data valutei" este
        prima — iar o potrivire pe „conține" i-ar da ei rolul de dată a
        operațiunii, mutând toate tranzacțiile cu o zi.
        """
        reversed_columns = CRLF.join(
            [
                "Data valutei;Data;Descriere;Suma;Moneda",
                "15.08.2026;14.08.2026;Plata;-1.190,00;RON",
            ]
        )

        rows, problems = parse(reversed_columns)

        assert not problems
        assert rows[0].booking_date == date(2026, 8, 14)
        assert rows[0].value_date == date(2026, 8, 15)

    def test_an_english_export_with_one_signed_column_works_too(self) -> None:
        rows, problems = parse(BANCA_EN)

        assert not problems
        assert [row.amount for row in rows] == [Decimal("-1190.00"), Decimal("4500.50")]

    def test_a_broken_row_is_named_and_the_rest_go_through(self) -> None:
        """Refuzul total ar muta munca înapoi la om — exact ce economisește importul."""
        text = BANCA_RO + "\r\n" + "candva;;Ceva;100,00;;RON;;;"

        rows, problems = parse(text)

        assert len(rows) == 3
        assert len(problems) == 1
        assert problems[0].outcome is ImportOutcome.INVALID
        assert "Data" in (problems[0].note or "")

    def test_a_row_without_an_amount_is_refused_not_imported_as_zero(self) -> None:
        text = BANCA_RO + "\r\n" + "21.08.2026;;Fara suma;;;RON;;;"

        _, problems = parse(text)

        assert len(problems) == 1
        assert "Suma" in (problems[0].note or "")

    def test_a_file_without_a_date_column_is_refused_with_what_is_missing(self) -> None:
        """Mesajul spune ce antet lipsește, nu „fișier invalid"."""
        from app.core.errors import AppError

        with pytest.raises(AppError) as caught:
            parse("Descriere;Suma\r\nCeva;100,00")

        assert "data" in str(caught.value).lower()


@pytest.fixture
def service(db: Session, org: Organization) -> BankImportService:
    return BankImportService(db, org.id)


class TestPreviewAndApply:
    def test_the_preview_writes_nothing(self, service: BankImportService, db: Session) -> None:
        """Prima trecere nu atinge nimic. Altfel previzualizarea ar fi un import."""
        plan = service.plan(
            BANCA_RO,
            actor=None,
            client_id=None,
            iban="RO00TEST0000000000000001",
            bank_name="Banca de Probă",
            statement_number="8",
            opening_balance=None,
            closing_balance=None,
            apply=False,
        )
        db.flush()

        assert plan.created == 3
        assert plan.statement_id is None
        assert db.query(BankStatement).count() == 0
        assert db.query(BankTransaction).count() == 0

    def test_applying_writes_the_statement_and_its_rows(
        self, service: BankImportService, db: Session, admin: User
    ) -> None:
        plan = service.plan(
            BANCA_RO,
            actor=admin,
            client_id=None,
            iban="RO00 TEST 0000 0000 0000 0001",
            bank_name="Banca de Probă",
            statement_number="8",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("4307.00"),
            apply=True,
        )
        db.flush()

        assert plan.created == 3
        statement = db.get(BankStatement, plan.statement_id)
        assert statement is not None
        # IBAN-ul se normalizează: fără spații, majuscule — forma în care se compară.
        assert statement.iban == "RO00TEST0000000000000001"
        assert statement.period_start == date(2026, 8, 14)
        assert statement.period_end == date(2026, 8, 20)
        assert len(statement.transactions) == 3
        assert [t.position for t in statement.transactions] == [1, 2, 3]

    def test_the_balance_gap_is_reported_not_hidden(
        self, service: BankImportService, admin: User
    ) -> None:
        """Soldul care nu se închide **este** informația: fișierul e incomplet.

        Un sold calculat de noi ar fi ascuns exact ce poate dovedi extrasul.
        """
        plan = service.plan(
            BANCA_RO,
            actor=admin,
            client_id=None,
            iban="RO00TEST0000000000000002",
            bank_name=None,
            statement_number=None,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("9999.00"),
            apply=False,
        )

        # 1000 - 1190 + 4500,50 - 3,50 = 4307. Declarat: 9999.
        assert plan.balance_gap == Decimal("5692.00")

    def test_the_gap_is_zero_when_everything_adds_up(
        self, service: BankImportService, admin: User
    ) -> None:
        plan = service.plan(
            BANCA_RO,
            actor=admin,
            client_id=None,
            iban="RO00TEST0000000000000003",
            bank_name=None,
            statement_number=None,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("4307.00"),
            apply=False,
        )

        assert plan.balance_gap == Decimal("0.00")


class TestImportingTwice:
    def test_the_same_file_twice_does_not_double_the_transactions(
        self, service: BankImportService, db: Session, admin: User
    ) -> None:
        """Cea mai probabilă greșeală de operare: „nu sunt sigur că a mers, mai încerc".

        Dublate, tranzacțiile ar fi făcut ca soldul să nu se mai închidă niciodată,
        iar reconcilierea ar fi propus fiecare plată de două ori.
        """
        common = {
            "actor": admin,
            "client_id": None,
            "iban": "RO00TEST0000000000000004",
            "bank_name": None,
            "statement_number": "8",
            "opening_balance": None,
            "closing_balance": None,
        }
        first = service.plan(BANCA_RO, apply=True, **common)  # type: ignore[arg-type]
        db.flush()
        second = service.plan(BANCA_RO, apply=True, **common)  # type: ignore[arg-type]
        db.flush()

        assert first.created == 3
        assert second.created == 0
        assert second.skipped == 3
        assert first.statement_id == second.statement_id
        assert db.query(BankTransaction).count() == 3

    def test_a_second_file_with_new_rows_adds_only_those(
        self, service: BankImportService, db: Session, admin: User
    ) -> None:
        """Extrasul retrimis cu o zi în plus: intră doar ziua nouă."""
        common = {
            "actor": admin,
            "client_id": None,
            "iban": "RO00TEST0000000000000005",
            "bank_name": None,
            "statement_number": "8",
            "opening_balance": None,
            "closing_balance": None,
        }
        service.plan(BANCA_RO, apply=True, **common)  # type: ignore[arg-type]
        db.flush()

        # Aceeași perioadă, plus o operațiune nouă în ziua de mijloc.
        extended = BANCA_RO + "\r\n" + "19.08.2026;19.08.2026;Plata noua;500,00;;RON;;;"
        second = service.plan(extended, apply=True, **common)  # type: ignore[arg-type]
        db.flush()

        assert second.created == 1
        assert second.skipped == 3
        assert db.query(BankTransaction).count() == 4
