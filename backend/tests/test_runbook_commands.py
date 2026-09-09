"""Comenzile din runbook-uri trebuie să ruleze, nu doar să arate bine.

**Defectul care a produs fișierul.** Procedura de copiere de siguranță scria:

```bash
pg_dump --format=custom --no-owner "$DATABASE_URL" > contacrm-$(date +%F).dump
```

`DATABASE_URL` este scrisă în dialect SQLAlchemy — `postgresql+psycopg://…` — iar
`pg_dump` **nu recunoaște schema aceea ca URI**. Nu se plânge de ea: o tratează ca
nume de bază de date și se conectează cu setările implicite, adică la altă bază, ca
alt utilizator.

Ce se întâmplă atunci depinde de noroc, și ambele capete sunt proaste. Cu parolă
cerută, primești „password authentication failed for user <utilizatorul de sistem>"
— un mesaj care te trimite să cauți o problemă de parolă acolo unde este o problemă
de adresă, exact în minutul în care ai nevoie de o copie. Cu autentificare `trust`
sau un `.pgpass` potrivit, **comanda reușește și copiază altă bază**, iar fișierul
rezultat are dimensiune, dată și un nume liniștitor.

O copie de siguranță care nu conține nimic se descoperă la restaurare. Nu există
moment mai prost.

Regula fixată aici: uneltele PostgreSQL nu primesc niciodată `$DATABASE_URL`
direct.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import REPO_ROOT, settings

DOCS = REPO_ROOT / "docs"

#: Uneltele libpq. Toate refuză dialectul, din același motiv.
TOOLS = ("pg_dump", "pg_restore", "pg_dumpall", "psql")

#: Forma corectă: dialectul scos înainte de a ajunge la unealtă.
STRIPPED = "${DATABASE_URL/+psycopg/}"

RAW = re.compile(r'"?\$DATABASE_URL"?')

#: Rapoartele **citează** comanda greșită ca să explice defectul; un raport nu se
#: execută. Lista este explicită, nu un tipar: un document nou care ajunge aici
#: trebuie adăugat de cineva care s-a uitat la el, nu strecurat de o regulă.
QUOTE_THE_DEFECT: frozenset[str] = frozenset({"VERCEL_DEPLOYMENT_REPORT.md"})

#: Documentele pe care cineva chiar le urmează, cu mâinile pe tastatură.
MUST_BE_SCANNED: frozenset[str] = frozenset(
    {
        "RUNBOOK.md",
        "PRODUCTION_RELEASE_GATE.md",
        "PRODUCTION_INCIDENT_RUNBOOK.md",
    }
)


def command_lines() -> list[tuple[Path, int, str]]:
    """Liniile din documentație care cheamă o unealtă PostgreSQL."""
    found: list[tuple[Path, int, str]] = []
    for document in sorted(DOCS.rglob("*.md")):
        if document.name in QUOTE_THE_DEFECT:
            continue
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            if any(tool in line for tool in TOOLS):
                found.append((document, number, line))
    return found


def test_the_application_really_speaks_the_sqlalchemy_dialect() -> None:
    """Contra-proba. Fără dialect în `DATABASE_URL`, restul fișierului n-ar avea rost."""
    assert "+psycopg" in settings.database_url


def test_there_are_commands_to_check() -> None:
    """A doua contra-probă: o căutare care nu găsește nimic ar trece pe gol."""
    assert command_lines()


def test_the_documents_people_actually_follow_are_scanned() -> None:
    """A treia. Excluderea rapoartelor nu are voie să înghită și procedurile.

    Fără testul ăsta, o scutire pusă din grabă ar fi scos din verificare exact
    fișierul pe care îl deschide cineva la trei dimineața.
    """
    scanned = {document.name for document, _, _ in command_lines()}

    assert scanned >= MUST_BE_SCANNED


def test_no_postgres_tool_gets_the_dialect_url() -> None:
    """Testul pentru care există fișierul."""
    offenders = [
        f"{document.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for document, number, line in command_lines()
        if RAW.search(line.replace(STRIPPED, ""))
    ]

    assert offenders == [], (
        "Uneltele PostgreSQL nu înțeleg `postgresql+psycopg://`. Nu dau eroare "
        "despre schemă: se conectează în altă parte, iar copia poate reuși pe altă "
        "bază. Scoate dialectul întâi: " + STRIPPED + "\n" + "\n".join(offenders)
    )
