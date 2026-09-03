"""Limitarea încercărilor de autentificare (§43).

`RATE_LIMIT_PER_MINUTE` exista în configurare și în `.env.example` de la început,
dar nu îl citea niciun modul. O variabilă care promite o protecție inexistentă
este mai rea decât absența ei: cine o vede în configurare crede că este protejat.
Singura barieră reală era costul Argon2id — măsurat, ~200 ms pe încercare.

Contorul are limite reale, scrise în `app/core/rate_limit.py`: stă în proces, deci
mai multe procese de API înseamnă mai multe contoare. Testele de aici verifică ce
face, nu ce ne-am dori să facă.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.auth import LOGIN_LIMITERS
from app.core.rate_limit import WINDOW_SECONDS, FixedWindowLimiter
from app.core.security import hash_password
from app.domain.permissions import ROLE_PERMISSIONS, RoleCode
from app.models.organization import Organization
from app.models.user import Permission, Role, User
from tests.conftest import requires_db

PASSWORD = "parola-de-test-123"


class TestFixedWindow:
    """Contorul singur, fără HTTP.

    `blocked` și `record` sunt separate: prima se pune înaintea încercării, a doua
    după, și numai dacă a eșuat. O singură metodă care ar face amândouă ar fi
    trebuit să numere și reușitele.
    """

    def test_lets_through_exactly_the_limit_of_failures(self) -> None:
        limiter = FixedWindowLimiter(limit=3)
        for _ in range(3):
            assert limiter.blocked("a", now=0.0).allowed is True
            limiter.record("a", now=0.0)
        assert limiter.blocked("a", now=0.0).allowed is False

    def test_successes_never_count(self) -> None:
        """Cine ghicește parola este oricum înăuntru; contorul nu mai apără nimic.

        Prima variantă număra toate încercările, iar suita end-to-end a arătat
        imediat de ce nu merge: al unsprezecelea login **corect** dintr-un minut
        era refuzat.
        """
        limiter = FixedWindowLimiter(limit=2)
        for _ in range(100):
            assert limiter.blocked("a", now=0.0).allowed is True
        assert limiter.blocked("a", now=0.0).allowed is True

    def test_keys_do_not_interfere(self) -> None:
        """Un cabinet care greșește parola nu are voie să blocheze alt cabinet."""
        limiter = FixedWindowLimiter(limit=1)
        limiter.record("primul", now=0.0)
        assert limiter.blocked("primul", now=0.0).allowed is False
        assert limiter.blocked("al doilea", now=0.0).allowed is True

    def test_the_window_reopens(self) -> None:
        limiter = FixedWindowLimiter(limit=1)
        limiter.record("a", now=0.0)
        assert limiter.blocked("a", now=WINDOW_SECONDS - 1).allowed is False
        assert limiter.blocked("a", now=WINDOW_SECONDS + 1).allowed is True

    def test_says_how_long_to_wait(self) -> None:
        limiter = FixedWindowLimiter(limit=1)
        limiter.record("a", now=0.0)
        refused = limiter.blocked("a", now=10.0)
        assert refused.allowed is False
        # Fereastra s-a deschis la 0 și ține 60 de secunde; la secunda 10 mai sunt 50.
        assert 50 <= refused.retry_after <= 51

    def test_zero_means_no_limit_not_no_access(self) -> None:
        """O configurare greșită nu are voie să închidă autentificarea pentru toți."""
        limiter = FixedWindowLimiter(limit=0)
        for _ in range(100):
            limiter.record("a", now=0.0)
        assert limiter.blocked("a", now=0.0).allowed is True


@requires_db
class TestLoginRoute:
    """Ruta reală, prin HTTP.

    Pe `api`, nu pe `client`: primul este legat de sesiunea de test, al doilea ar
    interoga baza din configurare — adică baza de development a celui care rulează
    suita, care poate să nu fie nici măcar migrată.
    """

    #: Praguri mici pentru teste. Fiecare încercare costă un hash Argon2id — ~200 ms,
    #: deliberat — iar pragurile de producție (10 și 60) ar fi însemnat vreo 140 de
    #: autentificări reale, adică o jumătate de minut adăugat fiecărei rulări de CI.
    #: Ce se verifică este comportamentul la prag, nu valoarea pragului.
    ACCOUNT_LIMIT = 3
    ADDRESS_LIMIT = 5

    @pytest.fixture(autouse=True)
    def _small_limits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(LOGIN_LIMITERS["cont"], "limit", self.ACCOUNT_LIMIT)
        monkeypatch.setattr(LOGIN_LIMITERS["adresa"], "limit", self.ADDRESS_LIMIT)
        for limiter in LOGIN_LIMITERS.values():
            limiter.reset()

    def test_repeated_wrong_passwords_are_refused_with_a_retry_after(self, api: TestClient) -> None:
        limit = self.ACCOUNT_LIMIT
        payload = {"email": "tinta@contacrm.test", "password": "gresit"}

        # Până la prag: refuzate pentru parolă, nu pentru număr.
        for _ in range(limit):
            assert api.post("/api/v1/auth/login", json=payload).status_code == 401

        refused = api.post("/api/v1/auth/login", json=payload)
        assert refused.status_code == 429
        assert refused.json()["code"] == "RATE_LIMITED"
        # Fără `Retry-After`, clientul rămâne să ghicească cât să aștepte.
        assert int(refused.headers["Retry-After"]) > 0

    def test_another_account_is_not_locked_out(self, api: TestClient) -> None:
        """Contorul este per (adresă, cont). Altfel oricine ar putea bloca un contabil."""
        limit = self.ACCOUNT_LIMIT
        for _ in range(limit + 1):
            api.post("/api/v1/auth/login", json={"email": "tinta@contacrm.test", "password": "x"})

        other = api.post(
            "/api/v1/auth/login", json={"email": "altcineva@contacrm.test", "password": "x"}
        )
        assert other.status_code == 401, "un cont blocat nu are voie să blocheze altul"

    def test_a_whole_office_behind_one_address_is_still_limited(self, api: TestClient) -> None:
        """Praguri diferite, atacuri diferite: o parolă încercată pe multe conturi."""
        per_address = self.ADDRESS_LIMIT
        codes = [
            api.post(
                "/api/v1/auth/login", json={"email": f"cont{i}@contacrm.test", "password": "x"}
            ).status_code
            for i in range(per_address + 1)
        ]
        assert codes[-1] == 429
        assert codes.count(429) == 1, "abia ultima încercare trebuie refuzată"

    def test_a_correct_password_is_never_refused_for_being_frequent(
        self, api: TestClient, db: Session
    ) -> None:
        """Cazul pe care suita end-to-end l-a prins: un client care se autentifică des.

        Un cabinet cu o integrare, sau chiar suita de teste, poate trece de zece ori
        prin autentificare într-un minut. Cu parola corectă, asta nu este un atac.
        """
        email = _make_admin(db)
        limit = max(self.ACCOUNT_LIMIT, self.ADDRESS_LIMIT)
        codes = [
            api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
            for _ in range(limit + 5)
        ]
        assert set(codes) == {200}, f"o parolă corectă nu are voie să fie refuzată: {codes}"


def _make_admin(db: Session) -> str:
    """Un administrator cu o parolă cunoscută. Întoarce adresa lui."""
    organization = Organization(name="Cabinet pentru Limită SRL")
    db.add(organization)
    db.flush()

    permissions = {
        code: Permission(code=code.value) for role in ROLE_PERMISSIONS.values() for code in role
    }
    db.add_all(permissions.values())
    role = Role(
        code=RoleCode.ADMIN.value,
        name="Administrator",
        permissions=[permissions[code] for code in ROLE_PERMISSIONS[RoleCode.ADMIN]],
    )
    db.add(role)
    db.flush()

    email = "des@contacrm.test"
    db.add(
        User(
            organization_id=organization.id,
            email=email,
            full_name="Cine se autentifică des",
            password_hash=hash_password(PASSWORD),
            is_active=True,
            roles=[role],
        )
    )
    db.flush()
    return email
