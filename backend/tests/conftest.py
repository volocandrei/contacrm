"""Fixture-uri comune.

Testele care nu ating baza de date rulează întotdeauna. Cele care au nevoie de
Postgres folosesc fixture-ul `db` și **sar** cu un motiv explicit când baza nu e
pornită — un test care cade pentru că infrastructura lipsește nu spune nimic despre
cod, dar ascunde regresiile reale.

Baza de test este una separată (`<db>_test`), creată și golită de fixture. Nu
atingem niciodată baza de development.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

CONNECT_TIMEOUT = 3


def _test_database_url() -> URL:
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_test")


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
requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason="PostgreSQL nu este pornit — rulează `docker compose up -d`",
)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[sa.Engine]:
    if not DB_AVAILABLE:  # pragma: no cover — sărit prin marker
        pytest.skip("PostgreSQL indisponibil")

    from app.models import Base  # importul înregistrează toate tabelele

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

    engine = sa.create_engine(target, poolclass=sa.pool.NullPool)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(engine)

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
        transaction.rollback()
        connection.close()


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
