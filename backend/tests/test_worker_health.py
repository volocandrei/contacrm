"""Semnul de viață al workerului, și alarma care depinde de el (§8, §9, §10).

**Blocantul pe care îl închide.** Până acum, un worker mort nu se vedea nicăieri.
Documentele intrau, rămâneau în coadă, iar ecranul nu arăta nicio eroare — fiindcă
nu era niciuna. Se descoperea a doua zi, la o sută de documente neprocesate.

**Ce apără testele de aici, în ordinea în care greșeala costă:**

1. un worker care nu a raportat niciodată **nu** este sănătos — altfel o
   instalare fără worker ar tăcea până la primul document;
2. un worker care a raportat demult **nu** este sănătos, oricât ar fi de viu
   procesul lui;
3. `/health/workers` răspunde **503**, ca un monitor extern să poată suna un om;
4. `/health/ready` **nu** cade odată cu workerul — altfel load balancerul ar
   scoate din rotație toate instanțele de API, transformând o problemă de
   procesare într-o cădere totală, exact când cabinetul are nevoie să vadă coada.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.v1 import health as health_routes
from app.models.worker import DEFAULT_WORKER, WorkerHeartbeat
from app.services import worker_health
from tests.conftest import requires_db

pytestmark = requires_db

READY = "/api/v1/health/ready"
WORKERS = "/api/v1/health/workers"


def age_the_heartbeat(db: Session, *, seconds: int) -> None:
    """Împinge ultimul bătut în trecut, cu ceasul bazei.

    `now() - interval`, nu o dată calculată în Python: vechimea se măsoară de
    bază, deci tot de acolo trebuie construită, altfel testul ar depinde de
    ceasul mașinii care rulează suita.
    """
    db.execute(
        sa.update(WorkerHeartbeat)
        .where(WorkerHeartbeat.name == DEFAULT_WORKER)
        .values(beat_at=sa.func.now() - sa.text(f"interval '{seconds} seconds'"))
    )
    db.flush()


class TestTheHeartbeatItself:
    def test_a_worker_that_never_reported_is_not_healthy(self, db: Session) -> None:
        """Cazul instalării în care workerul nu a fost pornit deloc.

        Tratat ca „necunoscut", ar fi tăcut până la primul document — adică până
        când conta. Este exact starea pe care trebuie s-o vadă cineva în ziua
        pornirii, nu peste o săptămână.
        """
        state = worker_health.status(db)

        assert state.beat_at is None
        assert state.age_seconds is None
        assert not state.is_fresh
        assert "niciodată" in state.describe()

    def test_beating_makes_it_healthy(self, db: Session) -> None:
        worker_health.beat(db)
        db.flush()

        state = worker_health.status(db)

        assert state.is_fresh
        assert state.age_seconds is not None and state.age_seconds < 5
        assert state.hostname
        assert state.pid

    def test_beating_twice_does_not_add_a_second_row(self, db: Session) -> None:
        """Un rând pe worker, actualizat — nu un jurnal care crește la nesfârșit."""
        worker_health.beat(db)
        worker_health.beat(db)
        db.flush()

        assert db.query(WorkerHeartbeat).count() == 1

    def test_an_old_heartbeat_is_stale(self, db: Session) -> None:
        """Motivul întregului mecanism.

        Un proces blocat într-un apel de rețea care nu se mai întoarce este viu
        pentru sistemul de operare și mort pentru cabinet.
        """
        worker_health.beat(db)
        db.flush()
        age_the_heartbeat(db, seconds=worker_health.settings.worker_heartbeat_timeout_seconds + 30)

        state = worker_health.status(db)

        assert not state.is_fresh
        assert state.age_seconds is not None
        assert state.age_seconds > state.timeout_seconds
        assert "coadă" in state.describe()

    def test_just_under_the_threshold_is_still_healthy(self, db: Session) -> None:
        """Contra-proba: fără ea, un prag de zero ar fi trecut toate testele de sus."""
        worker_health.beat(db)
        db.flush()
        age_the_heartbeat(
            db, seconds=max(1, worker_health.settings.worker_heartbeat_timeout_seconds - 30)
        )

        assert worker_health.status(db).is_fresh


@pytest.fixture
def api_public(api: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Rutele de sănătate nu cer sesiune: le citește un monitor, care nu are cont.

    **De ce se leagă `session_scope` de sesiunea testului.** Ruta își deschide
    singură sesiunea, în loc s-o primească prin `Depends`, și nu este un capriciu:
    o dependență de sesiune rulează **înaintea** funcției, deci cu baza căzută
    cererea ar fi murit acolo și ar fi ieșit 500 cu urmă de excepție, în loc de
    503-ul controlat pe care îl așteaptă load balancerul. Ruta de sănătate trebuie
    să răspundă **mai ales** când ceva este stricat.

    Prețul este că nu vede tranzacția necomisă a testului — de aceea legătura de
    aici, același tipar ca `cli_session` din `test_cli.py`.
    """

    @contextmanager
    def scope() -> Iterator[Session]:
        yield db
        db.flush()

    monkeypatch.setattr(health_routes, "session_scope", scope)
    return api


