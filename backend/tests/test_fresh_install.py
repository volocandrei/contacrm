"""Prima zi a unui cabinet: ce trebuie să existe pe o bază goală.

**De ce are nevoie de teste proprii.** Suita E2E pornește de la `seed-dev`:
clienți, așteptări, obligații și documente există deja. Un cabinet real pornește
de la nimic, iar drumul acela nu era acoperit de nimic — deși este exact drumul pe
care se decide dacă aplicația se adoptă sau se închide.

Verificat și manual, pe o instalare complet nouă (6 septembrie 2026): migrări de
la zero, `sync-roles`, admin, catalogul de tipuri și cel de declarații, primul
client, un profil aplicat, un document citit, o cerere compusă, registrul și
arhiva. Testele de aici apără **partea care se poate strica în tăcere**: ce trebuie
să fie în bază înainte ca cineva să deschidă ecranul.

Ce s-a mai văzut la proba manuală și nu se poate testa aici: `create-admin`
citește parola cu `getpass`, care pe Windows ia caracterele direct din consolă, nu
din stdin — deci prima instalare nu se poate scripta. Este o alegere deliberată,
scrisă în docstring-ul comenzii: o parolă dată ca argument ajunge în istoricul
shell-ului și în lista de procese.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import sync_document_types, sync_obligation_types
from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import ClientStatus
from app.domain.obligations import DEFAULT_OBLIGATIONS
from app.domain.periods import format_reference_month
from app.models.client import Client
from app.models.document import DocumentType
from app.models.obligation import ObligationType
from app.models.organization import Organization
from app.services.fees import FeeService
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def fresh(db: Session) -> Organization:
    """O organizație fără nimic în ea, ca după `create-admin`."""
    row = Organization(name="Cabinet Nou SRL")
    db.add(row)
    db.flush()
    return row


class TestWhatANewOfficeGets:
    def test_it_can_receive_documents_from_the_first_minute(
        self, db: Session, fresh: Organization
    ) -> None:
        """Un cabinet fără tipuri de document nu poate primi niciun fișier."""
        created = sync_document_types(db, fresh)
        db.flush()

        codes = {
            row.code
            for row in db.scalars(
                select(DocumentType).where(DocumentType.organization_id == fresh.id)
            )
        }
        assert created == len(DEFAULT_DOCUMENT_TYPES)
        assert codes == {seed.code for seed in DEFAULT_DOCUMENT_TYPES}

    def test_it_has_a_catalogue_of_declarations(self, db: Session, fresh: Organization) -> None:
        """Fără catalog, ecranul „Termene" nu are ce urmări și nici ce administra."""
        created = sync_obligation_types(db, fresh)
        db.flush()

        rows = list(
            db.scalars(select(ObligationType).where(ObligationType.organization_id == fresh.id))
        )
        assert created == len(DEFAULT_OBLIGATIONS)
        assert {row.code for row in rows} == {seed.code for seed in DEFAULT_OBLIGATIONS}
        # Fiecare declarație vine cu termenul ei: unul fără zi n-ar produce nimic.
        assert all(1 <= row.deadline_day <= 31 for row in rows)
        assert all(row.months_after >= 0 for row in rows)

    def test_running_the_installer_twice_changes_nothing(
        self, db: Session, fresh: Organization
    ) -> None:
        """O reinstalare, un deploy repetat, un `docker compose up` de două ori."""
        sync_document_types(db, fresh)
        sync_obligation_types(db, fresh)
        db.flush()

        assert sync_document_types(db, fresh) == 0
        assert sync_obligation_types(db, fresh) == 0

    def test_a_corrected_deadline_survives_the_next_deploy(
        self, db: Session, fresh: Organization
    ) -> None:
        """Cel mai important lucru dintre toate cele de aici.

        Termenele sunt ale cabinetului. Un cabinet care a corectat o zi pentru că
        știe altfel decât noi nu are voie să o vadă revenind la valoarea din cod
        după un deploy — și n-ar afla decât din amenda de luna următoare.
        """
        sync_obligation_types(db, fresh)
        db.flush()
        vat = db.scalars(
            select(ObligationType).where(
                ObligationType.organization_id == fresh.id, ObligationType.code == "D300"
            )
        ).one()
        vat.deadline_day = 15
        vat.months_after = 2
        vat.is_active = False
        db.flush()

        sync_obligation_types(db, fresh)
        db.flush()
        db.refresh(vat)

        assert vat.deadline_day == 15
        assert vat.months_after == 2
        assert vat.is_active is False

    def test_the_label_does_come_back_up_to_date(self, db: Session, fresh: Organization) -> None:
        """Eticheta este text, nu regulă: acolo versiunea din cod este cea bună."""
        sync_obligation_types(db, fresh)
        db.flush()
        vat = db.scalars(
            select(ObligationType).where(
                ObligationType.organization_id == fresh.id, ObligationType.code == "D300"
            )
        ).one()
        vat.label = "ceva scris greșit"
        db.flush()

        sync_obligation_types(db, fresh)
        db.flush()
        db.refresh(vat)

        expected = next(seed for seed in DEFAULT_OBLIGATIONS if seed.code == "D300").label
        assert vat.label == expected

    def test_two_offices_do_not_share_a_catalogue(self, db: Session, fresh: Organization) -> None:
        """§72. Un cabinet care schimbă un termen nu îl schimbă pentru altul."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        sync_obligation_types(db, fresh)
        sync_obligation_types(db, other)
        db.flush()

        mine = db.scalars(
            select(ObligationType).where(
                ObligationType.organization_id == fresh.id, ObligationType.code == "D300"
            )
        ).one()
        mine.deadline_day = 10
        db.flush()

        theirs = db.scalars(
            select(ObligationType).where(
                ObligationType.organization_id == other.id, ObligationType.code == "D300"
            )
        ).one()
        assert theirs.deadline_day != 10


class TestTheMoneyOnDayOne:
    """Ecranul de onorarii, pe un cabinet care tocmai a instalat aplicația.

    Greșeala pe care o apără este cea făcută o dată la termene: o listă de
    restanțe inventate pentru toate lunile din urmă, pe o instalare de azi. Acolo
    au fost 52 de rânduri roșii; aici ar fi fost sume.
    """

    def test_a_new_office_owes_nothing_to_nobody(self, db: Session, fresh: Organization) -> None:
        service = FeeService(db, fresh.id)

        assert service.month(format_reference_month(date.today())) == []
        assert service.arrears(format_reference_month(date.today())) == []

    def test_a_client_added_today_is_not_billed_for_last_year(
        self, db: Session, fresh: Organization
    ) -> None:
        """Clientul apare pe lunile de după ce a intrat în cabinet, nu înainte."""
        client = Client(
            organization_id=fresh.id,
            name="Prima Firmă SRL",
            tax_id="RO900001",
            status=ClientStatus.ACTIVE,
        )
        db.add(client)
        db.flush()
        service = FeeService(db, fresh.id)

        assert service.month("2024-03") == []
        # Pe luna în curs apare, fără sumă: cine n-are onorariu stabilit trebuie
        # văzut, nu ascuns.
        rows = service.month(format_reference_month(date.today()))
        assert [row.client_name for row in rows] == ["Prima Firmă SRL"]
        assert rows[0].configured is None
        assert rows[0].is_generated is False

    def test_generating_a_month_without_fees_creates_nothing(
        self, db: Session, fresh: Organization
    ) -> None:
        """Aplicația nu inventează o sumă pentru un client căruia nu i s-a pus una."""
        db.add(
            Client(
                organization_id=fresh.id,
                name="Prima Firmă SRL",
                tax_id="RO900001",
                status=ClientStatus.ACTIVE,
            )
        )
        db.flush()
        today = date.today()

        created = FeeService(db, fresh.id).generate(format_reference_month(today), today=today)

        assert created == 0
