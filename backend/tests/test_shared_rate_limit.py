"""Contorul de încercări trebuie să fie același pentru toate instanțele.

**Ce apără.** Contorul stătea în memoria procesului de API. Pe un server cu un
container asta funcționează, și `app/core/rate_limit.py` spune deschis unde nu:
„pe o platformă care pornește un proces per cerere nu limitează nimic".

Platforma de deploy este exact aceea. Mai rău, serverless-ul pornește instanțe
noi când crește traficul — adică fix ce produce cineva care încearcă parole una
după alta: cu cât apasă mai tare, cu atât se împarte contorul în mai multe
bucăți. Protecția slăbea singură, în clipa în care era nevoie de ea.

Testul care contează este primul: două obiecte limitator diferite, ca două
instanțe de API, trebuie să numere în același loc.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.rate_limit import WINDOW_SECONDS
from app.models.rate_limit import RateLimitWindow
from app.services import rate_limit as shared_rate_limit
from app.services.rate_limit import FORGET_AFTER_SECONDS, SharedWindowLimiter, forget_old
from tests.conftest import requires_db

pytestmark = requires_db


def age_the_window(db: Session, *, seconds: float) -> None:
    """Împinge fereastra în trecut, cu ceasul bazei.

    Nu cu o dată calculată în Python: vechimea se măsoară de bază, deci tot de
    acolo trebuie construită — altfel testul ar depinde de ceasul mașinii.
    """
    db.execute(
        sa.update(RateLimitWindow).values(
            window_started_at=sa.func.now() - sa.text(f"interval '{seconds} seconds'")
        )
    )
    db.flush()


class TestTwoInstancesCountTogether:
    def test_the_second_instance_sees_what_the_first_recorded(self, db: Session) -> None:
        """Testul pentru care există fișierul.

        Două obiecte limitator, ca două instanțe de API pornite de platformă.
        Cu contorul în proces, al doilea ar fi început de la zero — iar cine
        încearcă parole ar fi avut din nou tot bugetul, la fiecare instanță nouă.
        """
        first = SharedWindowLimiter(scope="proba", limit=3)
        second = SharedWindowLimiter(scope="proba", limit=3)

        for _ in range(3):
            first.record("acelasi-cont")

        assert not second.blocked("acelasi-cont").allowed

    def test_a_different_scope_is_a_different_counter(self, db: Session) -> None:
        """Contra-proba: fără ea, un singur contor ar bloca tot.

        Autentificarea și asistentul numără lucruri diferite; dacă ar împărți
        cheia, câteva parole greșite ar fi închis și asistentul.
        """
        SharedWindowLimiter(scope="unul", limit=1).record("cheie")

        assert SharedWindowLimiter(scope="altul", limit=1).blocked("cheie").allowed

    def test_a_different_key_is_a_different_counter(self, db: Session) -> None:
        """Altfel primul care greșește parola ar bloca tot cabinetul."""
        limiter = SharedWindowLimiter(scope="proba", limit=1)
        limiter.record("ana")

        assert limiter.blocked("bogdan").allowed


class TestTheWindow:
    def test_under_the_limit_it_lets_through(self, db: Session) -> None:
        limiter = SharedWindowLimiter(scope="proba", limit=3)

        limiter.record("cheie")
        limiter.record("cheie")

        assert limiter.blocked("cheie").allowed

    def test_at_the_limit_it_refuses_and_says_for_how_long(self, db: Session) -> None:
        """`Retry-After` fără număr nu ajută pe nimeni."""
        limiter = SharedWindowLimiter(scope="proba", limit=2)

        limiter.record("cheie")
        limiter.record("cheie")

        decision = limiter.blocked("cheie")
        assert not decision.allowed
        assert 0 < decision.retry_after <= WINDOW_SECONDS + 1

    def test_the_window_closes_by_itself(self, db: Session) -> None:
        """Un minut mai târziu, cine a greșit poate încerca din nou.

        Fără asta, prima greșeală de tastare ar fi ținut un contabil afară până
        când cineva ar fi șters un rând cu mâna.
        """
        limiter = SharedWindowLimiter(scope="proba", limit=1)
        limiter.record("cheie")
        assert not limiter.blocked("cheie").allowed

        age_the_window(db, seconds=WINDOW_SECONDS + 1)

        assert limiter.blocked("cheie").allowed

    def test_a_failure_after_the_window_starts_a_new_one(self, db: Session) -> None:
        """Contorul repornește de la unu, nu continuă de unde rămăsese.

        Altfel eșecurile s-ar aduna peste zile, iar pragul „pe minut" ar fi
        însemnat de fapt „vreodată".
        """
        limiter = SharedWindowLimiter(scope="proba", limit=2)
        limiter.record("cheie")
        limiter.record("cheie")
        age_the_window(db, seconds=WINDOW_SECONDS + 1)

        limiter.record("cheie")

        assert limiter.blocked("cheie").allowed
        assert db.scalar(sa.select(RateLimitWindow.hits)) == 1


class TestWhenItMustNotGetInTheWay:
    def test_a_limit_of_zero_means_no_limit(self, db: Session) -> None:
        """Zero înseamnă „fără limită", nu „blochează tot".

        O configurare greșită nu are voie să închidă autentificarea pentru toată
        lumea — asta ar transforma protecția într-o pană.
        """
        limiter = SharedWindowLimiter(scope="proba", limit=0)

        for _ in range(10):
            limiter.record("cheie")

        assert limiter.blocked("cheie").allowed
        assert db.scalar(sa.select(sa.func.count()).select_from(RateLimitWindow)) == 0


class TestHousekeeping:
    def test_old_windows_are_forgotten(self, db: Session) -> None:
        """Fără curățenie, tabelul ar crește cu un rând per adresă, la nesfârșit."""
        SharedWindowLimiter(scope="proba", limit=1).record("cheie")
        age_the_window(db, seconds=FORGET_AFTER_SECONDS + 1)

        assert forget_old(db) == 1
        assert db.scalar(sa.select(sa.func.count()).select_from(RateLimitWindow)) == 0

    def test_a_window_still_in_use_survives(self, db: Session) -> None:
        """Contra-proba: o curățenie prea lacomă ar șterge chiar contorul care apără."""
        limiter = SharedWindowLimiter(scope="proba", limit=1)
        limiter.record("cheie")

        assert forget_old(db) == 0
        assert not limiter.blocked("cheie").allowed


class TestItDoesNotRideOnTheRequestTransaction:
    """De ce contorul își deschide propria tranzacție.

    Un refuz la autentificare se ridică drept eroare de aplicație, iar
    `CommittingRoute` nu confirmă tranzacția când ruta ridică ceva: `get_db` o dă
    înapoi. Un eșec numărat în sesiunea cererii s-ar șterge odată cu ea — adică
    exact încercările care trebuie ținute minte ar dispărea, iar limita ar fi
    rămas o promisiune goală.

    În suită, `session_scope` este legat de sesiunea testului (vezi `conftest`),
    deci comportamentul de rollback nu se poate reproduce aici. Ce se poate fixa
    este contractul: `record` **cere o tranzacție**, nu primește una.
    """

    def test_record_opens_its_own_scope(self, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        opened = 0

        @contextmanager
        def counting_scope() -> Iterator[Session]:
            nonlocal opened
            opened += 1
            yield db
            db.flush()

        monkeypatch.setattr(shared_rate_limit, "session_scope", counting_scope)

        SharedWindowLimiter(scope="proba", limit=1).record("cheie")

        assert opened == 1
