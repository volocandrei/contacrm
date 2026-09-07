"""Lista de clienți, dintr-un fișier.

**De ce are nevoie de teste bune.** Este singura funcție din aplicație care
scrie două sute de rânduri dintr-o apăsare. O greșeală într-un formular se vede
și se corectează; o greșeală aici produce o bază în care nimeni nu mai poate
deosebi clienții buni de cei creați strâmb, iar curățarea cere exact munca pe
care importul o economisea.

De aceea testele sunt aproape toate despre **ce nu se întâmplă**:

1. **Previzualizarea nu scrie nimic.** Butonul are un pas înainte tocmai ca
   nimeni să nu descopere rezultatul după ce e prea târziu.
2. **Ce arată previzualizarea este ce se întâmplă.** Dacă cele două ar putea
   diferi, primul pas ar fi o minciună liniștitoare.
3. **Nu suprascrie un client existent.** Fișierul poate fi vechi de un an; ce a
   tastat un om în aplicație este mai proaspăt decât ce a exportat cineva.
4. **Același fișier importat de două ori nu dublează pe nimeni.**
5. **Un rând stricat nu oprește restul** — altfel un fișier de două sute de
   clienți cade la al treilea și nimeni nu-l mai încearcă.
6. **Fișierul scris de Excel românesc se citește** — `;`, diacritice, cp1250.
   Un import care refuză exact formatul pe care îl produce programul din care
   vine lista nu este un import.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus, ImportOutcome
from app.domain.permissions import RoleCode
from app.models.client import Client, Contact
from app.models.organization import Organization
from app.models.user import Role, User
from app.services.client_import import MAX_ROWS, TEMPLATE_HEADER
from tests.conftest import requires_db
from tests.test_periods_api import login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

HEADER = ";".join(TEMPLATE_HEADER)


def csv_file(*rows: str) -> str:
    """Un fișier ca cel salvat de Excel românesc: `;`, CRLF."""
    return "\r\n".join([HEADER, *rows])


def upload(api: TestClient, text: str | bytes, *, apply: bool = False):
    payload = text.encode("utf-8") if isinstance(text, str) else text
    return api.post(
        f"/api/v1/clients/import?apply={'true' if apply else 'false'}",
        files={"file": ("clienti.csv", io.BytesIO(payload), "text/csv")},
    )


def count_clients(db: Session, org: Organization) -> int:
    return (
        db.scalar(select(func.count()).select_from(Client).where(Client.organization_id == org.id))
        or 0
    )


@pytest.fixture
def admin_api(api: TestClient, db: Session, admin: User) -> TestClient:
    db.commit()
    login(api, admin.email)
    return api


# ── Ce nu face ───────────────────────────────────────────────────────────────


class TestItDoesNotWriteBehindYourBack:
    def test_the_preview_creates_nothing(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Butonul are un pas înainte tocmai ca rezultatul să nu fie o surpriză."""
        before = count_clients(db, org)

        body = upload(admin_api, csv_file("Alfa Prest SRL;RO14399840;;;;;;;")).json()

        assert body["dryRun"] is True
        assert body["created"] == 1
        assert count_clients(db, org) == before

    def test_what_the_preview_promised_is_what_happens(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Dacă cele două ar putea diferi, primul pas ar fi o minciună liniștitoare."""
        text = csv_file(
            "Alfa Prest SRL;RO14399840;;;;;;;",
            ";RO12345678;;;;;;;",  # date, dar fără denumire
            "Beta Impex SRL;;;;;;;;",
        )
        before = count_clients(db, org)
        preview = upload(admin_api, text).json()

        applied = upload(admin_api, text, apply=True).json()

        assert applied["dryRun"] is False
        assert (applied["created"], applied["invalid"]) == (preview["created"], preview["invalid"])
        assert count_clients(db, org) == before + preview["created"]

    def test_it_does_not_overwrite_a_client_that_already_exists(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Ce a tastat un om este mai proaspăt decât ce a exportat cineva acum un an."""
        existing = Client(organization_id=org.id, name="Numele bun SRL", tax_id="14399840")
        db.add(existing)
        db.commit()

        body = upload(
            admin_api,
            csv_file("Numele vechi din export SRL;RO 14.399.840;;Altă adresă;;;;;"),
            apply=True,
        ).json()

        db.refresh(existing)
        assert existing.name == "Numele bun SRL"
        assert body["existing"] == 1
        assert body["created"] == 0
        # Și spune de ce, în loc să tacă: altfel „am importat 40 din 200" nu se
        # poate explica.
        assert body["rows"][0]["outcome"] == ImportOutcome.EXISTING.value
        assert body["rows"][0]["note"]

    def test_the_same_file_twice_does_not_double_anyone(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cineva va apăsa de două ori. Nu trebuie să coste nimic."""
        text = csv_file("Alfa Prest SRL;RO14399840;;;;;;;")
        upload(admin_api, text, apply=True)
        after_first = count_clients(db, org)

        second = upload(admin_api, text, apply=True).json()

        assert second["created"] == 0
        assert second["existing"] == 1
        assert count_clients(db, org) == after_first

    def test_the_same_code_twice_in_one_file_creates_one_client(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Un export cu rânduri repetate este cazul obișnuit, nu unul exotic."""
        before = count_clients(db, org)

        body = upload(
            admin_api,
            csv_file("Alfa Prest SRL;RO14399840;;;;;;;", "Alfa Prest S.R.L.;14399840;;;;;;;"),
            apply=True,
        ).json()

        assert body["created"] == 1
        assert body["duplicates"] == 1
        assert count_clients(db, org) == before + 1

    def test_a_broken_row_does_not_stop_the_rest(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Un fișier de două sute de clienți care cade la al treilea nu se mai încearcă."""
        body = upload(
            admin_api,
            csv_file(
                "Alfa Prest SRL;RO14399840;;;;;;;",
                # Un rând cu date, dar fără denumire — cazul stricat. Un rând
                # numai din separatori este altceva: pe acelea le lasă Excel la
                # sfârșitul fișierului, iar ele se sar în tăcere.
                ";RO12345678;;Str. Fără Nume nr. 1;;;;;",
                "Beta Impex SRL;RO87654321;;;;;;;",
            ),
            apply=True,
        ).json()

        assert body["created"] == 2
        assert body["invalid"] == 1
        broken = next(row for row in body["rows"] if row["outcome"] == ImportOutcome.INVALID.value)
        # Numărul rândului, ca să-l poată găsi în Excel.
        assert broken["line"] == 3


# ── Ce face ──────────────────────────────────────────────────────────────────


class TestItReadsWhatPeopleActuallyHave:
    def test_it_reads_the_file_excel_writes_in_romanian(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """`;`, diacritice și pagina de cod veche — nu UTF-8, cum ar fi comod.

        „Salvează ca CSV" din Excel pe Windows românesc scrie cp1250 — pagina de
        cod central-europeană, singura în care există „ă". Un import
        care cere UTF-8 refuză exact fișierul pe care îl produce programul din
        care vine lista, și îl refuză cu un mesaj despre codificare pe care
        nimeni nu are cum să-l urmeze.
        """
        text = csv_file("Societatea Măgura Veche SRL;RO14399840;;Str. Măgurii nr. 2;;;;;")

        body = upload(admin_api, text.encode("cp1250"), apply=True).json()

        assert body["created"] == 1
        client = db.scalars(
            select(Client).where(Client.organization_id == org.id, Client.tax_id == "14399840")
        ).one()
        assert client.name == "Societatea Măgura Veche SRL"
        assert client.address == "Str. Măgurii nr. 2"

    def test_it_reads_a_file_written_with_commas_too(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Exportul făcut de un programator scrie `,`. Amândouă sunt fișiere reale."""
        text = "Denumire,CUI,Email\r\nAlfa Prest SRL,RO14399840,contact@alfa.test"

        body = upload(admin_api, text, apply=True).json()

        assert body["created"] == 1

    def test_the_code_is_stored_normalised(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """`RO 14.399.840` și `14399840` sunt același client.

        Scris altfel, documentul din e-Factura nu s-ar mai lega de firmă, iar
        cineva l-ar căuta cu mâna în fiecare lună.
        """
        upload(admin_api, csv_file("Alfa Prest SRL;RO 14.399.840;;;;;;;"), apply=True)

        assert db.scalars(
            select(Client).where(Client.organization_id == org.id, Client.tax_id == "14399840")
        ).one()

    def test_the_contact_comes_in_with_the_company(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Fără adresă, clientul nou nu poate primi nici solicitări, nici remindere.

        Diferența dintre o listă de nume și o agendă se face aici, la import: cine
        adaugă contactele pe urmă, unul câte unul, nu le adaugă niciodată.
        """
        upload(
            admin_api,
            csv_file(
                "Alfa Prest SRL;RO14399840;;;;Ion Popescu;ion@alfa.test;0722 111 222;0722 111 222"
            ),
            apply=True,
        )

        client = db.scalars(
            select(Client).where(Client.organization_id == org.id, Client.tax_id == "14399840")
        ).one()
        contact = db.scalars(select(Contact).where(Contact.client_id == client.id)).one()
        assert contact.full_name == "Ion Popescu"
        assert contact.email == "ion@alfa.test"
        assert contact.whatsapp_number == "0722 111 222"
        assert contact.is_primary is True

    def test_a_client_without_a_status_is_active(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Cine importă o listă importă clienții pe care îi are.

        Două sute de prospecți ar fi lăsat cabinetul fără nicio lună de urmărit
        și fără niciun termen — adică fără aplicație.
        """
        upload(admin_api, csv_file("Alfa Prest SRL;RO14399840;;;;;;;"), apply=True)

        client = db.scalars(
            select(Client).where(Client.organization_id == org.id, Client.tax_id == "14399840")
        ).one()
        assert client.status is ClientStatus.ACTIVE

    def test_the_status_can_be_written_in_romanian(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        upload(admin_api, csv_file("Alfa Prest SRL;RO14399840;;;Inactiv;;;;"), apply=True)

        client = db.scalars(
            select(Client).where(Client.organization_id == org.id, Client.tax_id == "14399840")
        ).one()
        assert client.status is ClientStatus.INACTIVE


# ── Ce semnalează ────────────────────────────────────────────────────────────


class TestItFlagsWithoutRefusing:
    def test_a_code_that_fails_the_checksum_still_comes_in_with_a_warning(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Nu orice cod care nu trece verificarea este fals.

        Sunt firme străine, sunt PFA-uri, sunt coduri vechi. Refuzul ar fi
        însemnat că aplicația știe mai bine decât omul cine sunt clienții lui —
        iar rândul refuzat s-ar fi tastat oricum, de mână, la fel de greșit.
        """
        body = upload(admin_api, csv_file("Alfa Prest SRL;RO14399841;;;;;;;"), apply=True).json()

        assert body["created"] == 1
        assert body["rows"][0]["outcome"] == ImportOutcome.NEW.value
        assert body["rows"][0]["warning"]

    def test_a_client_without_a_code_is_flagged_not_refused(self, admin_api: TestClient) -> None:
        """Fără CUI, documentele din e-Factura nu se leagă singure de client."""
        body = upload(admin_api, csv_file("Alfa Prest SRL;;;;;;;;")).json()

        assert body["rows"][0]["outcome"] == ImportOutcome.NEW.value
        assert "e-Factura" in body["rows"][0]["warning"]


# ── Cine poate ───────────────────────────────────────────────────────────────


class TestWhoMayImport:
    def test_the_accountant_may_not_create_two_hundred_clients(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Gardul este `clients:write`, ca la formularul de client.

        Contabilul are `documents:write` și aleargă după documente; cine schimbă
        lista de clienți a cabinetului este administratorul. Ascunderea butonului
        nu ar fi o măsură — refuzul îl dă serverul (§32).
        """
        accountant = make_user(
            db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT
        )
        db.commit()
        login(api, accountant.email)

        assert upload(api, csv_file("Alfa Prest SRL;RO14399840;;;;;;;")).status_code == 403

    def test_the_template_is_downloadable_and_matches_the_reader(
        self, admin_api: TestClient
    ) -> None:
        """Modelul trebuie să treacă prin propriul cititor.

        Un model pe care importul îl refuză este mai rău decât niciunul: prima
        încercare eșuează pe antet, iar a doua nu mai are loc.
        """
        model = admin_api.get("/api/v1/clients/import/template.csv")

        assert model.status_code == 200
        body = upload(admin_api, model.content).json()
        assert body["rows"] and body["rows"][0]["outcome"] == ImportOutcome.NEW.value


class TestTheLimits:
    def test_a_file_with_too_many_rows_is_refused_before_anything_is_written(
        self, admin_api: TestClient, db: Session, org: Organization
    ) -> None:
        """Limita ține cererea sub timpul maxim al oricărei platforme.

        Refuzul vine înainte de orice scriere: un import oprit la jumătate ar
        lăsa în bază o listă pe care nimeni n-ar ști unde s-a întrerupt.
        """
        before = count_clients(db, org)
        rows = [f"Firma {index} SRL;;;;;;;;" for index in range(MAX_ROWS + 1)]

        answer = upload(admin_api, csv_file(*rows), apply=True)

        assert answer.status_code == 422
        assert count_clients(db, org) == before

    def test_a_file_without_a_name_column_says_which_column_is_missing(
        self, admin_api: TestClient
    ) -> None:
        answer = upload(admin_api, "CUI;Adresă\r\nRO14399840;Str. Exemplu")

        assert answer.status_code == 422
        assert "denumire" in answer.text.lower()
