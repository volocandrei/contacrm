"""Onorariile, pe API.

Ce apără testele, în ordinea importanței:

1. **Registrul nu își rescrie trecutul.** O renegociere de azi nu schimbă suma
   unei luni deja facturate. Dacă asta cade, aplicația nu mai este un registru,
   ci o părere despre trecut.
2. **Nu inventează datorii.** Un cabinet care își configurează onorariile azi nu
   deschide ecranul pe restanțe pentru toate lunile din urmă — greșeala făcută o
   dată la termene și corectată acolo.
3. **Generarea se poate apăsa de două ori.** Al doilea clic nu dublează nimic și
   nu șterge încasările marcate între timp.
4. **Cifrele sunt suma rândurilor de pe ecran**, pe monedă. Un total care adună
   lei cu euro este un număr pe care cineva îl va crede.
5. **Banii nu se văd de la orice rol**, și nu trec granița dintre cabinete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus, DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.document import Document
from app.models.fee import ClientFee, FeeEntry
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
URL = "/api/v1/fees"
MONTH = "2026-08"
EARLIER = "2026-07"


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


def make_client(db: Session, org: Organization, name: str, *, months_ago: int = 12) -> Client:
    """Un client activ, intrat în cabinet demult.

    „Demult" contează: un client apare pe o lună doar dacă relația începuse, iar
    unul adăugat azi nu are ce căuta pe luna trecută.
    """
    row = Client(
        organization_id=org.id,
        name=name,
        tax_id=f"RO{abs(hash(name)) % 100000}",
        status=ClientStatus.ACTIVE,
        created_at=datetime.now(UTC) - timedelta(days=30 * months_ago),
    )
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
def alfa(db: Session, org: Organization) -> Client:
    return make_client(db, org, "Alfa Conta SRL")


@pytest.fixture
def beta(db: Session, org: Organization) -> Client:
    return make_client(db, org, "Beta Prod SRL")


@pytest.fixture
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    response = api.post("/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD})
    assert response.status_code == 200
    return api


def set_fee(
    api: TestClient,
    client: Client,
    amount: str,
    *,
    currency: str = "RON",
    starts_on: str = "2020-01-01",
) -> None:
    response = api.put(
        f"{URL}/clients/{client.id}",
        json={"amount": amount, "currency": currency, "startsOn": starts_on},
    )
    assert response.status_code == 200, response.text


def generate(api: TestClient, month: str = MONTH) -> dict:  # type: ignore[type-arg]
    response = api.post(f"{URL}/generate", json={"referenceMonth": month})
    assert response.status_code == 200, response.text
    return response.json()


def row_for(payload: dict, client: Client) -> dict:  # type: ignore[type-arg]
    matches = [row for row in payload["rows"] if row["clientId"] == str(client.id)]
    assert matches, f"{client.name} nu apare pe lună"
    return matches[0]


class TestTheLedgerKeepsItsPast:
    def test_a_renegotiation_does_not_rewrite_a_generated_month(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Cel mai important test din fișier.

        Onorariul crește de la 500 la 800. Luna deja facturată rămâne 500 —
        altfel istoricul s-ar rescrie singur la fiecare renegociere.
        """
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)

        set_fee(as_admin, alfa, "800.00")

        after = as_admin.get(URL, params={"referenceMonth": MONTH}).json()
        row = row_for(after, alfa)
        assert row["amount"] == "500.00"
        # Ce se va factura de acum înainte este totuși cel nou.
        assert row["configured"] == "800.00"

    def test_regenerating_does_not_touch_what_exists(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Al doilea clic nu dublează rândul și nu pierde încasarea."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)
        paid = as_admin.post(
            f"{URL}/payments",
            json={"clientId": str(alfa.id), "referenceMonth": MONTH, "paidOn": "2026-08-10"},
        )
        assert paid.status_code == 201, paid.text
        set_fee(as_admin, alfa, "800.00")

        again = generate(as_admin)

        rows = [row for row in again["rows"] if row["clientId"] == str(alfa.id)]
        assert len(rows) == 1
        assert rows[0]["amount"] == "500.00"
        assert rows[0]["paidOn"] == "2026-08-10"

    def test_a_month_stays_visible_after_the_client_leaves(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        """Restanța unui client plecat este exact cea care nu trebuie să dispară."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)

        alfa.status = ClientStatus.INACTIVE
        db.flush()

        after = as_admin.get(URL, params={"referenceMonth": MONTH}).json()
        assert row_for(after, alfa)["amount"] == "500.00"


class TestItDoesNotInventDebts:
    def test_a_fee_configured_today_does_not_bill_last_year(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Regula care lipsea o dată la termene și a produs 52 de rânduri roșii.

        Contractul începe în august. Martie nu se facturează — dar august, da:
        fără a doua jumătate, testul ar trece și dacă generarea n-ar face nimic
        niciodată.
        """
        set_fee(as_admin, alfa, "500.00", starts_on="2026-08-01")

        march = generate(as_admin, "2026-03")
        assert [row for row in march["rows"] if row["isGenerated"]] == []

        august = generate(as_admin, "2026-08")
        assert row_for(august, alfa)["amount"] == "500.00"

    def test_a_client_without_a_fee_is_shown_but_not_billed(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Cine n-are onorariu stabilit trebuie **văzut**, nu ascuns.

        Un ecran care ar afișa doar clienții configurați ar arăta identic într-un
        cabinet pus la punct și în unul care a uitat jumătate din listă.
        """
        payload = generate(as_admin)

        row = row_for(payload, alfa)
        assert row["configured"] is None
        assert row["isGenerated"] is False

    def test_a_future_month_is_refused(self, as_admin: TestClient, alfa: Client) -> None:
        next_year = f"{date.today().year + 1}-01"
        response = as_admin.post(f"{URL}/generate", json={"referenceMonth": next_year})
        assert response.status_code == 422

    def test_a_client_added_today_does_not_appear_on_old_months(
        self, as_admin: TestClient, db: Session, org: Organization
    ) -> None:
        fresh = make_client(db, org, "Nou Venit SRL", months_ago=0)

        payload = as_admin.get(URL, params={"referenceMonth": "2024-01"}).json()

        assert [row for row in payload["rows"] if row["clientId"] == str(fresh.id)] == []


class TestTheNumbers:
    def test_the_totals_are_the_sum_of_the_rows(
        self, as_admin: TestClient, alfa: Client, beta: Client
    ) -> None:
        set_fee(as_admin, alfa, "500.00")
        set_fee(as_admin, beta, "300.50")
        generate(as_admin)
        as_admin.post(f"{URL}/payments", json={"clientId": str(alfa.id), "referenceMonth": MONTH})

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()

        (totals,) = payload["totals"]
        assert totals["currency"] == "RON"
        assert Decimal(totals["billed"]) == Decimal("800.50")
        assert Decimal(totals["collected"]) == Decimal("500.00")
        assert Decimal(totals["outstanding"]) == Decimal("300.50")
        assert payload["unpaidClients"] == 1

    def test_two_currencies_make_two_lines_not_one_wrong_number(
        self, as_admin: TestClient, alfa: Client, beta: Client
    ) -> None:
        """Adunarea leilor cu euro ar da o cifră pe care cineva ar crede-o."""
        set_fee(as_admin, alfa, "500.00")
        set_fee(as_admin, beta, "100.00", currency="EUR")
        generate(as_admin)

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()

        assert [item["currency"] for item in payload["totals"]] == ["RON", "EUR"]
        assert Decimal(payload["totals"][0]["billed"]) == Decimal("500.00")
        assert Decimal(payload["totals"][1]["billed"]) == Decimal("100.00")

    def test_old_unpaid_months_are_listed_separately(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Restanța veche nu se mai vede nicăieri altundeva: luna trece, ecranul
        se schimbă, iar banii rămân neîncasați."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, EARLIER)
        generate(as_admin, MONTH)

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()

        assert [item["period"] for item in payload["arrears"]] == [EARLIER]

    def test_a_paid_old_month_leaves_the_arrears(self, as_admin: TestClient, alfa: Client) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, EARLIER)
        generate(as_admin, MONTH)

        as_admin.post(f"{URL}/payments", json={"clientId": str(alfa.id), "referenceMonth": EARLIER})

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()
        assert payload["arrears"] == []


class TestThePayment:
    def test_marking_and_unmarking(self, as_admin: TestClient, alfa: Client) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)

        marked = as_admin.post(
            f"{URL}/payments",
            json={"clientId": str(alfa.id), "referenceMonth": MONTH, "paidOn": "2026-08-11"},
        )
        assert marked.status_code == 201
        assert marked.json()["isPaid"] is True
        assert marked.json()["paidByName"] == "Ioana Marinescu"

        removed = as_admin.request(
            "DELETE",
            f"{URL}/payments",
            params={"clientId": str(alfa.id), "referenceMonth": MONTH},
        )
        assert removed.status_code == 200
        assert removed.json()["isPaid"] is False
        # Rândul rămâne: luna a fost facturată chiar dacă banii nu au intrat.
        assert removed.json()["isGenerated"] is True

    def test_an_ungenerated_month_cannot_be_paid(self, as_admin: TestClient, alfa: Client) -> None:
        response = as_admin.post(
            f"{URL}/payments", json={"clientId": str(alfa.id), "referenceMonth": MONTH}
        )
        assert response.status_code == 404

    def test_clearing_the_fee_stops_future_billing(
        self, as_admin: TestClient, alfa: Client
    ) -> None:
        """Ștergerea onorariului nu este același lucru cu zero.

        Zero înseamnă „îl servesc gratuit" și se generează; lipsa lui înseamnă
        „nu-l facturez" și nu se generează.
        """
        set_fee(as_admin, alfa, "500.00")
        cleared = as_admin.put(f"{URL}/clients/{alfa.id}", json={"amount": None})
        assert cleared.status_code == 200
        assert cleared.json()["amount"] is None

        payload = generate(as_admin)
        assert row_for(payload, alfa)["isGenerated"] is False

    def test_zero_is_billed(self, as_admin: TestClient, alfa: Client) -> None:
        set_fee(as_admin, alfa, "0.00")

        payload = generate(as_admin)

        assert row_for(payload, alfa)["isGenerated"] is True


class TestWhoMaySee:
    def test_an_accountant_cannot_see_the_money(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Lista este ordinea în care cabinetul își ține clienții după bani."""
        user = make_user(db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT)
        api.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})

        assert api.get(URL, params={"referenceMonth": MONTH}).status_code == 403

    def test_another_organizations_client_is_not_found(
        self, as_admin: TestClient, db: Session
    ) -> None:
        """§72: 404, nu 403 — un 403 ar confirma că id-ul există altundeva."""
        stranger_org = Organization(name="Alt Cabinet SRL")
        db.add(stranger_org)
        db.flush()
        stranger = make_client(db, stranger_org, "Străin SRL")

        response = as_admin.put(f"{URL}/clients/{stranger.id}", json={"amount": "100.00"})

        assert response.status_code == 404

    def test_another_organizations_rows_never_appear(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        stranger_org = Organization(name="Alt Cabinet SRL")
        db.add(stranger_org)
        db.flush()
        stranger = make_client(db, stranger_org, "Străin SRL")
        db.add(
            ClientFee(
                organization_id=stranger_org.id,
                client_id=stranger.id,
                amount=Decimal("900.00"),
                currency="RON",
                starts_on=date(2020, 1, 1),
            )
        )
        db.add(
            FeeEntry(
                organization_id=stranger_org.id,
                client_id=stranger.id,
                period=MONTH,
                amount=Decimal("900.00"),
                currency="RON",
            )
        )
        db.flush()

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()

        assert [row["clientId"] for row in payload["rows"]] == [str(alfa.id)]

    def test_an_unknown_client_is_not_found(self, as_admin: TestClient) -> None:
        response = as_admin.get(f"{URL}/clients/{uuid.uuid4()}")
        assert response.status_code == 404


class TestTheClientHistory:
    """Întrebarea de la telefon: „eu am plătit în martie"."""

    def test_it_lists_the_months_newest_first(self, as_admin: TestClient, alfa: Client) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, "2026-06")
        generate(as_admin, EARLIER)
        generate(as_admin, MONTH)

        rows = as_admin.get(f"{URL}/clients/{alfa.id}/history").json()

        assert [row["period"] for row in rows] == [MONTH, EARLIER, "2026-06"]

    def test_it_says_which_months_were_paid(self, as_admin: TestClient, alfa: Client) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, EARLIER)
        generate(as_admin, MONTH)
        as_admin.post(
            f"{URL}/payments",
            json={"clientId": str(alfa.id), "referenceMonth": EARLIER, "paidOn": "2026-07-20"},
        )

        rows = {
            row["period"]: row for row in as_admin.get(f"{URL}/clients/{alfa.id}/history").json()
        }

        assert rows[EARLIER]["paidOn"] == "2026-07-20"
        assert rows[EARLIER]["paidByName"] == "Ioana Marinescu"
        assert rows[MONTH]["isPaid"] is False

    def test_it_keeps_the_amount_of_each_month(self, as_admin: TestClient, alfa: Client) -> None:
        """Istoricul este locul unde se vede că registrul nu-și rescrie trecutul."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, EARLIER)
        set_fee(as_admin, alfa, "800.00")
        generate(as_admin, MONTH)

        rows = {
            row["period"]: row for row in as_admin.get(f"{URL}/clients/{alfa.id}/history").json()
        }

        assert rows[EARLIER]["amount"] == "500.00"
        assert rows[MONTH]["amount"] == "800.00"

    def test_a_client_from_another_organization_is_not_found(
        self, as_admin: TestClient, db: Session
    ) -> None:
        stranger_org = Organization(name="Alt Cabinet SRL")
        db.add(stranger_org)
        db.flush()
        stranger = make_client(db, stranger_org, "Străin SRL")

        assert as_admin.get(f"{URL}/clients/{stranger.id}/history").status_code == 404


class TestTheFileThatLeaves:
    """Un număr care nu poate ieși din aplicație se copiază de mână."""

    def test_it_has_the_romanian_excel_shape(self, as_admin: TestClient, alfa: Client) -> None:
        """Aceleași patru reguli ca la registrul de documente, verificate din nou.

        Un al doilea export scris de la zero le-ar fi respectat pe unele și nu pe
        toate, iar un fișier care se deschide „aproape bine" se repară de mână, de
        fiecare dată.
        """
        set_fee(as_admin, alfa, "1234.50")
        generate(as_admin)

        response = as_admin.get(f"{URL}/register.csv", params={"referenceMonth": MONTH})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert f"onorarii-{MONTH}.csv" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "no-store"

        text = response.content.decode("utf-8")
        assert text.startswith("﻿"), "fără BOM, Excel citește diacriticele greșit"
        assert ";" in text.splitlines()[0], "separatorul trebuie să fie punct și virgulă"
        assert "\r\n" in text
        # Virgulă la zecimale, fără separator de mii: altfel Excel românesc nu
        # adună coloana și nimeni nu observă până la primul total.
        assert "1234,50" in text
        assert "1234.50" not in text

    def test_it_lists_the_clients_without_a_fee_too(
        self, as_admin: TestClient, alfa: Client, beta: Client
    ) -> None:
        """Un fișier care i-ar tăcea ar arăta identic într-un cabinet pus la punct
        și în unul care a uitat jumătate din listă."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)

        text = as_admin.get(f"{URL}/register.csv", params={"referenceMonth": MONTH}).content.decode(
            "utf-8"
        )

        assert alfa.name in text
        assert beta.name in text

    def test_another_organizations_clients_are_not_in_it(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        stranger_org = Organization(name="Alt Cabinet SRL")
        db.add(stranger_org)
        db.flush()
        stranger = make_client(db, stranger_org, "Străin SRL")
        db.add(
            FeeEntry(
                organization_id=stranger_org.id,
                client_id=stranger.id,
                period=MONTH,
                amount=Decimal("900.00"),
                currency="RON",
            )
        )
        db.flush()

        text = as_admin.get(f"{URL}/register.csv", params={"referenceMonth": MONTH}).content.decode(
            "utf-8"
        )

        assert stranger.name not in text

    def test_an_accountant_cannot_download_it(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        user = make_user(db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT)
        api.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})

        response = api.get(f"{URL}/register.csv", params={"referenceMonth": MONTH})

        assert response.status_code == 403


