"""Rapoartele (§84).

Testul care justifică existența acestui endpoint este
`test_nothing_is_left_out_above_the_page_limit`: până acum agregarea se făcea în
browser, peste primele 200 de documente, iar rezultatul era afișat ca și cum ar fi
acoperit tot. Pe setul de development ieșea corect, pentru că sunt mai puține de
200 — exact motivul pentru care greșeala nu se vedea.

Restul verifică ce se întâmplă la margini: ce se numără când lipsește ceva (lună,
client, tip) și ce se răspunde când nu s-a terminat încă nimic.
"""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentSource, DocumentStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services import document_register, report_export
from app.services.report_service import TOP_CLIENTS
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-123"
MONTH = "2026-08"
URL = "/api/v1/reports/summary"


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


@pytest.fixture
def other_org(db: Session) -> Organization:
    row = Organization(name="Alt Cabinet SRL")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def types(db: Session, org: Organization) -> dict[str, DocumentType]:
    created: dict[str, DocumentType] = {}
    for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = DocumentType(
            organization_id=org.id,
            code=seed.code,
            label=seed.label,
            sort_order=index,
            required_fields=list(seed.required_fields),
        )
        db.add(row)
        created[seed.code] = row
    db.flush()
    return created


@pytest.fixture
def client_row(db: Session, org: Organization) -> Client:
    row = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1")
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
def admin(db: Session, org: Organization, roles: dict[RoleCode, Role]) -> User:
    return make_user(db, org, roles, email="admin@contacrm.test", role=RoleCode.ADMIN)


def login(api: TestClient, email: str) -> None:
    response = api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> TestClient:
    """Sesiune de administrator pe clientul de test."""
    login(api, admin.email)
    return api


def add_document(
    db: Session,
    org: Organization,
    *,
    client: Client | None = None,
    document_type: DocumentType | None = None,
    reference_month: str | None = MONTH,
    status: DocumentStatus = DocumentStatus.APPROVED,
    is_duplicate: bool = False,
) -> Document:
    document_id = uuid.uuid4()
    prefix = f"organizations/{org.id}/documents/{document_id}"
    document = Document(
        id=document_id,
        organization_id=org.id,
        client_id=client.id if client else None,
        document_type_id=document_type.id if document_type else None,
        status=status,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=f"{prefix}/original/source.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        received_at=datetime.now(UTC),
        reference_month=reference_month,
        is_duplicate=is_duplicate,
    )
    if status is DocumentStatus.ARCHIVED:
        # Schema refuza un document arhivat fara nume standardizat si fara copie
        # (`ck_documents_archived_has_filename`). Testul respecta invariantul in
        # loc sa-l ocoleasca: un ARCHIVED inventat, incomplet, ar testa o stare
        # care nu poate exista in realitate.
        document.archived_at = datetime.now(UTC)
        document.stored_filename = "2026-08-14_Facturaintrare_AlfaConta_FCT1.pdf"
        document.archive_key = f"{prefix}/archive/document.pdf"
        document.archive_path = "/ARHIVA/2026/08/Alfa Conta SRL"
    db.add(document)
    db.flush()
    return document


def fetch(api: TestClient, **params: str) -> dict[str, Any]:
    response = api.get(URL, params=params)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def counts(buckets: list[dict[str, Any]]) -> dict[str | None, int]:
    return {bucket["key"]: bucket["count"] for bucket in buckets}


