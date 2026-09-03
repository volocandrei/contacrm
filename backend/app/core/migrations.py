"""Aplicarea migrărilor din cod, nu din linia de comandă.

Există un singur loc care știe unde stau `alembic.ini` și directorul de scripturi.
Testele își construiesc baza cu funcția asta, la fel și comanda care pregătește
baza de E2E — deci amândouă rulează exact ce rulează și producția, iar §59 se
respectă de la sine: nicio schemă nu se mai poate naște din `create_all`.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import URL

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


def run_migrations(url: URL) -> None:
    """`alembic upgrade head` pe baza dată."""
    command.upgrade(alembic_config(url), "head")
