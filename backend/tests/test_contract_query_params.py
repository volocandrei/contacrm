"""Fiecare parametru de query, în forma pe care o cere contractul (§52, §53).

**Defectul G-01, ca să nu se mai întoarcă.** Ruta de tranzacții bancare declara
filtrele ca parametri separați — `statement_id`, `client_id` — într-un contract
care este camelCase în ambele direcții. Interfața cerea `?statementId=...`,
FastAPI nu recunoștea numele și **îl ignora**: fără eroare, cu răspuns 200, dar cu
rândurile tuturor extraselor în loc de ale celui ales.

Un filtru ignorat nu se vede. Nu dă 422, nu apare în loguri, nu strică niciun
test funcțional — răspunde la altă întrebare. Într-o reconciliere bancară, asta
înseamnă că cine bifează „nimic nepotrivit" se uită la altceva.

**Regula, verificată aici pe toată aplicația:** niciun parametru de query nu are
voie să ajungă `snake_case` în schema publică. Sunt două feluri corecte de a o
respecta, amândouă folosite deja în cod:

1. un model `ApiModel` legat cu `Query()` — primește `alias_generator=to_camel`
   de la sine, și este forma preferată pentru filtre;
2. un `Query(alias="numeCamel")` explicit, pentru un parametru singur.

Testul se uită la **rezultat**, nu la formă: citește schema OpenAPI pe care o
publică aplicația. Orice cale ar alege cineva, dacă parametrul iese `snake_case`,
testul cade.
"""

from __future__ import annotations

import re

import pytest

from app.main import create_app

#: Un nume cu underscore între litere mici. `pageSize` trece, `page_size` nu.
SNAKE = re.compile(r"[a-z]_[a-z]")


@pytest.fixture(scope="module")
def query_parameters() -> list[tuple[str, str, str]]:
    """Toți parametrii de query ai aplicației: metodă, cale, nume.

    Din schema OpenAPI, adică din ce **vede clientul** — nu din numele variabilei
    Python, care poate fi altul dacă există un alias.
    """
    schema = create_app().openapi()
    found = [
        (method.upper(), path, parameter["name"])
        for path, methods in schema["paths"].items()
        for method, spec in methods.items()
        for parameter in spec.get("parameters", [])
        if parameter.get("in") == "query"
    ]
    assert len(found) >= 50, f"descoperire suspect de mică: {len(found)} parametri"
    return found


def test_no_query_parameter_is_snake_case(query_parameters: list[tuple[str, str, str]]) -> None:
    """Un parametru `snake_case` este un filtru pe care interfața nu-l poate trimite."""
    offenders = [
        f"{method} {path} → {name}" for method, path, name in query_parameters if SNAKE.search(name)
    ]

    assert not offenders, (
        "parametri de query în `snake_case`, pe care interfața îi trimite camelCase "
        "și care se pierd în tăcere:\n  "
        + "\n  ".join(offenders)
        + "\n\nLeagă-i printr-un model `ApiModel` cu `Query()`, sau dă-le "
        '`Query(alias="numeCamel")`.'
    )


def test_the_bank_filters_are_the_ones_that_broke(
    query_parameters: list[tuple[str, str, str]],
) -> None:
    """Cazul concret, numit, ca nimeni să nu-l repare doar pe hârtie.

    Nu este redundant față de testul de mai sus: acela apără regula, acesta apără
    **defectul găsit**. Dacă cineva rescrie ruta și scapă filtrul cu totul, primul
    test tace — nu mai există niciun parametru greșit — iar ecranul se întoarce la
    a arăta toate tranzacțiile cabinetului.
    """
    bank = {name for method, path, name in query_parameters if path == "/api/v1/bank/transactions"}

    assert {"statementId", "clientId", "status"} <= bank, (
        f"filtrele listei de tranzacții lipsesc din schemă: {sorted(bank)}"
    )
