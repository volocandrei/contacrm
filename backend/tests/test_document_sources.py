"""Pe unde intră documentele — ecranul care răspunde la prima întrebare.

**Ce apără testele de aici.** Un cabinet care se uită la aplicație întreabă, în
primele cinci minute, cum ajung documentele înăuntru. Răspunsul era împrăștiat pe
patru ecrane, deci cine nu găsea un drum presupunea că nu există.

Ecranul are voie să greșească într-un singur fel, și acela este cel mai scump:
**să spună că merge ceva ce nu merge.** Cineva ar aștepta luni de zile documente
care nu vin. De aceea aproape toate testele verifică starea și motivul, nu
prezența rândurilor:

1. **Starea se calculează din configurarea reală**, nu se declară.
2. **Când nu merge, se spune ce lipsește.** „Neconfigurat" fără motiv este o
   ghicitoare pe care omul o pierde.
3. **Ce nu există se scrie pe față**, cu `documents` nul — un zero ar fi arătat
   ca o integrare stricată.
4. **Nicio sursă de documente nu rămâne nenumărată**: dacă cineva adaugă mâine un
   drum nou, testul cade până când apare și pe ecran.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import config as core_config
from app.domain.enums import DocumentSource, SourceState
from app.domain.permissions import RoleCode
from app.models.anaf import AnafConnection
from app.models.client import Client
from app.models.document import DocumentType
from app.models.organization import Organization
from app.models.user import Role, User
from app.services.document_sources import EXPORTS, SourceCode
from tests.conftest import requires_db
from tests.test_periods_api import add_document, login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


@pytest.fixture
def admin_api(api: TestClient, db: Session, admin: User) -> TestClient:
    db.commit()
    login(api, admin.email)
    return api


def sources(api: TestClient) -> dict[str, dict]:
    body = api.get("/api/v1/integrations/sources").json()
    return {row["code"]: row for row in body["sources"]}


class TestItSaysWhatWorksNow:
    def test_the_two_drums_that_need_nothing_are_live(self, admin_api: TestClient) -> None:
        """Încărcarea și linkul de trimitere merg din prima zi.

        Sunt singurele care nu cer nici credențiale, nici o hotărâre. Dacă
        vreodată apar ca „de configurat", cabinetul nou ar crede că nu poate
        primi niciun document până nu conectează ceva.
        """
        rows = sources(admin_api)

        assert rows[SourceCode.UPLOAD.value]["state"] == SourceState.LIVE.value
        assert rows[SourceCode.PORTAL.value]["state"] == SourceState.LIVE.value
        assert rows[SourceCode.UPLOAD.value]["requirement"] is None

    def test_it_counts_the_documents_that_really_arrived(
        self,
        admin_api: TestClient,
        db: Session,
        org: Organization,
        client_row: Client,
        types: dict[str, DocumentType],
    ) -> None:
        """O integrare conectată care n-a adus nimic arată ca una care merge.

        Contorul este singurul lucru care le deosebește — iar el vine din
        documentele reale, nu din starea conexiunii.
        """
        before = sources(admin_api)[SourceCode.UPLOAD.value]["documents"]
        add_document(db, org, client_row, types["FACTURA_INTRARE"])
        db.commit()

        assert sources(admin_api)[SourceCode.UPLOAD.value]["documents"] == before + 1


class TestItSaysWhatIsMissing:
    def test_an_unconfigured_source_says_which_setting_is_missing(
        self, admin_api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """„Neconfigurat" fără motiv trimite omul să caute în locul greșit."""
        monkeypatch.setattr(core_config.settings, "ms_client_id", "")
        monkeypatch.setattr(core_config.settings, "ms_client_secret", "")

        row = sources(admin_api)[SourceCode.ONEDRIVE.value]

        assert row["state"] == SourceState.NEEDS_SETUP.value
        assert "MS_CLIENT_ID" in row["requirement"]

    def test_configured_but_not_connected_says_something_else(
        self, admin_api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Două cauze diferite nu au voie să dea același mesaj.

        Cheile lipsă se rezolvă în deployment; conectarea se rezolvă apăsând un
        buton. Un singur text pentru amândouă l-ar trimite pe administrator să
        caute variabile de mediu care sunt deja acolo.
        """
        monkeypatch.setattr(core_config.settings, "ms_client_id", "un-id")
        monkeypatch.setattr(core_config.settings, "ms_client_secret", "un-secret")
        monkeypatch.setattr("app.services.document_sources.encryption_available", lambda: True)

        row = sources(admin_api)[SourceCode.ONEDRIVE.value]

        assert row["state"] == SourceState.NEEDS_SETUP.value
        assert "MS_CLIENT_ID" not in row["requirement"]
        assert "conectat" in row["requirement"].lower()

    def test_efactura_explains_the_thing_nobody_guesses(
        self, admin_api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fără împuternicire, ANAF nu dă eroare — dă gol, ceea ce e mai rău.

        Este singurul refuz din aplicație care nu se vede ca un refuz, deci
        singurul care chiar trebuie scris pe ecran.
        """
        monkeypatch.setattr(core_config.settings, "anaf_client_id", "")
        monkeypatch.setattr(core_config.settings, "anaf_client_secret", "")

        row = sources(admin_api)[SourceCode.EFACTURA.value]

        assert row["state"] == SourceState.NEEDS_SETUP.value
        assert "ANAF_CLIENT_ID" in row["requirement"]

    def test_connected_but_nobody_empowered_says_the_form_number(
        self,
        admin_api: TestClient,
        db: Session,
        org: Organization,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cazul cel mai perfid: totul pare conectat, și nu vine nimic.

        Certificatul este pus, conexiunea există, ecranul de e-Factura arată
        verde — dar fără împuternicirea fiecărui client ANAF întoarce **gol**, nu
        eroare. Fără rândul ăsta, cabinetul așteaptă facturi luni de zile și
        crede că nu are clienți care emit.
        """
        monkeypatch.setattr(core_config.settings, "anaf_client_id", "un-id")
        monkeypatch.setattr(core_config.settings, "anaf_client_secret", "un-secret")
        db.add(
            AnafConnection(
                organization_id=org.id,
                environment="prod",
                refresh_token="criptat-in-realitate",
                connected_at=datetime.now(UTC),
                is_active=True,
            )
        )
        db.commit()

        row = sources(admin_api)[SourceCode.EFACTURA.value]

        assert row["state"] == SourceState.NEEDS_SETUP.value
        assert "150" in row["requirement"]


class TestItDoesNotPromise:
    def test_what_does_not_exist_says_so_and_counts_nothing(self, admin_api: TestClient) -> None:
        """Un zero ar fi arătat ca o integrare stricată, nu ca una inexistentă."""
        rows = sources(admin_api)

        for code in (SourceCode.EMAIL_IMAP, SourceCode.WHATSAPP, SourceCode.GOOGLE_DRIVE):
            row = rows[code.value]
            assert row["state"] == SourceState.PLANNED.value, code
            assert row["documents"] is None, code
            # Și ce ar fi nevoie ca să existe: unele cer cod, altele o hotărâre.
            assert row["requirement"], code
            # Fără drum: un buton care duce nicăieri este mai rău decât niciunul.
            assert row["path"] is None, code

    def test_whatsapp_does_not_pretend_to_receive(self, admin_api: TestClient) -> None:
        """Aplicația **deschide** o conversație WhatsApp; nu primește nimic pe ea.

        Distincția contează: butoanele de WhatsApp există peste tot în aplicație,
        deci cineva ar putea presupune că și intrarea documentelor merge pe acolo.
        """
        row = sources(admin_api)[SourceCode.WHATSAPP.value]

        assert row["state"] == SourceState.PLANNED.value
        assert "Meta" in row["requirement"]

    def test_saga_is_an_exit_not_an_entrance(self, admin_api: TestClient) -> None:
        """Cabinetul întreabă de Saga în aceeași propoziție cu „de unde iau facturile".

        Apare pe ecran, dar în lista de ieșiri — și cu motivul pentru care nu se
        poate scrie din presupuneri.
        """
        body = admin_api.get("/api/v1/integrations/sources").json()

        codes = {row["code"] for row in body["exports"]}
        assert "SAGA" in codes
        assert "SAGA" not in {row["code"] for row in body["sources"]}
        saga = next(row for row in body["exports"] if row["code"] == "SAGA")
        assert saga["state"] == SourceState.PLANNED.value
        assert "exemplu" in saga["requirement"]


class TestTheContract:
    def test_every_source_a_document_can_have_is_shown_somewhere(
        self, admin_api: TestClient
    ) -> None:
        """Dacă apare mâine un drum nou, testul cade până când apare și pe ecran.

        Fără el, un `DocumentSource` adăugat într-o zi ar aduce documente pe care
        ecranul nu le-ar număra nicăieri — iar totalul de pe „Surse documente" ar
        fi mai mic decât arhiva, tăcut.
        """
        body = admin_api.get("/api/v1/integrations/sources").json()
        shown = {row["code"] for row in body["sources"]}
        # `API` nu are ecran propriu: nu există nicio rută publică de creare de
        # documente, iar valoarea rămâne în enum pentru documentele vechi.
        expected = {
            DocumentSource.UPLOAD: SourceCode.UPLOAD,
            DocumentSource.PORTAL: SourceCode.PORTAL,
            DocumentSource.ONEDRIVE: SourceCode.ONEDRIVE,
            DocumentSource.EMAIL: SourceCode.EMAIL_MICROSOFT,
            DocumentSource.EFACTURA: SourceCode.EFACTURA,
            DocumentSource.WHATSAPP: SourceCode.WHATSAPP,
        }
        missing = {
            source
            for source in DocumentSource
            if source is not DocumentSource.API and source not in expected
        }
        assert not missing, f"surse fără rând pe ecran: {missing}"
        for code in expected.values():
            assert code.value in shown, code

    def test_the_count_matches_the_screen_header(self, admin_api: TestClient) -> None:
        body = admin_api.get("/api/v1/integrations/sources").json()

        assert body["live"] == sum(
            1 for row in body["sources"] if row["state"] == SourceState.LIVE.value
        )

    def test_every_export_that_works_has_somewhere_to_go(self, admin_api: TestClient) -> None:
        """Un export care merge, dar despre care nu scrie de unde se ia, nu se ia."""
        for item in EXPORTS:
            if item.state is SourceState.LIVE:
                assert item.path, item.code


class TestWhoMaySee:
    def test_it_is_the_administrator_screen(
        self, api: TestClient, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Enumeră ce lipsește din configurare — aceeași întrebare ca ecranul de setări.

        Ascunderea rândului din meniu rămâne ergonomie; refuzul îl dă serverul (§32).
        """
        accountant = make_user(
            db, org, roles, email="contabil@contacrm.test", role=RoleCode.ACCOUNTANT
        )
        db.commit()
        login(api, accountant.email)

        assert api.get("/api/v1/integrations/sources").status_code == 403
