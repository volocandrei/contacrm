"""Ce parolă se acceptă, și ce se întâmplă când se schimbă (§1).

**De ce este primul lucru dintr-o rundă de producție.** Contul unui contabil
deschide documentele financiare ale tuturor clienților lui. Până acum aplicația
avea autentificare bună — Argon2id, contor pe eșecuri, familii de tokenuri cu
detecția refolosirii — și două goluri care se vedeau abia dacă întrebai cine
schimbă parola:

1. **Nimeni nu-și putea schimba propria parola.** Exista doar resetarea făcută de
   un administrator **altcuiva**. Pe o instalare proaspătă administratorul este
   unul singur, deci parola pusă la instalare nu mai putea fi schimbată din
   aplicație de nimeni — nici de el.
2. **O resetare nu închidea sesiunile.** Al doilea motiv, mai rar și mai grav,
   pentru care cineva cere o parolă nouă este că altcineva i-a căpătat-o pe cea
   veche. Acolo parola nouă nu rezolva nimic: tokenul de reîmprospătare furat mai
   trăia două săptămâni.

Testele de mai jos apără amândouă, plus regulile parolei.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import passwords
from app.domain.permissions import RoleCode
from app.models.audit import AuditLog
from app.models.organization import Organization
from app.models.user import RefreshToken, User
from tests.conftest import requires_db
from tests.test_crm_api import PASSWORD, login, make_user

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/auth/password"

#: Lungă, variată, fără nicio legătură cu numele sau adresa contului de test.
NEW_PASSWORD = "trei-mere-verzi-pe-pervaz"


class TestThePolicy:
    """Regulile, ca funcție pură. Fiecare are o pagubă concretă în spate."""

    def test_a_short_password_is_refused(self) -> None:
        assert passwords.problems("scurta1234")

    def test_twelve_identical_characters_are_not_a_password(self) -> None:
        """Regula de lungime singură acceptă `aaaaaaaaaaaa`. Nu apără nimic."""
        assert passwords.problems("a" * 12)
        assert passwords.problems("123412341234")

    def test_a_password_that_contains_the_account_name_is_refused(self) -> None:
        """Primul lucru pe care îl încearcă cineva care are lista de utilizatori.

        Iar lista de utilizatori se află din orice email trimis de cabinet.
        """
        assert passwords.problems(
            "ioana-marinescu-2026", email="ioana.marinescu@cabinet.ro", full_name="Ioana Marinescu"
        )
        assert passwords.problems(
            "parola-cabinet-buna", email="ioana.marinescu@cabinet.ro", full_name="Ioana Marinescu"
        )

    def test_a_short_name_fragment_does_not_poison_everything(self) -> None:
        """`Ion` are trei litere și apare în cuvinte întregi. Nu se caută."""
        assert not passwords.problems(
            "campionatul-de-iarna", email="ion@cabinet.ro", full_name="Ion Vasile"
        )

    def test_a_good_passphrase_passes(self) -> None:
        """Fără majusculă obligatorie, fără simbol obligatoriu. Vezi modulul."""
        assert not passwords.problems(
            NEW_PASSWORD, email="ioana@cabinet.ro", full_name="Ioana Marinescu"
        )

    def test_all_the_reasons_come_at_once(self) -> None:
        """Cine repară un motiv și primește următorul încearcă a treia oară degeaba."""
        found = passwords.problems("ioana", email="ioana@cabinet.ro", full_name="Ioana Marinescu")
        assert len(found) >= 2


@pytest.mark.usefixtures("roles")
class TestChangingYourOwnPassword:
    def test_the_only_admin_of_a_fresh_install_can_change_their_password(
        self, api: TestClient, admin: User
    ) -> None:
        """Rostul întreg al rutei.

        Resetarea din *Administrare → Utilizatori* o face un administrator
        altcuiva; la început administratorul este unul singur. Fără ruta asta,
        parola de la instalare rămânea pe viață.
        """
        login(api, admin.email)

        answer = api.post(URL, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})

        assert answer.status_code == 200, answer.text
        # Și chiar funcționează: noua parolă intră, cea veche nu.
        api.post("/api/v1/auth/logout")
        assert (
            api.post(
                "/api/v1/auth/login", json={"email": admin.email, "password": NEW_PASSWORD}
            ).status_code
            == 200
        )
        api.post("/api/v1/auth/logout")
        assert (
            api.post(
                "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
            ).status_code
            == 401
        )

    def test_without_the_current_password_nothing_changes(
        self, api: TestClient, admin: User
    ) -> None:
        """O filă lăsată deschisă în birou nu are voie să devină un cont furat."""
        login(api, admin.email)

        answer = api.post(
            URL, json={"currentPassword": "altceva-complet-gresit", "newPassword": NEW_PASSWORD}
        )

        assert answer.status_code == 401
        api.post("/api/v1/auth/logout")
        # Parola veche merge în continuare: nu s-a schimbat nimic.
        assert (
            api.post(
                "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
            ).status_code
            == 200
        )

    def test_a_weak_new_password_is_refused_with_all_the_reasons(
        self, api: TestClient, admin: User
    ) -> None:
        login(api, admin.email)

        answer = api.post(URL, json={"currentPassword": PASSWORD, "newPassword": "aaaaaaaaaaaaaa"})

        assert answer.status_code == 422
        assert answer.json()["details"]["newPassword"]

    def test_an_anonymous_request_cannot_change_anyones_password(self, api: TestClient) -> None:
        api.post("/api/v1/auth/logout")
        answer = api.post(URL, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})
        assert answer.status_code == 401

    def test_the_other_sessions_are_closed(self, api: TestClient, db: Session, admin: User) -> None:
        """Motivul obișnuit al schimbării este bănuiala că altcineva o are.

        Dacă sesiunile vechi rămân valabile, schimbarea nu a rezolvat nimic.
        """
        login(api, admin.email)
        before = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == admin.id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        assert before, "testul nu demonstrează nimic fără o sesiune deschisă"

        answer = api.post(URL, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})
        assert answer.status_code == 200, answer.text

        # `flush`, nu `expire_all`: în teste ruta împarte sesiunea cu testul și nu
        # comite (tranzacția se anulează la final), deci o expirare ar arunca
        # tocmai schimbarea care se verifică. Confirmarea înainte de răspuns are
        # testul ei, `test_commit_before_response.py`.
        db.flush()
        for token in before:
            assert token.revoked_at is not None, "o sesiune veche a rămas valabilă"

    def test_the_caller_stays_logged_in(self, api: TestClient, admin: User) -> None:
        """Altfel omul s-ar deconecta singur exact când face lucrul corect."""
        login(api, admin.email)

        api.post(URL, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})

        assert api.get("/api/v1/me").status_code == 200

    def test_the_journal_records_it_without_either_password(
        self, api: TestClient, db: Session, admin: User
    ) -> None:
        login(api, admin.email)

        api.post(URL, json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "USER_PASSWORD_CHANGED")).one()
        assert entry.user_id == admin.id
        assert PASSWORD not in (entry.detail or "")
        assert NEW_PASSWORD not in (entry.detail or "")


@pytest.mark.usefixtures("roles")
class TestResettingSomeoneElsesPassword:
    def test_the_reset_closes_the_colleagues_sessions(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        roles: dict[RoleCode, object],
    ) -> None:
        """Al doilea motiv al unei resetări este că altcineva a căpătat accesul.

        O parolă nouă nu rezolvă nimic cât timp tokenul furat mai trăiește două
        săptămâni.
        """
        colleague = make_user(db, org, roles, email="coleg@contacrm.test", role=RoleCode.OPERATOR)
        db.commit()

        # Colegul se autentifică: are o sesiune.
        login(api, colleague.email)
        opened = db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == colleague.id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        assert opened

        login(api, admin.email)
        answer = api.post(f"/api/v1/users/{colleague.id}/password", json={"password": NEW_PASSWORD})
        assert answer.status_code == 200, answer.text

        db.flush()
        for token in opened:
            assert token.revoked_at is not None, "sesiunea colegului a rămas deschisă"

    def test_a_weak_password_cannot_be_forced_on_a_colleague(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        admin: User,
        roles: dict[RoleCode, object],
    ) -> None:
        """Drumul de administrator nu are voie să producă parole mai slabe."""
        colleague = make_user(db, org, roles, email="coleg2@contacrm.test", role=RoleCode.OPERATOR)
        db.commit()
        login(api, admin.email)

        answer = api.post(
            f"/api/v1/users/{colleague.id}/password", json={"password": "bbbbbbbbbbbbbb"}
        )

        assert answer.status_code == 422


@pytest.mark.usefixtures("roles")
class TestSeeingYourOwnSessions:
    """Cine mai are o fereastră deschisă pe contul meu, și cum o închid (§45).

    Întrebarea nu avea până acum niciun răspuns în aplicație, iar ea se pune
    exact în ziua proastă: după un laptop lăsat deschis într-un birou, după o
    parolă tastată pe alt calculator, după un email dubios. Fără ecran, singurul
    remediu era schimbarea parolei — adică o măsură mai mare decât problema, pe
    care omul o amână.
    """

    URL = "/api/v1/auth/sessions"

    def test_my_own_session_is_listed_and_marked_as_mine(
        self, api: TestClient, admin: User
    ) -> None:
        login(api, admin.email)

        rows = api.get(self.URL).json()

        assert len(rows) == 1
        assert rows[0]["current"] is True

    def test_no_token_ever_appears_in_the_answer(self, api: TestClient, admin: User) -> None:
        """Un ecran care listează sesiuni nu are voie să livreze cheile lor."""
        login(api, admin.email)

        body = api.get(self.URL).text

        for word in ("token", "hash", "eyJ"):
            assert word not in body.lower(), body

    def test_i_only_see_my_own(
        self,
        api: TestClient,
        db: Session,
        org: Organization,
        roles: dict[RoleCode, object],
        admin: User,
    ) -> None:
        """Sesiunile unui coleg nu sunt treaba mea, nici dacă sunt administrator."""
        colleague = make_user(db, org, roles, email="coleg3@contacrm.test", role=RoleCode.OPERATOR)
        db.commit()
        login(api, colleague.email)
        login(api, admin.email)

        rows = api.get(self.URL).json()

        assert len(rows) == 1
        assert rows[0]["current"] is True

    def test_closing_the_others_keeps_mine(self, api: TestClient, db: Session, admin: User) -> None:
        """Altfel omul care face lucrul corect se deconectează singur."""
        # O sesiune „de pe alt calculator": aceleași credențiale, alt login.
        login(api, admin.email)
        first = api.get(self.URL).json()[0]["id"]
        login(api, admin.email)

        answer = api.post(f"{self.URL}/revoke-others")

        assert answer.status_code == 200, answer.text
        assert answer.json()["closed"] == 1
        db.flush()
        remaining = api.get(self.URL).json()
        assert len(remaining) == 1
        assert remaining[0]["id"] != first
        # Și cea rămasă este chiar a mea: cererea de mai sus a mers.
        assert api.get("/api/v1/me").status_code == 200