def add_document(db: Session, client: Client, reference_month: str) -> None:
    """Un document al clientului, în luna cerută. Doar ce cere modelul."""
    db.add(
        Document(
            organization_id=client.organization_id,
            client_id=client.id,
            status=DocumentStatus.APPROVED,
            source=DocumentSource.UPLOAD,
            original_filename="factura.pdf",
            storage_key=f"{uuid.uuid4().hex}/original/source.pdf",
            mime_type="application/pdf",
            file_size=512,
            sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            received_at=datetime.now(UTC),
            reference_month=reference_month,
        )
    )
    db.flush()


class TestHowMuchWorkForHowMuchMoney:
    """Întrebarea pe care un cabinet și-o pune o dată pe an și n-o poate răspunde.

    Numărul de documente nu este o măsură a efortului, dar este singura pe care
    cabinetul o are — și pusă lângă onorariu spune cine este subevaluat.
    """

    def test_the_row_carries_the_document_count_of_the_month(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)
        for _ in range(3):
            add_document(db, alfa, MONTH)
        # O lună vecină nu are ce căuta în cifra lunii de pe ecran.
        add_document(db, alfa, EARLIER)

        payload = as_admin.get(URL, params={"referenceMonth": MONTH}).json()

        assert row_for(payload, alfa)["documents"] == 3

    def test_it_counts_the_same_as_the_report(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        """Două numărători ar fi ajuns, într-o zi, la două cifre diferite pentru
        aceeași lună — una pe raport și alta lângă bani."""
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin)
        for _ in range(2):
            add_document(db, alfa, MONTH)

        fees_row = row_for(as_admin.get(URL, params={"referenceMonth": MONTH}).json(), alfa)
        report = as_admin.get(
            "/api/v1/reports/summary", params={"fromMonth": MONTH, "toMonth": MONTH}
        ).json()

        by_client = {bucket["key"]: bucket["count"] for bucket in report["byClient"]}
        assert fees_row["documents"] == by_client[str(alfa.id)]

    def test_the_history_carries_the_count_of_each_month(
        self, as_admin: TestClient, db: Session, alfa: Client
    ) -> None:
        set_fee(as_admin, alfa, "500.00")
        generate(as_admin, EARLIER)
        generate(as_admin, MONTH)
        add_document(db, alfa, EARLIER)
        for _ in range(2):
            add_document(db, alfa, MONTH)

        rows = {
            row["period"]: row for row in as_admin.get(f"{URL}/clients/{alfa.id}/history").json()
        }

        assert rows[EARLIER]["documents"] == 1
        assert rows[MONTH]["documents"] == 2
