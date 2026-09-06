"""Rezumatul zilei, fără să plece nimic nicăieri.

Ce apără testele, în ordinea importanței:

1. **Nu se trimite când nu e nimic de spus.** Un rezumat care scrie „nimic" în
   fiecare dimineață antrenează pe toată lumea să nu-l mai deschidă — inclusiv în
   ziua în care are ceva înăuntru.
2. **Cifrele sunt cele de pe ecran.** Un rezumat care contrazice panoul face
   inutile amândouă.
3. **Merge la cine face munca**, nu la cine are voie să se uite.
4. **Oprit implicit.** Nimic nu pleacă dintr-o instalare pe care nimeni n-a
   configurat-o.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import ObligationFrequency
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, RoleCode
from app.models.client import Client
from app.models.obligation import ClientObligation, ObligationType
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from app.services.daily_digest import DailyDigestService, Digest, compose
from app.services.mail import EmailError, EmailMessage
from tests.conftest import requires_db

pytestmark = requires_db

TODAY = date(2026, 9, 6)


class Collecting:
    """Providerul de email, înlocuit cu unul care reține."""

    name = "test"

    def __init__(self, failing: set[str] | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.failing = failing or set()

    def send(self, message: EmailMessage) -> None:
        if message.to in self.failing:
            raise EmailError("serverul a refuzat")
        self.sent.append(message)


class TestTheTextItself:
    """Compunerea nu are nevoie de bază de date."""

    def test_only_the_numbers_that_are_not_zero_get_a_line(self) -> None:
        """Un rând care scrie „0 documente de verificat" ocupă un rând și nu spune nimic."""
        text = compose(
            Digest(overdue=0, due_soon=2, to_review=0, unmatched=0, not_asked=0, silent=0),
            organization_name="Cabinet Demo SRL",
            today=TODAY,
        )

        assert "2 termene" in text
        assert "de verificat" not in text
        assert "0 " not in text

    def test_the_overdue_line_comes_first(self) -> None:
        """Sunt singurele care costă bani, iar la client, nu la cabinet."""
        text = compose(
            Digest(overdue=1, due_soon=1, to_review=1, unmatched=1, not_asked=1, silent=1),
            organization_name="Cabinet Demo SRL",
            today=TODAY,
        )

        bullets = [line for line in text.splitlines() if line.startswith("•")]
        assert "nedepusă" in bullets[0]

    def test_it_is_signed_by_the_office_not_by_the_application(self) -> None:
        text = compose(
            Digest(overdue=1, due_soon=0, to_review=0, unmatched=0, not_asked=0, silent=0),
            organization_name="Cabinet Demo SRL",
            today=TODAY,
        )

        assert text.rstrip().endswith("Cabinet Demo SRL")
        assert "ContaCRM" not in text

    def test_one_and_many_are_written_differently(self) -> None:
        one = compose(
            Digest(overdue=1, due_soon=0, to_review=0, unmatched=0, not_asked=0, silent=0),
            organization_name="X",
            today=TODAY,
        )
        many = compose(
            Digest(overdue=3, due_soon=0, to_review=0, unmatched=0, not_asked=0, silent=0),
            organization_name="X",
            today=TODAY,
        )

        assert "1 declarație nedepusă" in one
        assert "3 declarații nedepuse" in many


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


def make_user(
    db: Session, org: Organization, roles: dict[RoleCode, Role], email: str, role: RoleCode
) -> User:
    from app.core.security import hash_password

    user = User(
        organization_id=org.id,
        email=email,
        full_name="Cineva",
        password_hash=hash_password("parola-de-test-123"),
        roles=[roles[role]],
    )
    db.add(user)
    db.flush()
    return user


def overdue_obligation(db: Session, org: Organization) -> None:
    """Un client cu o declarație al cărei termen a trecut."""
    client = Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1")
    obligation = ObligationType(
        organization_id=org.id,
        code="D300",
        label="D300",
        frequency=ObligationFrequency.MONTHLY,
        months_after=1,
        deadline_day=25,
    )
    db.add_all([client, obligation])
    db.flush()
    db.add(
        ClientObligation(
            organization_id=org.id,
            client_id=client.id,
            obligation_type_id=obligation.id,
            # Configurat demult: altfel aplicația nu produce termene trecute.
            created_at=datetime.now(UTC) - timedelta(days=200),
        )
    )
    db.flush()


