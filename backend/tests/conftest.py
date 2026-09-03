"""Fixture-uri comune.

Testele care nu ating baza de date rulează întotdeauna. Cele care au nevoie de
Postgres folosesc fixture-ul `db` și **sar** cu un motiv explicit când baza nu e
pornită — un test care cade pentru că infrastructura lipsește nu spune nimic despre
cod, dar ascunde regresiile reale.

**În CI, nu.** Acolo o bază lipsă oprește rularea: altfel un serviciu `postgres`
care nu a pornit ar da un raport verde peste o suită sărită aproape în întregime.

Baza de test este una separată (`<db>_test_<pid>`), creată și golită de fixture.
Nu atingem niciodată baza de development.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.migrations import run_migrations
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

CONNECT_TIMEOUT = 3

# Cheia cu care se criptează tokenurile de drive. Se pune aici, la import, pentru
# că `app.core.crypto` o citește o singură dată și o ține în cache — setată dintr-o
# fixture, ar ajunge prea târziu. Este o cheie de test, generată o dată și scrisă
# aici pe față: nu deschide nimic real.
if not settings.drive_token_key:
    settings.drive_token_key = "cCPQjIQqRAo3mm7d1u_ehSTzWpEHRe1XoHZM9lyoO_M="


def _test_database_url() -> URL:
    """Baza de test, una per proces.

    Numele poartă PID-ul pentru că fixture-ul își aruncă baza cu
    `DROP DATABASE ... WITH (FORCE)`, iar `FORCE` deconectează pe oricine este
    legat la ea. Cu un nume comun, două rulări pornite în paralel — două terminale,
    sau o rulare uitată în fundal — se distrug reciproc, iar rezultatul este o
    sută de erori SQLAlchemy fără nicio legătură cu codul. Le-am urmărit de două
    ori înainte să-mi dau seama ce se întâmplă.

    Un proces omorât brutal lasă în urmă o bază `..._test_<pid>`. Se vede după
    nume și nu încurcă pe nimeni.
    """
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_test_{os.getpid()}")


def _server_reachable() -> bool:
    """Ne conectăm la baza de întreținere `postgres`, nu la cea de test."""
    admin = make_url(settings.database_url).set(database="postgres")
    try:
        engine = sa.create_engine(
            admin, connect_args={"connect_timeout": CONNECT_TIMEOUT}, poolclass=sa.pool.NullPool
        )
        with engine.connect():
            return True
    except Exception:
        return False


DB_AVAILABLE = _server_reachable()

# Pe laptop, o bază oprită înseamnă „sari testele care o cer": un eșec de
# infrastructură nu spune nimic despre cod și ar ascunde regresiile reale.
#
# În CI înseamnă altceva. Aproape toată suita cere baza de date, deci un Postgres
# care nu pornește ar face rularea să treacă **verde cu totul sărit** — exact
# raportul care nu trebuie să existe. De aceea acolo lipsa bazei este o eroare, nu
# un motiv de sărit.
if not DB_AVAILABLE and os.getenv("CI"):
    raise RuntimeError(
        "PostgreSQL nu este accesibil, iar CI nu are voie să treacă sărind "
        "testele de integrare. Verifică serviciul `postgres` și DATABASE_URL."
    )

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason="PostgreSQL nu este pornit — rulează `docker compose up -d`",
)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[sa.Engine]:
    if not DB_AVAILABLE:  # pragma: no cover — sărit prin marker
        pytest.skip("PostgreSQL indisponibil")

    target = _test_database_url()
    admin = sa.create_engine(
        make_url(settings.database_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=sa.pool.NullPool,
    )
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        connection.execute(sa.text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()

    # Schema se construiește **rulând migrările**, nu din metadata ORM: altfel
    # extensiile, funcțiile, constrângerile CHECK și indexurile parțiale definite
    # doar în migrări ar lipsi din teste, iar migrările n-ar fi exercitate niciodată.
    run_migrations(target)

    engine = sa.create_engine(target, poolclass=sa.pool.NullPool)
    yield engine

    engine.dispose()
    admin = sa.create_engine(
        make_url(settings.database_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=sa.pool.NullPool,
    )
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db(db_engine: sa.Engine) -> Iterator[Session]:
    """O sesiune per test, într-o tranzacție care se dă înapoi la final.

    Testele nu se pot influența între ele prin date rămase în urmă.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        # Un test care si-a dat singur rollback (ca sa verifice starea de dupa) lasa
        # tranzactia deja inchisa; a o inchide a doua oara ar produce un warning care
        # ar acoperi warning-urile reale.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _fresh_login_limiters() -> Iterator[None]:
    """Contoarele de autentificare sunt stare globala de proces.

    Fara golire, testele care se autentifica de mai multe ori s-ar bloca unele
    pe altele: `TestClient` are o singura adresa, deci toate testele suitei
    impart aceeasi cheie. Limitarea in sine este verificata explicit, in
    `test_rate_limit.py` si `test_auth_api.py`.
    """
    from app.api.v1.auth import LOGIN_LIMITERS

    for limiter in LOGIN_LIMITERS.values():
        limiter.reset()
    yield
    for limiter in LOGIN_LIMITERS.values():
        limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client HTTP fără bază de date — pentru health, erori și configurare."""
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def api(db: Session) -> Iterator[TestClient]:
    """Client HTTP legat de sesiunea de test, ca datele scrise să fie vizibile."""
    from app.core.db import get_db

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def frontend_types_source() -> str:
    """Sursa contractului pe care îl consumă frontend-ul."""
    return (REPO_ROOT / "frontend" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
