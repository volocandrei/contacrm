"""Conexiunea la baza de date.

Engine-ul se creează o singură dată. Sesiunea trăiește exact cât o cerere HTTP:
se comite dacă handler-ul a reușit, se face rollback dacă a aruncat. Nicio scriere
nu rămâne pe jumătate.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Sondele de health trebuie să răspundă repede, chiar și când baza e căzută.
DB_CONNECT_TIMEOUT_SECONDS = 3

# O conexiune care stă deschisă mai mult de atât se reînnoiește. Poolerii și
# firewall-urile taie conexiunile inactive fără să anunțe pe nimeni; descoperirea
# se face altfel în mijlocul unei cereri reale.
POOL_RECYCLE_SECONDS = 1800


def connect_arguments(config: Settings) -> dict[str, object]:
    """Ce se trimite driverului la fiecare conexiune nouă.

    Stă separat de `build_engine` pentru că este singura parte pe care nu o mai
    poți citi din engine după construire — SQLAlchemy o coace în closure-ul de
    conectare. Ceva ce nu se poate inspecta nu se poate nici verifica, iar asta
    conține exact detaliul care se rupe doar în producție.
    """
    arguments: dict[str, object] = {
        # Fără asta, o sondă de readiness atârnă la nesfârșit când baza nu răspunde,
        # iar orchestratorul nu află niciodată că serviciul nu e gata.
        "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
        # Apare în pg_stat_activity — util când cauți cine ține o conexiune.
        "application_name": config.app_name,
    }
    if config.db_external_pooler:
        # Poolerul dă altă sesiune din spate la fiecare tranzacție, iar o
        # instrucțiune pregătită într-una nu există în următoarea. Eșecul arată ca
        # un `prepared statement "_pg3_0" does not exist` apărut din senin, la a
        # doua cerere — nu la prima, deci nu la testare.
        arguments["prepare_threshold"] = None
    return arguments


def build_engine(config: Settings | None = None) -> Engine:
    """Engine-ul, configurat după cine face poolingul.

    Două lumi diferite, și confuzia dintre ele se vede abia sub trafic:

    - **proces lung, conexiune directă** — SQLAlchemy ține poolul, pentru că el
      este singurul care știe cine folosește conexiunile;
    - **în spatele unui pooler în mod tranzacție** — SQLAlchemy nu ține niciunul.
      Un pool peste alt pool ar însemna conexiuni ținute degeaba de fiecare
      instanță, iar când instanțele apar și dispar odată cu traficul, baza rămâne
      fără conexiuni exact în vârful în care ai nevoie de ele.

    Ce se schimbă în plus la conectare este în `connect_arguments`.
    """
    config = config or settings
    connect_args = connect_arguments(config)

    if config.db_external_pooler:
        return create_engine(
            config.database_url,
            echo=config.db_echo,
            poolclass=NullPool,
            future=True,
            connect_args=connect_args,
        )

    return create_engine(
        config.database_url,
        echo=config.db_echo,
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        # O conexiune ruptă în pool trebuie descoperită înainte de a fi folosită.
        pool_pre_ping=True,
        pool_recycle=POOL_RECYCLE_SECONDS,
        future=True,
        connect_args=connect_args,
    )


engine = build_engine()

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


def get_db(request: Request) -> Generator[Session, None, None]:
    """Dependența FastAPI. O cerere = o tranzacție.

    **`commit` nu se face aici.** Blocul de după `yield` al unei dependențe se
    execută, în FastAPI, după ce răspunsul a plecat spre client — deci o cerere
    imediat următoare putea citi starea de dinainte de confirmare. Confirmarea o
    face `CommittingRoute`, în interiorul apelului de endpoint; sesiunea i se
    lasă la îndemână pe `request.state`.

    `rollback` și `close` rămân aici: ele au voie să se întâmple după răspuns,
    fiindcă nu schimbă ce vede clientul.
    """
    session = SessionFactory()
    request.state.db = session
    try:
        yield session
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