class TestWhenItGoesOut:
    def test_nothing_leaves_when_there_is_nothing_to_say(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Tăcerea este ea însăși informația."""
        make_user(db, org, roles, "contabil@contacrm.test", RoleCode.ACCOUNTANT)
        mailer = Collecting()

        sent = DailyDigestService(db, org.id).send(mailer, today=TODAY)

        assert sent == 0
        assert mailer.sent == []

    def test_it_goes_to_the_people_who_do_the_work(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un vizitator nu are ce face cu lista."""
        overdue_obligation(db, org)
        make_user(db, org, roles, "contabil@contacrm.test", RoleCode.ACCOUNTANT)
        make_user(db, org, roles, "vizitator@contacrm.test", RoleCode.VIEWER)
        mailer = Collecting()

        DailyDigestService(db, org.id).send(mailer, today=TODAY)

        assert {message.to for message in mailer.sent} == {"contabil@contacrm.test"}

    def test_a_deactivated_colleague_is_left_out(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        overdue_obligation(db, org)
        gone = make_user(db, org, roles, "plecat@contacrm.test", RoleCode.ACCOUNTANT)
        gone.is_active = False
        db.flush()
        mailer = Collecting()

        assert DailyDigestService(db, org.id).send(mailer, today=TODAY) == 0

    def test_one_refused_address_does_not_silence_the_rest(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un server de mail care refuză o adresă nu este un motiv ca restul
        cabinetului să nu afle ce are de făcut."""
        overdue_obligation(db, org)
        make_user(db, org, roles, "unu@contacrm.test", RoleCode.ACCOUNTANT)
        make_user(db, org, roles, "doi@contacrm.test", RoleCode.ADMIN)
        mailer = Collecting(failing={"unu@contacrm.test"})

        sent = DailyDigestService(db, org.id).send(mailer, today=TODAY)

        assert sent == 1
        assert [message.to for message in mailer.sent] == ["doi@contacrm.test"]

    def test_another_organizations_numbers_never_leak_in(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """§72: izolarea stă prima și nu este opțională."""
        stranger = Organization(name="Alt Cabinet SRL")
        db.add(stranger)
        db.flush()
        overdue_obligation(db, stranger)
        make_user(db, org, roles, "contabil@contacrm.test", RoleCode.ACCOUNTANT)
        mailer = Collecting()

        assert DailyDigestService(db, org.id).send(mailer, today=TODAY) == 0

    def test_the_numbers_are_the_ones_from_the_screen(
        self, db: Session, org: Organization, roles: dict[RoleCode, Role]
    ) -> None:
        """Un rezumat care contrazice panoul face inutile amândouă."""
        overdue_obligation(db, org)
        service = DailyDigestService(db, org.id)

        digest = service.build(TODAY)
        from app.services.obligations import ObligationService

        rows = ObligationService(db, org.id).upcoming(
            since=TODAY - timedelta(days=120), until=TODAY
        )
        assert digest.overdue == sum(1 for row in rows if row.is_overdue(TODAY))


class TestTheRoute:
    URL = "/api/v1/internal/daily-digest"

    def test_it_is_invisible_without_the_secret(self, api) -> None:  # type: ignore[no-untyped-def]
        """Același răspuns pentru «secret greșit» și «secret neconfigurat»."""
        assert api.get(self.URL).status_code == 404

    def test_it_does_nothing_while_the_switch_is_off(
        self, api, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        """Nimic nu pleacă dintr-o instalare pe care nimeni n-a configurat-o."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "cron_secret", "un-secret-de-test")
        monkeypatch.setattr(settings, "daily_digest_enabled", False)

        response = api.get(self.URL, headers={"Authorization": "Bearer un-secret-de-test"})

        assert response.status_code == 200
        assert response.json() == {"organizations": 0, "sent": 0}
