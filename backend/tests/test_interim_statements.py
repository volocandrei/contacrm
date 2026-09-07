"""Situațiile financiare interimare, pentru dividende (§3, §4).

**De ce nu sunt „încă o declarație".** Toate celelalte din catalog se nasc din
calendar: luna se încheie, termenul curge. Situațiile interimare se nasc dintr-o
**hotărâre** — asociații vor să repartizeze dividende în cursul anului, iar pentru
asta trebuie întocmite situații financiare pe o perioadă aleasă de ei. Poate de
trei ori într-un an, poate niciodată.

**Ce s-ar fi întâmplat dacă erau trecute drept „anuale".** Ar fi apărut ca
restanță la fiecare sfârșit de an, la **toți** clienții — inclusiv la cei care nu
au distribuit nimic și nu aveau ce întocmi. O listă de restanțe false se închide o
dată și nu se mai deschide, iar odată cu ea și restanțele adevărate.

De aceea au o periodicitate proprie, `ON_DEMAND`: aplicația nu le cere singură. Le
înregistrează când cineva spune că s-au întocmit, cu perioada pe care o alege el.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ObligationFrequency
from app.domain.obligations import DEFAULT_OBLIGATIONS
from app.models.client import Client
from app.models.obligation import ClientObligation, ObligationFiling, ObligationType
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

INTERIM = "SITFIN_INTERIM"


class TestTheCatalogue:
    def test_the_forms_the_office_asked_for_are_there(self) -> None:
        """Lista cerută de cabinet, plus cele pe care le depune orice cabinet.

        Codurile sunt nume de formulare, nu interpretări ale legii; fiecare termen
        rămâne de confirmat de un contabil — vezi capul lui `app/domain/obligations.py`.
        """
        codes = {seed.code for seed in DEFAULT_OBLIGATIONS}

        for asked in ("D394", "D301", "D390", "SAFT", INTERIM):
            assert asked in codes, asked

    def test_the_interim_statements_have_no_calendar(self) -> None:
        seed = next(item for item in DEFAULT_OBLIGATIONS if item.code == INTERIM)

        assert seed.frequency is ObligationFrequency.ON_DEMAND

    def test_the_special_vat_return_is_not_a_variant_of_the_ordinary_one(self) -> None:
        """D301 îl depune cine **nu** este înregistrat normal în scopuri de TVA.

        Este pentru altcineva decât D300, nu o formă a lui — de aceea are rândul
        lui în catalog, iar un client îl poate avea fără să-l aibă pe celălalt.
        """
        codes = {seed.code for seed in DEFAULT_OBLIGATIONS}

        assert "D301" in codes and "D300" in codes


@pytest.fixture
def interim_type(db: Session, org: Organization) -> ObligationType:
    """Catalogul cabinetului, cu situațiile interimare în el."""
    seed = next(item for item in DEFAULT_OBLIGATIONS if item.code == INTERIM)
    row = ObligationType(
        organization_id=org.id,
        code=seed.code,
        label=seed.label,
        frequency=seed.frequency,
        months_after=seed.months_after,
        deadline_day=seed.deadline_day,
        sort_order=99,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def as_admin(api: TestClient, admin: User) -> None:
    login(api, admin.email)


@pytest.mark.usefixtures("as_admin")
class TestOnTheDeadlinesScreen:
    def test_it_never_appears_as_an_overdue_filing(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
        interim_type: ObligationType,
    ) -> None:
        """Cazul pentru care există periodicitatea proprie.

        Clientul are obligația configurată, a trecut un an întreg — și totuși
        nimic nu apare ca restanță, fiindcă nimeni nu a hotărât să distribuie
        dividende. Aplicația nu inventează o obligație care nu s-a născut.
        """
        db.add(
            ClientObligation(
                organization_id=client_row.organization_id,
                client_id=client_row.id,
                obligation_type_id=interim_type.id,
            )
        )
        db.flush()

        answer = api.get(
            "/api/v1/obligations", params={"since": "2026-01-01", "until": "2027-12-31"}
        )

        assert answer.status_code == 200, answer.text
        codes = {row["code"] for row in answer.json()}
        assert INTERIM not in codes

    def test_the_calendar_obligations_still_appear(
        self, api: TestClient, db: Session, client_row: Client, org: Organization
    ) -> None:
        """Contra-proba: fără ea, testul de mai sus ar trece și cu ecranul gol."""
        monthly = ObligationType(
            organization_id=org.id,
            code="D300",
            label="D300 — decont TVA",
            frequency=ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
        )
        db.add(monthly)
        db.flush()
        db.add(
            ClientObligation(
                organization_id=org.id, client_id=client_row.id, obligation_type_id=monthly.id
            )
        )
        db.flush()

        answer = api.get(
            "/api/v1/obligations", params={"since": "2026-01-01", "until": "2027-12-31"}
        )

        assert "D300" in {row["code"] for row in answer.json()}


@pytest.mark.usefixtures("as_admin")
class TestRecordingOne:
    def test_it_is_recorded_for_the_period_the_office_chooses(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
        interim_type: ObligationType,
        admin: User,
    ) -> None:
        """Trimestrul pentru care s-au întocmit, ales de om, nu de calendar.

        Aici se închide bucla: aplicația nu cere situațiile interimare, dar le
        **ține minte** — cu perioada, cu cine le-a depus și cu nota lui.
        """
        answer = api.post(
            "/api/v1/obligations/filings",
            json={
                "clientId": str(client_row.id),
                "obligationTypeId": str(interim_type.id),
                "period": "2026-09",
                "note": "Repartizare dividende interimare, trimestrul III",
            },
        )

        assert answer.status_code in (200, 201), answer.text
        filing = db.scalars(
            select(ObligationFiling).where(ObligationFiling.obligation_type_id == interim_type.id)
        ).one()
        assert filing.period == "2026-09"
        assert filing.filed_by == admin.id
        assert "dividende" in (filing.note or "")

    def test_two_different_periods_can_be_recorded_in_the_same_year(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
        interim_type: ObligationType,
    ) -> None:
        """Se pot repartiza dividende de mai multe ori într-un an.

        O obligație anuală nu ar fi permis-o: cheia de unicitate este
        (client, tip, perioadă), iar perioada ar fi fost mereu decembrie.
        """
        for period in ("2026-06", "2026-09"):
            answer = api.post(
                "/api/v1/obligations/filings",
                json={
                    "clientId": str(client_row.id),
                    "obligationTypeId": str(interim_type.id),
                    "period": period,
                },
            )
            assert answer.status_code in (200, 201), answer.text

        found = db.scalars(
            select(ObligationFiling).where(ObligationFiling.obligation_type_id == interim_type.id)
        ).all()
        assert {item.period for item in found} == {"2026-06", "2026-09"}

    def test_another_offices_client_cannot_be_used(
        self, api: TestClient, db: Session, interim_type: ObligationType
    ) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO909090")
        db.add(other)
        db.flush()
        foreign = Client(organization_id=other.id, name="Client Străin SRL", tax_id="RO808080")
        db.add(foreign)
        db.flush()

        answer = api.post(
            "/api/v1/obligations/filings",
            json={
                "clientId": str(foreign.id),
                "obligationTypeId": str(interim_type.id),
                "period": "2026-09",
            },
        )

        assert answer.status_code == 404


@pytest.mark.usefixtures("as_admin")
class TestSeeingItAfterwards:
    """Ce s-a înregistrat trebuie să se și vadă.

    Depunerile obișnuite se văd pe ecranul de termene, fiindcă acolo există un
    rând calculat pe care se așază bifa. Una fără calendar nu produce niciun
    rând — deci fără fișa clientului ar fi fost scrisă în evidență și invizibilă
    în aceeași clipă. Un lucru înregistrat pe care nimeni nu-l mai poate vedea
    se înregistrează a doua oară.
    """

    def test_it_appears_on_the_client_with_its_period_and_note(
        self,
        api: TestClient,
        client_row: Client,
        interim_type: ObligationType,
    ) -> None:
        api.post(
            "/api/v1/obligations/filings",
            json={
                "clientId": str(client_row.id),
                "obligationTypeId": str(interim_type.id),
                "period": "2026-09",
                "note": "Repartizare dividende interimare",
            },
        )

        answer = api.get(f"/api/v1/obligations/clients/{client_row.id}/filings")

        assert answer.status_code == 200, answer.text
        rows = answer.json()
        assert [row["code"] for row in rows] == [INTERIM]
        assert rows[0]["period"] == "2026-09"
        assert rows[0]["note"] == "Repartizare dividende interimare"
        assert rows[0]["frequency"] == "ON_DEMAND"

    def test_the_newest_period_is_first(
        self,
        api: TestClient,
        client_row: Client,
        interim_type: ObligationType,
    ) -> None:
        """Cine deschide fișa caută ce s-a întâmplat ultima oară, nu prima."""
        for period in ("2026-03", "2026-09", "2026-06"):
            api.post(
                "/api/v1/obligations/filings",
                json={
                    "clientId": str(client_row.id),
                    "obligationTypeId": str(interim_type.id),
                    "period": period,
                },
            )

        answer = api.get(f"/api/v1/obligations/clients/{client_row.id}/filings")

        assert [row["period"] for row in answer.json()] == ["2026-09", "2026-06", "2026-03"]

    def test_it_does_not_show_another_clients_filings(
        self,
        api: TestClient,
        db: Session,
        client_row: Client,
        org: Organization,
        interim_type: ObligationType,
    ) -> None:
        """Contra-proba pentru filtrarea pe client, în același cabinet.

        Fără ea, o listă care ar întoarce tot ce are cabinetul ar trece testele
        de mai sus — și ar arăta dividendele unui client pe fișa altuia.
        """
        neighbour = Client(organization_id=org.id, name="Vecin SRL", tax_id="RO717171")
        db.add(neighbour)
        db.flush()
        api.post(
            "/api/v1/obligations/filings",
            json={
                "clientId": str(neighbour.id),
                "obligationTypeId": str(interim_type.id),
                "period": "2026-09",
            },
        )

        answer = api.get(f"/api/v1/obligations/clients/{client_row.id}/filings")

        assert answer.json() == []

    def test_another_offices_client_does_not_exist(self, api: TestClient, db: Session) -> None:
        other = Organization(name="Alt Cabinet SRL", tax_id="RO606060")
        db.add(other)
        db.flush()
        foreign = Client(organization_id=other.id, name="Client Străin SRL", tax_id="RO505050")
        db.add(foreign)
        db.flush()

        answer = api.get(f"/api/v1/obligations/clients/{foreign.id}/filings")

        assert answer.status_code == 404


def test_the_interim_type_reaches_a_fresh_office(db: Session, org: Organization) -> None:
    """Un cabinet instalat azi îl are în catalog, fără să facă nimic.

    `sync-obligation-types` scrie catalogul la crearea primului cont; dacă
    situațiile interimare nu ar fi acolo, nimeni nu le-ar adăuga de mână.
    """
    from app.cli import sync_obligation_types

    created = sync_obligation_types(db, org)
    db.flush()

    assert created >= len(DEFAULT_OBLIGATIONS)
    codes = {
        row.code
        for row in db.scalars(
            select(ObligationType).where(ObligationType.organization_id == org.id)
        )
    }
    assert INTERIM in codes
    assert "D301" in codes
