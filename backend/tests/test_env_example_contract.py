"""`.env.example` și `Settings`, ținute împreună (§30).

**De ce nu ajunge grija.** Fișierul acesta este singurul loc din care cineva care
pune aplicația în producție află ce se poate configura. Se desparte de cod în
două feluri, amândouă tăcute:

1. **O variabilă pe care aplicația nu o citește.** Cineva o pune, crede că a
   schimbat ceva, și nu s-a schimbat nimic. Cazul găsit la poarta de Go-Live:
   `PASSWORD_HASH_ALGORITHM=argon2id` — algoritmul este ales în cod și nu se
   poate schimba din mediu. Pusă pe altceva, ar fi lăsat pe cineva să creadă că
   a schimbat o decizie de securitate pe care nu a schimbat-o. La fel
   `OCR_FALLBACK_PROVIDER`, care nu are corespondent în cod.
2. **Un câmp real care nu apare nicăieri.** `REFERENCE_PERIOD_STRATEGY` decide
   din ce dată se derivă luna contabilă a unui document (ADR-008) — una dintre
   cele mai consecvente alegeri contabile din aplicație — și nu se putea afla
   decât citind sursa.

Un audit anterior a curățat lista o dată, de mână. Fără testul acesta, s-a
umplut la loc. De aceea verificarea stă aici, nu într-un document.

**Ce se acceptă în plus**, cu motiv scris pentru fiecare: variabile consumate de
`docker-compose.yml` (nu de aplicație) și variabile marcate explicit
`NEIMPLEMENTAT`. Marcajul este mai onest decât ștergerea — planul rămâne vizibil,
iar nimeni nu pierde o după-amiază adunând credențiale degeaba.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"
COMPOSE = REPO / "docker-compose.yml"

#: Marcajul care scutește o variabilă de obligația de a exista în cod.
UNIMPLEMENTED = "NEIMPLEMENTAT"


@pytest.fixture(scope="module")
def example_source() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def declared(example_source: str) -> dict[str, str]:
    """Fiecare variabilă din `.env.example`, cu linia ei întreagă.

    Linia întreagă, nu doar numele: marcajul `NEIMPLEMENTAT` stă în comentariul
    de pe aceeași linie, iar testul trebuie să-l poată vedea.
    """
    found: dict[str, str] = {}
    for line in example_source.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match is not None:
            found[match.group(1)] = line
    assert found, ".env.example nu declară nicio variabilă"
    return found


@pytest.fixture(scope="module")
def compose_variables() -> set[str]:
    """Ce citește `docker-compose.yml` direct, fără să treacă prin aplicație."""
    source = COMPOSE.read_text(encoding="utf-8")
    return set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", source))


def test_every_setting_can_be_discovered(declared: dict[str, str]) -> None:
    """Un câmp care nu apare aici nu se poate configura de nimeni care nu citește codul."""
    missing = sorted({name.upper() for name in Settings.model_fields} - set(declared))

    assert not missing, (
        "câmpuri din Settings care lipsesc din .env.example: "
        + ", ".join(missing)
        + ". Un operator nu are de unde ști că se pot pune."
    )


def test_no_variable_promises_something_the_code_does_not_read(
    declared: dict[str, str], compose_variables: set[str]
) -> None:
    """Fiecare variabilă ori este citită, ori este a lui compose, ori spune că nu face nimic."""
    fields = {name.upper() for name in Settings.model_fields}

    orphans = [
        name
        for name, line in declared.items()
        if name not in fields and name not in compose_variables and UNIMPLEMENTED not in line
    ]

    assert not orphans, (
        "variabile pe care nu le citește nimeni și care nu sunt marcate "
        f"{UNIMPLEMENTED!r}: " + ", ".join(sorted(orphans))
    )


#: Variabile care **au** câmp în `Settings` și sunt totuși marcate `NEIMPLEMENTAT`.
#:
#: Nu este o contradicție: câmpul citește valoarea și ecranul de administrare o
#: arată, dar **funcția din spate nu există**. Lista este scrisă de mână tocmai
#: ca fiecare astfel de caz să fie o decizie, nu un accident — vezi testul de
#: mai jos, care refuză orice altă combinație.
CONFIGURED_BUT_NOT_IMPLEMENTED: dict[str, str] = {
    # Niciun job de retenție nu există. Comutatorul se citește și se afișează,
    # dar pe `true` nu șterge nimic. Eticheta de pe ecran spune „neimplementat",
    # ca nimeni să nu creadă că documentele vechi dispar singure (R8).
    "RETENTION_ENABLED": "nu există niciun job de retenție; comutatorul nu șterge nimic",
}


def test_the_marked_ones_really_are_absent_from_the_code(declared: dict[str, str]) -> None:
    """Contra-proba: marcajul nu are voie să devină o portiță.

    Fără ea, `NEIMPLEMENTAT` s-ar fi lipit pe orice și testul de mai sus ar fi
    tăcut — inclusiv pentru un câmp real scris greșit. Marcajul pe o variabilă
    care **are** câmp cere o intrare explicită mai sus, cu motivul ei.
    """
    fields = {name.upper() for name in Settings.model_fields}

    lying = [
        name
        for name, line in declared.items()
        if UNIMPLEMENTED in line and name in fields and name not in CONFIGURED_BUT_NOT_IMPLEMENTED
    ]

    assert not lying, (
        f"variabile marcate {UNIMPLEMENTED!r} care au câmp în Settings și nu sunt "
        "explicate în CONFIGURED_BUT_NOT_IMPLEMENTED: " + ", ".join(sorted(lying))
    )


def test_the_explained_exceptions_are_still_marked(declared: dict[str, str]) -> None:
    """Iar lista de excepții nu are voie să rămână în urmă.

    Dacă retenția se implementează vreodată, marcajul dispare din `.env.example`
    și intrarea de aici trebuie ștearsă odată cu el — altfel documentația ar
    continua să spună „neimplementat" despre o funcție care există.
    """
    for name in CONFIGURED_BUT_NOT_IMPLEMENTED:
        assert name in declared, f"{name} nu mai există în .env.example"
        assert UNIMPLEMENTED in declared[name], (
            f"{name} nu mai este marcat {UNIMPLEMENTED!r}: scoate-l din "
            "CONFIGURED_BUT_NOT_IMPLEMENTED dacă funcția s-a implementat."
        )


def test_no_real_secret_value_is_committed(declared: dict[str, str]) -> None:
    """`.env.example` conține **nume**, nu valori.

    Cele două excepții sunt evidente și rămân verificate ca atare: cheia de
    development, al cărei text spune să fie schimbată, și parola bazei de
    development. Orice altă valoare care arată a secret cade testul.
    """
    expected_placeholders = {
        "SECRET_KEY": "schimba-aceasta-valoare-inainte-de-orice-deploy",
        "POSTGRES_PASSWORD": "contacrm_dev_password",
    }
    #: Numele care **poartă** un secret, nu orice nume care conține cuvântul.
    #: `ACCESS_TOKEN_EXPIRE_MINUTES` este o durată, nu un token.
    secretish = re.compile(r"(_SECRET|SECRET_KEY|_PASSWORD|_TOKEN|_API_KEY|_ACCESS_KEY_ID)$")

    for name, line in declared.items():
        if not secretish.search(name):
            continue
        value = line.split("=", 1)[1].split("#")[0].strip()
        if value == "":
            continue
        assert value == expected_placeholders.get(name), (
            f"{name} are o valoare în .env.example. Fișierul conține doar nume."
        )