@pytest.mark.usefixtures("as_admin")
class TestCoverage:
    def test_nothing_is_left_out_above_the_page_limit(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Motivul pentru care raportul s-a mutat în backend.

        Interfața cerea primele 200 de documente și le număra acolo. Cu 250, un
        sfert din realitate lipsea din procentul afișat — fără niciun semn că
        lipsește.
        """
        for _ in range(250):
            add_document(db, org, client=client_row)

        assert fetch(api, **{})["total"] == 250

    def test_a_second_organization_is_invisible(
        self, api: TestClient, db: Session, org: Organization, other_org: Organization
    ) -> None:
        """§72 — agregarea nu are voie să vadă peste graniță."""
        add_document(db, org)
        for _ in range(5):
            add_document(db, other_org)

        assert fetch(api, **{})["total"] == 1


@pytest.mark.usefixtures("as_admin")
class TestSuccessRate:
    def test_unfinished_work_is_not_a_failure(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Nimic terminat înseamnă `null`, nu zero.

        Zero s-ar citi ca „totul a eșuat", ceea ce este altceva — și exact opusul
        adevărului când sistemul tocmai a primit primele fișiere.
        """
        add_document(db, org, status=DocumentStatus.RECEIVED)
        add_document(db, org, status=DocumentStatus.PROCESSING)

        payload = fetch(api, **{})
        assert payload["successRate"] is None
        assert payload["processed"] == 0
        assert payload["total"] == 2

    def test_documents_still_in_progress_do_not_lower_the_rate(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cineva care tocmai a încărcat un fișier nu strică statistica nimănui."""
        add_document(db, org, status=DocumentStatus.APPROVED)
        add_document(db, org, status=DocumentStatus.ARCHIVED)
        add_document(db, org, status=DocumentStatus.PROCESSING)

        payload = fetch(api, **{})
        assert payload["processed"] == 2
        assert payload["successRate"] == 1.0

    def test_errors_are_what_lowers_the_rate(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        for _ in range(3):
            add_document(db, org, status=DocumentStatus.APPROVED)
        add_document(db, org, status=DocumentStatus.ERROR)

        payload = fetch(api, **{})
        assert payload["failed"] == 1
        assert payload["successRate"] == 0.75


@pytest.mark.usefixtures("as_admin")
class TestWhatIsMissing:
    """Ce lipsește se numără; nu se sare peste."""

    def test_documents_without_a_month_get_their_own_bucket(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Un document fără lună contabilă este exact ce trebuie să vadă cineva."""
        add_document(db, org, reference_month=MONTH)
        add_document(db, org, reference_month=None)

        by_month = counts(fetch(api, **{})["byMonth"])
        assert by_month == {MONTH: 1, None: 1}

    def test_the_undated_bucket_comes_last(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Luna recentă prima, fără lună la coadă — ordinea cronologică rămâne."""
        add_document(db, org, reference_month="2026-06")
        add_document(db, org, reference_month=None)
        add_document(db, org, reference_month="2026-08")

        keys = [bucket["key"] for bucket in fetch(api, **{})["byMonth"]]
        assert keys == ["2026-08", "2026-06", None]

    def test_documents_without_a_client_get_their_own_bucket(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)
        add_document(db, org, client=None)

        by_client = counts(fetch(api, **{})["byClient"])
        assert by_client == {str(client_row.id): 1, None: 1}

    def test_the_absent_bucket_carries_no_label(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cum se scrie „client neidentificat" este treaba interfeței.

        Dacă serverul ar trimite și el formularea, ar exista două surse pentru
        același text și s-ar despărți la prima modificare.
        """
        add_document(db, org, client=None, document_type=None)

        payload = fetch(api, **{})
        assert payload["byClient"][0]["label"] is None
        assert payload["byType"][0]["label"] is None

    def test_statuses_carry_no_label_either(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """`status-badge.tsx` le traduce de mult; nu le traducem a doua oară."""
        add_document(db, org, status=DocumentStatus.APPROVED)

        bucket = fetch(api, **{})["byStatus"][0]
        assert bucket["key"] == DocumentStatus.APPROVED.value
        assert bucket["label"] is None

    def test_the_type_label_comes_from_the_database(
        self, api: TestClient, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Asta serverul chiar o știe — tipurile sunt administrabile (§6)."""
        add_document(db, org, document_type=types["FACTURA_INTRARE"])

        bucket = fetch(api, **{})["byType"][0]
        assert bucket["key"] == "FACTURA_INTRARE"
        assert bucket["label"] == types["FACTURA_INTRARE"].label


@pytest.mark.usefixtures("as_admin")
class TestFilters:
    def test_the_month_range_includes_both_ends(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        for month in ("2026-05", "2026-06", "2026-07", "2026-08"):
            add_document(db, org, reference_month=month)

        payload = fetch(api, fromMonth="2026-06", toMonth="2026-07")
        assert payload["total"] == 2
        assert counts(payload["byMonth"]) == {"2026-07": 1, "2026-06": 1}

    def test_a_month_range_excludes_documents_without_a_month(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Nu se poate spune despre un document fără lună că este într-un interval."""
        add_document(db, org, reference_month=MONTH)
        add_document(db, org, reference_month=None)

        assert fetch(api, fromMonth=MONTH, toMonth=MONTH)["total"] == 1

    def test_filtering_by_client(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)
        add_document(db, org, client=None)

        assert fetch(api, clientId=str(client_row.id))["total"] == 1

    def test_a_reversed_range_is_refused(self, api: TestClient) -> None:
        """Tăcut, ar întoarce zero — care se citește „nu aveți documente"."""
        response = api.get(URL, params={"fromMonth": "2026-08", "toMonth": "2026-06"})
        assert response.status_code == 422
        assert "fromMonth" in response.json()["details"]

    def test_a_malformed_month_is_refused(self, api: TestClient) -> None:
        assert api.get(URL, params={"fromMonth": "august"}).status_code == 422
        assert api.get(URL, params={"fromMonth": "2026-13"}).status_code == 422

    def test_the_filters_are_read_as_camel_case(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Trimise snake_case ar fi ignorate tăcut, iar raportul ar răspunde la
        altă întrebare decât cea pusă."""
        add_document(db, org, reference_month="2026-05")
        add_document(db, org, reference_month="2026-08")

        assert fetch(api, fromMonth="2026-08")["total"] == 1


@pytest.mark.usefixtures("as_admin")
class TestRanking:
    def test_the_client_ranking_is_capped_but_says_so(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Lista este scurtă; numărul real de clienți nu este ascuns."""
        for index in range(TOP_CLIENTS + 5):
            client = Client(organization_id=org.id, name=f"Client {index:02d}")
            db.add(client)
            db.flush()
            for _ in range(index + 1):
                add_document(db, org, client=client)

        payload = fetch(api, **{})
        assert len(payload["byClient"]) == TOP_CLIENTS
        assert payload["clientCount"] == TOP_CLIENTS + 5

    def test_the_ranking_is_ordered_by_count(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        few = Client(organization_id=org.id, name="Puține")
        many = Client(organization_id=org.id, name="Multe")
        db.add_all([few, many])
        db.flush()

        add_document(db, org, client=few)
        for _ in range(3):
            add_document(db, org, client=many)

        assert [b["label"] for b in fetch(api, **{})["byClient"]] == ["Multe", "Puține"]


class TestEmptiness:
    def test_no_documents_is_a_valid_report(self, as_admin: TestClient) -> None:
        """Un cabinet nou nu primește o eroare, ci un raport gol și onest."""
        api = as_admin

        payload = fetch(api, **{})
        assert payload["total"] == 0
        assert payload["successRate"] is None
        assert payload["byMonth"] == []
        assert payload["clientCount"] == 0


class TestAuthorization:
    def test_anonymous_gets_nothing(self, api: TestClient) -> None:
        assert api.get(URL).status_code == 401

    def test_a_viewer_may_count_what_it_may_read(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un raport este o numărătoare peste documente; permisiunea este aceeași."""
        viewer = make_user(db, org, roles, email="vizitator@contacrm.test", role=RoleCode.VIEWER)
        login(api, viewer.email)

        assert api.get(URL).status_code == 200


@pytest.mark.usefixtures("as_admin")
class TestTheExport:
    """Raportul, ca fișier.

    Numerele se vedeau pe ecran și nu puteau ieși din aplicație; un cabinet care
    trebuie să pună situația lunii într-un raport intern o retasta.

    Trei detalii par mărunte și fără ele fișierul nu se poate folosi în România:
    separatorul `;`, BOM-ul de la început și sfârșitul de linie CRLF. Fiecare are
    testul lui, pentru că fiecare, lipsă, produce un fișier care *se deschide* și
    arată prost — nu o eroare pe care s-o vadă cineva.
    """

    def _csv(self, api: TestClient, **params: str) -> str:
        response = api.get(f"{URL}.csv", params=params)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        return response.text

    def test_the_numbers_are_the_same_as_on_screen(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Două căi de calcul ar ajunge, într-o zi, la două numere diferite."""
        for _ in range(3):
            add_document(db, org, client=client_row, document_type=types["FACTURA_INTRARE"])

        on_screen = fetch(api)
        exported = self._csv(api)

        assert f"Documente în interval{report_export.DELIMITER}{on_screen['total']}" in exported

    def test_excel_in_romania_gets_columns_not_one_long_line(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Cu virgulă, Excel în setările românești pune totul într-o coloană."""
        add_document(db, org, client=client_row)

        assert report_export.DELIMITER == ";"
        assert ";" in self._csv(api)

    def test_the_file_starts_with_a_byte_order_mark(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Fără el, Excel citește UTF-8 ca ANSI și „Rată" devine „RatÄƒ"."""
        add_document(db, org, client=client_row)

        assert self._csv(api).startswith(report_export.BOM)

    def test_lines_end_the_way_windows_expects(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)

        assert report_export.LINE_ENDING in self._csv(api)

    def test_a_semicolon_in_a_client_name_does_not_break_the_columns(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """`csv.writer` scapă singur valorile; o concatenare de mână n-ar fi făcut-o."""
        awkward = Client(organization_id=org.id, name='Alfa; Beta "SRL"', tax_id="RO7788")
        db.add(awkward)
        db.flush()
        add_document(db, org, client=awkward)

        exported = self._csv(api)

        # Numele apare întreg, între ghilimele, nu rupt în două coloane.
        assert '"Alfa; Beta ""SRL"""' in exported

    def test_an_unfinished_report_exports_an_empty_rate_not_a_zero(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Zero s-ar citi ca „totul a eșuat"; gol înseamnă „nu s-a terminat nimic"."""
        add_document(db, org, client=client_row, status=DocumentStatus.PROCESSING)

        rate_line = next(line for line in self._csv(api).splitlines() if "Rată de succes" in line)
        assert rate_line.endswith(report_export.DELIMITER)

    def test_the_rate_uses_the_decimal_comma_excel_expects(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Se scria cu punct, deci Excel românesc o citea ca text, nu ca număr.

        Fișierul se deschidea, coloana arăta plauzibil, iar singurul semn era
        alinierea la stânga. Găsit scoțând convențiile de format într-un modul
        comun cu registrul: acolo întrebarea „cum se scrie un număr" se pune o
        singură dată, iar răspunsul de aici nu se potrivea.
        """
        add_document(db, org, client=client_row)
        add_document(db, org, client=client_row, status=DocumentStatus.ERROR)
        add_document(db, org, client=client_row, status=DocumentStatus.ERROR)

        rate_line = next(line for line in self._csv(api).splitlines() if "Rată de succes" in line)

        assert rate_line.endswith("0,3333")

    def test_the_filename_carries_the_interval(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Două exporturi succesive nu au voie să se suprascrie în „Descărcări"."""
        add_document(db, org, client=client_row)

        response = api.get(f"{URL}.csv", params={"fromMonth": "2026-08", "toMonth": "2026-08"})

        assert "2026-08_2026-08" in response.headers["content-disposition"]

    def test_a_reversed_interval_is_refused_here_too(self, api: TestClient) -> None:
        """Altfel exportul ar da tăcut un fișier gol, care se citește ca „nu am nimic"."""
        response = api.get(f"{URL}.csv", params={"fromMonth": "2026-09", "toMonth": "2026-08"})

        assert response.status_code == 422

    def test_the_export_is_not_cached_by_a_proxy(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        add_document(db, org, client=client_row)

        response = api.get(f"{URL}.csv")

        assert response.headers["cache-control"] == "no-store"

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        api.post("/api/v1/auth/logout")
        assert api.get(f"{URL}.csv").status_code == 401


REGISTER = "/api/v1/reports/register.csv"


def with_amounts(
    db: Session,
    document: Document,
    *,
    document_date: date | None = date(2026, 8, 14),
    subtotal: Decimal | None = Decimal("1000.00"),
    vat_amount: Decimal | None = Decimal("190.00"),
    total_amount: Decimal | None = Decimal("1190.00"),
) -> Document:
    """Un document cu ce s-a citit din el.

    Se setează pe obiectul deja creat, nu prin `add_document`: fabrica aceea este
    folosită de tot fișierul, iar parametri noi acolo ar fi complicat fiecare test
    care nu are nevoie de sume.
    """
    document.document_date = document_date
    document.series = "FCT"
    document.document_number = "1042"
    document.supplier_name = "Furnizor Test SRL"
    document.supplier_tax_id = "RO12345678"
    document.currency = "RON"
    document.subtotal = subtotal
    document.vat_amount = vat_amount
    document.total_amount = total_amount
    db.flush()
    return document


@pytest.mark.usefixtures("as_admin")
class TestTheRegister:
    """Registrul lunii: un rând pe document, cu tot ce s-a citit din el.

    `summary.csv` numără documente. Acesta le listează cu sumele lor, și este
    singura cale prin care datele extrase ies din aplicație — până acum se puteau
    doar citi de pe ecran și retasta în programul de contabilitate.
    """

    def _lines(self, api: TestClient, **params: str) -> list[str]:
        response = api.get(REGISTER, params=params)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        return response.text.lstrip(report_export.BOM).strip().splitlines()

    def _row(self, api: TestClient) -> list[str]:
        return self._lines(api)[1].split(report_export.DELIMITER)

    def test_what_was_read_from_the_document_ends_up_in_the_file(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """Motivul pentru care există endpointul."""
        with_amounts(
            db, add_document(db, org, client=client_row, document_type=types["FACTURA_INTRARE"])
        )

        lines = self._lines(api)

        assert len(lines) == 2
        row = lines[1].split(report_export.DELIMITER)
        assert row[0] == "Alfa Conta SRL"
        assert row[2] == "14.08.2026"
        assert row[5] == "FCT"
        assert row[6] == "1042"
        assert row[7] == "Furnizor Test SRL"
        assert row[8] == "RO12345678"

    def test_amounts_use_the_decimal_comma_excel_expects(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Cea mai perfidă dintre convenții.

        `1190.00` scris cu punct nu este un număr pentru Excel în setările
        românești: îl ia ca text, îl aliniază la stânga și nu îl adună. Fișierul
        pare bun până când cineva trage un total pe coloană și primește zero.
        """
        with_amounts(db, add_document(db, org, client=client_row))

        row = self._row(api)

        assert row[12] == "1000,00"
        assert row[13] == "190,00"
        assert row[14] == "1190,00"

    def test_an_amount_that_was_not_read_stays_empty_not_zero(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Într-un registru, „nu s-a citit" și „este zero" nu sunt același lucru.

        Al doilea se aprobă fără să se uite nimeni la el.
        """
        with_amounts(db, add_document(db, org, client=client_row), total_amount=None)

        assert self._row(api)[14] == ""

    def test_a_document_still_in_review_is_listed_with_its_state(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Un registru care ar conține doar aprobatele ar tăcea despre restul.

        Cine exportă o lună cu documente rămase în verificare ar primi mai puține
        rânduri decât are documente și n-ar avea de unde ști. Omisiunea tăcută
        dintr-un registru se descoperă la un control; un rând care scrie
        „Necesită verificare" se vede.
        """
        with_amounts(
            db,
            add_document(db, org, client=client_row, status=DocumentStatus.REVIEW_REQUIRED),
        )

        assert self._row(api)[15] == "Necesită verificare"

    def test_a_rejected_document_is_not_in_the_register(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Un document respins nu se înregistrează."""
        add_document(db, org, client=client_row, status=DocumentStatus.REJECTED)

        assert len(self._lines(api)) == 1

    def test_a_duplicate_is_not_recorded_a_second_time(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Exact greșeala pe care detecția duplicatelor o previne.

        Duplicatul arată spre originalul lui, fiindcă schema o cere
        (`ck_documents_duplicate_has_origin`). Un duplicat orfan ar testa o stare
        care nu poate exista — și ar trece pe lângă întrebarea reală: din două
        rânduri, câte ajung în registru.
        """
        original = with_amounts(db, add_document(db, org, client=client_row))
        # Marcat după inserare: constrângerea cere ca cele două câmpuri să ajungă
        # în baza de date împreună, iar fabrica scrie rândul înainte de a le avea.
        copy = add_document(db, org, client=client_row)
        copy.is_duplicate = True
        copy.duplicate_of_id = original.id
        db.flush()

        assert len(self._lines(api)) == 2

    def test_a_deleted_document_is_not_in_the_register(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Documentele nu se șterg fizic (§62), dar un șters nu se înregistrează.

        `soft_delete` nu are încă apelanți. Testul îl scrie direct, pentru că
        garanția trebuie să existe **înainte** de primul apelant — altfel se
        descoperă dintr-un fișier deja trimis mai departe.
        """
        document = with_amounts(db, add_document(db, org, client=client_row))
        document.deleted_at = datetime.now(UTC)
        db.flush()

        assert len(self._lines(api)) == 1

    def test_every_row_has_as_many_columns_as_the_header(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """O coloană adăugată la antet și uitată la rând mută toate valorile."""
        with_amounts(db, add_document(db, org, client=client_row))

        widths = {len(line.split(report_export.DELIMITER)) for line in self._lines(api)}

        assert widths == {len(document_register.HEADER)}

    def test_a_semicolon_in_a_client_name_does_not_break_the_columns(
        self, api: TestClient, db: Session, org: Organization
    ) -> None:
        """Separatorul este `;`; o denumire care îl conține trebuie citată."""
        odd = Client(organization_id=org.id, name="Alfa; Beta SRL", tax_id="RO2")
        db.add(odd)
        db.flush()
        with_amounts(db, add_document(db, org, client=odd))

        line = self._lines(api)[1]
        parsed = next(csv.reader([line], delimiter=report_export.DELIMITER))

        assert parsed[0] == "Alfa; Beta SRL"
        assert len(parsed) == len(document_register.HEADER)

    def test_another_organizations_documents_never_appear(
        self, api: TestClient, db: Session, other_org: Organization
    ) -> None:
        """Izolarea pe organizație stă prima și nu este opțională (§72)."""
        stranger = Client(organization_id=other_org.id, name="Terț SRL", tax_id="RO3")
        db.add(stranger)
        db.flush()
        with_amounts(db, add_document(db, other_org, client=stranger))

        assert len(self._lines(api)) == 1

    def test_the_filename_carries_the_month(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Două exporturi succesive nu au voie să se suprascrie în „Descărcări"."""
        add_document(db, org, client=client_row)

        response = api.get(REGISTER, params={"fromMonth": MONTH, "toMonth": MONTH})

        assert f"registru-documente-{MONTH}.csv" in response.headers["content-disposition"]

    def test_a_reversed_interval_is_refused_here_too(self, api: TestClient) -> None:
        """Un registru gol se citește ca „nu am documente", nu ca „ai greșit intervalul"."""
        response = api.get(REGISTER, params={"fromMonth": "2026-09", "toMonth": "2026-08"})

        assert response.status_code == 422

    def test_the_register_is_not_cached_by_a_proxy(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Sumele clienților nu au ce căuta în cache-ul unui proxy."""
        add_document(db, org, client=client_row)

        assert api.get(REGISTER).headers["cache-control"] == "no-store"

    def test_neither_storage_keys_nor_confidence_leak_into_the_file(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """§73: fișierul circulă pe email, iar o cale de stocare nu are ce căuta în el.

        Nici încrederea extracției: o probabilitate lângă o sumă nu ajută pe
        nimeni și sugerează că suma ar fi negociabilă.
        """
        document = with_amounts(db, add_document(db, org, client=client_row))
        document.ocr_confidence = 0.83
        document.ai_provider = "anthropic"
        db.flush()

        exported = api.get(REGISTER).text

        assert document.storage_key not in exported
        assert "0.83" not in exported
        assert "0,83" not in exported
        assert "anthropic" not in exported

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        api.post("/api/v1/auth/logout")

        assert api.get(REGISTER).status_code == 401