class TestTheHealthEndpoints:
    def test_workers_answers_503_when_nobody_is_processing(
        self, api_public: TestClient, db: Session
    ) -> None:
        """Semnalul pe care îl urmărește monitorizarea externă."""
        answer = api_public.get(WORKERS)

        assert answer.status_code == 503, answer.text
        body = answer.json()
        assert body["status"] == "stale"
        assert body["workers"][0]["healthy"] is False

    def test_workers_answers_200_when_the_worker_is_alive(
        self, api_public: TestClient, db: Session
    ) -> None:
        worker_health.beat(db)
        db.flush()

        answer = api_public.get(WORKERS)

        assert answer.status_code == 200, answer.text
        assert answer.json()["workers"][0]["healthy"] is True

    def test_a_stale_worker_does_not_take_the_api_out_of_rotation(
        self, api_public: TestClient, db: Session
    ) -> None:
        """Cea mai importantă alegere de aici.

        Dacă `ready` ar cădea odată cu workerul, load balancerul ar scoate din
        rotație **toate** instanțele de API: o problemă de procesare s-ar
        transforma într-o cădere totală, exact în clipa în care cabinetul are
        nevoie să deschidă ecranul cozii ca să înțeleagă ce se întâmplă.

        Un worker mort trebuie să sune un om, nu să oprească aplicația.
        """
        worker_health.beat(db)
        db.flush()
        age_the_heartbeat(db, seconds=worker_health.settings.worker_heartbeat_timeout_seconds + 60)

        ready = api_public.get(READY)

        assert ready.status_code == 200, ready.text
        assert ready.json()["database"] is True
        # …dar starea lui se vede acolo, pentru cine citește corpul.
        assert ready.json()["worker"]["healthy"] is False

    def test_readiness_still_reports_the_worker_it_sees(
        self, api_public: TestClient, db: Session
    ) -> None:
        worker_health.beat(db)
        db.flush()

        body = api_public.get(READY).json()

        assert body["worker"]["healthy"] is True
        assert body["worker"]["name"] == DEFAULT_WORKER

    def test_no_secret_leaks_through_the_health_endpoints(self, api_public: TestClient) -> None:
        """Le citește un monitor din afară, fără sesiune (§8: „nu expune secrets")."""
        for url in (READY, WORKERS, "/api/v1/health/info"):
            text = api_public.get(url).text.lower()
            for forbidden in ("password", "secret", "token", "api_key", "postgresql://"):
                assert forbidden not in text, f"{url} conține {forbidden!r}"


class TestWhenTheDatabaseIsDown:
    """Rutele de sănătate trebuie să răspundă **mai ales** când ceva e stricat.

    **Regresia pe care o apără.** Prima versiune a acestor rute primea sesiunea
    prin `Depends`. O dependență rulează **înaintea** funcției: cu baza căzută,
    cererea murea acolo și ieșea **500 cu urmă de excepție**, în loc de 503-ul
    controlat pe care îl așteaptă load balancerul — și exact atunci, când baza e
    jos, un 500 opac este cel mai prost răspuns posibil.

    Testul simulează căderea la nivelul la care se vede: sesiunea nu se poate
    deschide.
    """

    @pytest.fixture
    def database_down(self, api: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        @contextmanager
        def broken() -> Iterator[Session]:
            raise OperationalError("select 1", {}, Exception("connection refused"))
            yield  # pragma: no cover — nu se ajunge aici

        monkeypatch.setattr(health_routes, "session_scope", broken)
        monkeypatch.setattr(health_routes, "check_database", lambda: False)
        return api

    def test_readiness_answers_503_not_500(self, database_down: TestClient) -> None:
        answer = database_down.get(READY)

        assert answer.status_code == 503, answer.text
        assert answer.json()["database"] is False
        assert answer.json()["status"] == "degraded"

    def test_readiness_does_not_leak_a_stack_trace(self, database_down: TestClient) -> None:
        """Ruta este publică: un traceback de acolo spune structura aplicației."""
        text = database_down.get(READY).text

        assert "Traceback" not in text
        assert "psycopg" not in text
        assert "connection refused" not in text

    def test_workers_says_unknown_instead_of_healthy(self, database_down: TestClient) -> None:
        """Tăcerea ar fi cea mai proastă minciună.

        Dacă starea nu se poate citi, „sănătos" este exact afirmația pe care nu o
        putem susține — iar monitorul ar fi tăcut fix când trebuia să sune.
        """
        answer = database_down.get(WORKERS)

        assert answer.status_code == 503, answer.text
        assert answer.json()["status"] == "unknown"

    def test_liveness_still_answers(self, database_down: TestClient) -> None:
        """Procesul trăiește; orchestratorul nu trebuie să-l repornească degeaba."""
        assert database_down.get("/api/v1/health/live").status_code == 200
