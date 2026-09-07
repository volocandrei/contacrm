"""Registrul declarațiilor depuse, ca fișier (§3, §21).

**Golul.** Aplicația știe ce s-a depus, pentru cine și de către cine — și o ținea
numai pe ecran. Lista asta se cere ca fișier în trei situații concrete: la o
verificare internă la sfârșit de an, la predarea unui client către alt contabil,
și când clientul întreabă ce s-a depus pentru el. Până acum se compunea din
memorie.

**Ce apără testele de aici, în ordinea în care contează:**

1. declarațiile fără calendar intră în fișier — ele nu apar niciodată pe ecranul
   de termene, deci registrul este singurul loc unde se pot vedea;
2. intervalul se aplică perioadei declarate, nu zilei marcării;
3. registrul unui cabinet nu conține clienții altuia;
4. fișierul se deschide corect în Excel-ul românesc.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ObligationFrequency
from app.models.client import Client
from app.models.obligation import ObligationFiling, ObligationType
from app.models.organization import Organization
from app.models.user import User
from app.services import report_export
from tests.conftest import requires_db
from tests.test_reports_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_reports_api",)

URL = "/api/v1/reports/filings.csv"


def a_type(
    db: Session,
    org: Organization,
    *,
    code: str,
    label: str,
    frequency: ObligationFrequency = ObligationFrequency.MONTHLY,
) -> ObligationType:
    row = ObligationType(
        organization_id=org.id,
        code=code,
        label=label,
        frequency=frequency,
        months_after=1,
        deadline_day=25,
    )
    db.add(row)
    db.flush()
    return row


def a_filing(
    db: Session,
    org: Organization,
    *,
    client: Client,
    obligation_type: ObligationType,
    period: str,
    filed_by: uuid.UUID | None = None,
    note: str | None = None,
    filed_at: datetime | None = None,
) -> ObligationFiling:
    row = ObligationFiling(
        organization_id=org.id,
        client_id=client.id,
        obligation_type_id=obligation_type.id,
        period=period,
        filed_at=filed_at or datetime(2026, 9, 3, 9, 30, tzinfo=UTC),
        filed_by=filed_by,
        note=note,
    )
    db.add(row)
    db.flush()
    return row


def lines(api: TestClient, **params: str) -> list[str]:
    response = api.get(URL, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    return response.text.lstrip(report_export.BOM).strip().splitlines()


def cells(line: str) -> list[str]:
    return line.split(report_export.DELIMITER)


@pytest.mark.usefixtures("as_admin")
class TestWhatEndsUpInTheFile:
    def test_a_filing_is_written_with_its_client_period_and_author(
        self, api: TestClient, db: Session, org: Organization, client_row: Client, admin: User
    ) -> None:
        vat = a_type(db, org, code="D300", label="D300 — decont TVA")
        a_filing(
            db,
            org,
            client=client_row,
            obligation_type=vat,
            period="2026-08",
            filed_by=admin.id,
            note="depus prin SPV",
        )

        rows = lines(api)

        assert len(rows) == 2
        row = cells(rows[1])
        assert row[0] == "Alfa Conta SRL"
        assert row[2] == "D300"
        assert row[4] == "lunar"
        assert row[5] == "2026-08"
        assert row[6] == "03.09.2026"
        assert row[7] == admin.full_name
        assert row[8] == "depus prin SPV"

    def test_an_obligation_without_a_calendar_is_in_the_file(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Motivul cel mai important pentru care există registrul.

        Situațiile financiare interimare nu apar niciodată pe ecranul de termene:
        nu produc rânduri calculate, fiindcă nu se nasc din calendar
        (`docs/DECLARATIONS.md`). Un registru care le-ar sări ar fi singurul loc
        din aplicație unde s-ar fi putut vedea și nu s-ar vedea.
        """
        interim = a_type(
            db,
            org,
            code="SITFIN_INTERIM",
            label="Situații financiare interimare (dividende)",
            frequency=ObligationFrequency.ON_DEMAND,
        )
        a_filing(db, org, client=client_row, obligation_type=interim, period="2026-06")

        row = cells(lines(api)[1])

        assert row[2] == "SITFIN_INTERIM"
        assert row[4] == "la nevoie"

    def test_a_filing_survives_the_person_who_made_it(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Ce s-a depus rămâne depus și după ce omul pleacă din cabinet.

        Fără `outerjoin`, rândul ar fi dispărut din registru — nu ar fi apărut
        fără nume, ar fi lipsit cu totul.
        """
        vat = a_type(db, org, code="D300", label="D300 — decont TVA")
        a_filing(db, org, client=client_row, obligation_type=vat, period="2026-08", filed_by=None)

        rows = lines(api)

        assert len(rows) == 2
        assert cells(rows[1])[7] == ""

    def test_an_empty_register_still_has_its_header(self, api: TestClient) -> None:
        """Un fișier gol de tot nu se poate deosebi de un export care a eșuat."""
        rows = lines(api)

        assert len(rows) == 1
        assert cells(rows[0])[0] == "Client"


@pytest.mark.usefixtures("as_admin")
class TestTheInterval:
    def test_it_applies_to_the_period_declared_not_the_day_it_was_marked(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Cine cere anul 2026 întreabă ce s-a depus **pentru** 2026.

        Decontul lunii decembrie 2025 se marchează în ianuarie 2026. Filtrat după
        ziua marcării, ar fi intrat în registrul anului 2026 — și ar fi ieșit din
        cel al anului 2025, unde îi este locul.
        """
        vat = a_type(db, org, code="D300", label="D300 — decont TVA")
        a_filing(
            db,
            org,
            client=client_row,
            obligation_type=vat,
            period="2025-12",
            filed_at=datetime(2026, 1, 20, 10, 0, tzinfo=UTC),
        )

        assert len(lines(api, fromMonth="2026-01", toMonth="2026-12")) == 1
        assert len(lines(api, fromMonth="2025-01", toMonth="2025-12")) == 2

    def test_a_reversed_interval_is_refused_not_answered_with_nothing(
        self, api: TestClient
    ) -> None:
        """Zero rânduri s-ar citi ca lipsa depunerilor, nu ca un interval greșit."""
        answer = api.get(URL, params={"fromMonth": "2026-12", "toMonth": "2026-01"})

        assert answer.status_code == 422


@pytest.mark.usefixtures("as_admin")
class TestIsolation:
    def test_another_offices_filings_are_not_in_the_file(
        self, api: TestClient, db: Session, org: Organization, other_org: Organization
    ) -> None:
        theirs_client = Client(
            organization_id=other_org.id, name="Client Străin SRL", tax_id="RO404040"
        )
        db.add(theirs_client)
        theirs_type = a_type(db, other_org, code="D300", label="D300 — decont TVA")
        db.flush()
        a_filing(db, other_org, client=theirs_client, obligation_type=theirs_type, period="2026-08")

        assert len(lines(api)) == 1

    def test_a_deleted_client_is_not_listed(
        self, api: TestClient, db: Session, org: Organization, client_row: Client
    ) -> None:
        """Un client șters nu are ce căuta într-un registru exportat azi."""
        vat = a_type(db, org, code="D300", label="D300 — decont TVA")
        a_filing(db, org, client=client_row, obligation_type=vat, period="2026-08")
        client_row.deleted_at = datetime.now(UTC)
        db.flush()

        assert len(lines(api)) == 1


class TestTheFile:
    def test_it_opens_in_the_romanian_excel(
        self, api: TestClient, db: Session, org: Organization, client_row: Client, admin: User
    ) -> None:
        """Aceleași trei convenții ca la celelalte exporturi: BOM, `;`, CRLF."""
        login(api, admin.email)
        vat = a_type(db, org, code="D300", label="D300 — decont TVA")
        a_filing(db, org, client=client_row, obligation_type=vat, period="2026-08")

        raw = api.get(URL).text

        assert raw.startswith(report_export.BOM)
        assert report_export.DELIMITER in raw
        assert "\r\n" in raw

    def test_the_filename_carries_the_interval(self, api: TestClient, admin: User) -> None:
        """Două exporturi succesive nu au voie să se suprascrie în Descărcări."""
        login(api, admin.email)

        answer = api.get(URL, params={"fromMonth": "2026-01", "toMonth": "2026-08"})

        assert "registru-declaratii-2026-01_2026-08.csv" in answer.headers["content-disposition"]

    def test_an_anonymous_request_is_refused(self, api: TestClient) -> None:
        api.post("/api/v1/auth/logout")

        assert api.get(URL).status_code == 401
