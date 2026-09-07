"""Stiva din `docker-compose.yml` primeste chiar configurarea cabinetului (§48, §83).

**De ce exista testul asta.** `DEPLOY.md` spune ca un VPS cu `docker compose`
ruleaza aplicatia intreaga. Compose insa nu trimite in container decat ce ii
enumeri, iar enumerarea a ramas in urma de doua ori: o data pentru integrarile
Microsoft — reparat separat, cu un commit al lui — si a doua oara pentru tot ce a
venit dupa: `SECRET_KEY`, `PUBLIC_BASE_URL`, `CRON_SECRET`, SMTP-ul intreg.

Efectul nu era o functie lipsa, ci un serviciu care nu porneste: in productie,
`SECRET_KEY` implicit si `PUBLIC_BASE_URL` pe localhost sunt refuzate la pornire
(`Settings.assert_production_ready`). Adica drumul scris in documentatie nu ducea
nicaieri, iar asta se afla la primul `docker compose up` pe serverul cabinetului.

**De ce se verifica `env_file` si nu o lista de variabile.** O lista ar avea exact
problema pe care o repara: ar trebui tinuta la zi de mana, si nu a fost. `env_file`
duce tot fisierul; testul verifica **mecanismul**, nu inventarul.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

#: Serviciile care ruleaza codul aplicatiei. `postgres` nu: el nu citeste
#: configurarea noastra, iar `.env`-ul aplicatiei nu are ce cauta in imaginea lui.
APPLICATION_SERVICES = ("backend", "worker", "migrate")

#: Ce **trebuie** sa ramana scris in compose, pentru ca nu poate veni din `.env`:
#: acolo baza este pe `localhost`, aici se cheama `postgres`, iar documentele stau
#: intr-un volum montat, nu in directorul de lucru.
CONTAINER_ONLY = ("DATABASE_URL", "STORAGE_PATH", "ARCHIVE_ROOT")


def compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return data


def test_the_stack_file_is_where_the_documentation_says() -> None:
    assert COMPOSE.exists(), COMPOSE


def test_every_application_service_receives_the_whole_env_file() -> None:
    """Fara asta, containerul porneste cu valorile implicite de development."""
    services = compose()["services"]

    for name in APPLICATION_SERVICES:
        assert name in services, f"serviciul `{name}` a disparut din compose"
        entries = services[name].get("env_file")
        assert entries, f"`{name}` nu primeste `.env` — configurarea nu ajunge in container"
        paths = {
            entry["path"] if isinstance(entry, dict) else entry
            for entry in (entries if isinstance(entries, list) else [entries])
        }
        assert ".env" in paths, f"`{name}`: {paths}"


def test_the_env_file_is_optional_so_a_fresh_clone_still_starts() -> None:
    """`docker compose up -d` fara `.env` trebuie sa mearga, ca pana acum."""
    services = compose()["services"]

    for name in APPLICATION_SERVICES:
        for entry in services[name]["env_file"]:
            assert isinstance(entry, dict), f"`{name}`: forma scurta face fisierul obligatoriu"
            assert entry.get("required") is False, f"`{name}`: {entry}"


def test_only_what_the_container_owns_is_written_over_the_env_file() -> None:
    """`environment:` bate `env_file`, deci ce se pune acolo nu mai poate fi schimbat.

    Enumerarea de dinainte punea acolo si `MS_CLIENT_ID`, si `OCR_PROVIDER`, si
    restul — adica exact lista care ramanea in urma. Ce ramane are un singur
    motiv: valoarea din `.env` ar fi gresita **inauntrul** containerului.
    """
    services = compose()["services"]

    for name in ("backend", "worker"):
        written = set(services[name].get("environment", {}))
        assert written == set(CONTAINER_ONLY), f"`{name}`: {sorted(written)}"


def test_the_worker_gets_the_same_configuration_as_the_api() -> None:
    """Workerul sincronizeaza si descifreaza tokenuri; cu alta configurare, tace."""
    services = compose()["services"]

    assert services["worker"]["env_file"] == services["backend"]["env_file"]
    assert services["worker"]["environment"] == services["backend"]["environment"]
