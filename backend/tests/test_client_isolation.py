"""Clientul altui cabinet nu există — pe fiecare rută, nu doar pe cele verificate.

**Cum a fost găsit.** Nu citind cod, ci întrebând serverul: am creat o a doua
organizație cu un client al ei, apoi am cerut, cu sesiunea primei organizații,
fiecare rută care poartă un id. Șaisprezece au răspuns `404`. Două au răspuns
`200`.

**De ce contează, deși nu se scurgea nimic.** `/clients/{id}/upload-links` și
`/clients/{id}/aliases` filtrau oricum după `organization_id`, deci întorceau o
listă goală. Ce lipsea nu era confidențialitatea de azi, ci **garanția**: ziua în
care cineva ar fi simplificat interogarea la `client_id` — o schimbare care arată
inofensivă — le-ar fi transformat în scurgeri adevărate, fără niciun test care să
cadă. Iar inconsecvența era vizibilă cu ochiul liber: `POST` pe exact aceeași
resursă răspundea deja `404`.

**De ce sweep și nu două teste.** Rutele se adaugă mereu. Un test pe rută
verifică ce știam ieri; ăsta verifică ce se adaugă mâine, și cade până când noua
rută se poartă ca surorile ei (§72).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus
from app.models.client import Client
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import requires_db
from tests.test_periods_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)

#: Rute care poartă un id, dar nu al unei resurse de client sau document — deci
#: nu intră în această regulă. Se enumeră explicit: o listă albă tăcută ar fi
#: lăsat pe dinafară exact ruta care trebuia verificată.
NOT_OWNED = ("/roles/", "/users/", "/audit-logs/")


@pytest.fixture
def foreign_client(db: Session) -> Client:
    """Un client care aparține altui cabinet. Pentru noi, nu trebuie să existe."""
    other = Organization(name="Alt Cabinet SRL", tax_id="RO999888")
    db.add(other)
    db.flush()
    client = Client(
        organization_id=other.id,
        name="Client Străin SRL",
        tax_id="RO555444",
        status=ClientStatus.ACTIVE,
    )
    db.add(client)
    db.flush()
    return client


def owned_get_routes(api: TestClient) -> list[str]:
    """Rutele `GET` care primesc un id de resursă deținută de o organizație."""
    schema = api.get("/openapi.json").json()
    found = []
    for path, operations in schema["paths"].items():
        if "get" not in operations:
            continue
        if not any(name.endswith("_id") for name in re.findall(r"\{(\w+)\}", path)):
            continue
        if any(marker in path for marker in NOT_OWNED):
            continue
        found.append(path)
    return found


def test_no_route_answers_for_another_office_client(
    api: TestClient, db: Session, admin: User, foreign_client: Client
) -> None:
    """Fiecare rută cu id răspunde `404` pentru resursa altui cabinet.

    `404`, nu `403`: un „nu ai voie" confirmă că id-ul există undeva, iar asta
    este deja o informație despre clienții altui cabinet.
    """
    db.commit()
    login(api, admin.email)

    routes = owned_get_routes(api)
    assert len(routes) >= 15, "sweep-ul nu mai găsește rutele — s-a schimbat schema?"

    leaking = []
    for path in routes:
        url = re.sub(r"\{[^}]+\}", str(foreign_client.id), path)
        answer = api.get(url)
        if answer.status_code != 404:
            leaking.append(f"{path} → {answer.status_code}")

    assert not leaking, "rute care nu izolează clientul altui cabinet: " + ", ".join(leaking)


def test_the_two_routes_that_used_to_answer_are_named(
    api: TestClient, db: Session, admin: User, foreign_client: Client
) -> None:
    """Cele două care răspundeau `200 []`, pe nume.

    Sweep-ul de mai sus le-ar prinde oricum. Testul acesta există ca să rămână
    scris **care** au fost: peste un an, cine citește sweep-ul nu are de unde să
    știe că el a fost adăugat pentru ele.
    """
    db.commit()
    login(api, admin.email)

    for path in ("upload-links", "aliases"):
        answer = api.get(f"/api/v1/clients/{foreign_client.id}/{path}")
        assert answer.status_code == 404, path


def test_an_invented_id_does_not_answer_either(api: TestClient, db: Session, admin: User) -> None:
    """Nu doar clientul altui cabinet: și un id care nu există nicăieri.

    Amândouă rutele răspundeau `200 []` pentru orice UUID, ceea ce înseamnă că
    nu verificau nimic — nu că verificau și găseau gol.
    """
    db.commit()
    login(api, admin.email)
    nowhere = "00000000-0000-0000-0000-000000000000"

    assert api.get(f"/api/v1/clients/{nowhere}/upload-links").status_code == 404
    assert api.get(f"/api/v1/clients/{nowhere}/aliases").status_code == 404
