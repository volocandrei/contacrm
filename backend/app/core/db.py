"""Conexiunea la baza de date.

Engine-ul se creează o singură dată. Sesiunea trăiește exact cât o cerere HTTP:
se comite dacă handler-ul a reușit, se face rollback dacă a aruncat. Nicio scriere
nu rămâne pe jumătate.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Sondele de health trebuie să răspundă repede, chiar și când baza e căzută.
DB_CONNECT_TIMEOUT_SECONDS = 3

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # O conexiune ruptă în pool trebuie descoperită înainte de a fi folosită.
    pool_pre_ping=True,
    future=True,
    connect_args={
        # Fără asta, o sondă de readiness atârnă la nesfârșit când baza nu răspunde,
        # iar orchestratorul nu află niciodată că serviciul nu e gata.
        "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
        # Apare în pg_stat_activity — util când cauți cine ține o conexiune.
        "application_name": settings.app_name,
    },
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Tranzacție pentru cod din afara ciclului HTTP (workeri, comenzi CLI)."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Dependența FastAPI. O cerere = o tranzacție."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    """Folosit de `/health/ready`. Nu aruncă — întoarce starea."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # orice eșec înseamnă „nu e gata"
        logger.warning("database_unavailable", error=type(exc).__name__)
        return False
    return True
