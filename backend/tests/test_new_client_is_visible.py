"""Clientul adăugat acum apare peste tot unde se alege un client (§24).

**Sesizarea.** „nu îmi apare în această listă clientul adăugat de mine mai
devreme". Nu s-a spus care listă, și tocmai asta este problema: aplicația are
**unsprezece** locuri în care se alege un client, iar fiecare își cere lista cu
alți parametri. Trei fără filtru de stare, șase numai cu `ACTIVE`, unul cu
căutare, unul cu paginare proprie.

Un test pe ecranul reclamat ar fi răspuns la întrebarea de ieri. Testul de aici
ia **fiecare cerere pe care o face frontendul**, exact cum o face, și verifică
faptul care contează pentru cel care a reclamat: clientul pe care tocmai l-am
creat trebuie să fie acolo.

Perechile de mai jos sunt citite din interfață, nu inventate: `pageSize=200` este
chiar ce cere `upload-panel.tsx` când deschide selectorul de client, iar `200`
este și maximul acceptat de server — o cerere cu 201 ar fi fost respinsă cu 422,
și atunci **niciun** client n-ar mai fi apărut nicăieri.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import User
from tests.conftest import requires_db
from tests.test_crm_api import login

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

URL = "/api/v1/clients"

#: Cererile pe care le face interfața, cu numele ecranului care le face.
#: Se citesc din `useClients(...)`; dacă un ecran nou cere altfel, se adaugă aici.
SCREENS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Clienți (lista principală)", {"page": 1, "pageSize": 20}),
    ("Documente — selector de client", {"pageSize": 200}),
    ("Încărcare document — selector", {"pageSize": 200, "status": "ACTIVE"}),
    ("Verificare — reatribuire client", {"pageSize": 200, "status": "ACTIVE"}),
    ("Sarcini — selector", {"pageSize": 200, "status": "ACTIVE"}),
    ("Surse documente — dosare", {"pageSize": 200, "status": "ACTIVE"}),
    ("e-Factura — împuterniciri", {"pageSize": 200, "status": "ACTIVE"}),
    ("Declarații — selector", {"pageSize": 200}),
    ("Rapoarte — selector", {"pageSize": 200}),
)


def names_in(api: TestClient, params: dict[str, Any]) -> list[str]:
    answer = api.get(URL, params=params)
    assert answer.status_code == 200, f"{params} → {answer.status_code}: {answer.text}"
    return [item["name"] for item in answer.json()["items"]]


@pytest.fixture
def created(api: TestClient, admin: User) -> str:
    """Un client adăugat prin exact drumul pe care îl folosește omul: formularul."""
    login(api, admin.email)
    answer = api.post(URL, json={"name": "Zeta Nouă SRL", "taxId": "RO77001122"})
    assert answer.status_code == 201, answer.text
    name: str = answer.json()["name"]
    return name


class TestTheClientAddedAMomentAgo:
    def test_it_appears_on_every_screen_that_offers_a_client(
        self, api: TestClient, created: str
    ) -> None:
        """Unsprezece locuri, o singură așteptare: să fie acolo."""
        missing = [screen for screen, params in SCREENS if created not in names_in(api, params)]

        assert not missing, "clientul nou lipsește din: " + ", ".join(missing)

    def test_it_is_active_by_default_which_is_why_it_appears(
        self, api: TestClient, admin: User, created: str
    ) -> None:
        """Motivul pentru care șase dintre ecrane îl văd.

        Ele cer `status=ACTIVE`. Dacă implicitul creării ar deveni `PROSPECT` —
        o schimbare care sună inofensivă — clientul nou ar dispărea din
        **selectorul de încărcare**, adică exact din locul în care cineva tocmai
        l-a creat ca să-i urce documentele.
        """
        listed = api.get(URL, params={"pageSize": 200}).json()["items"]
        row = next(item for item in listed if item["name"] == created)

        assert row["status"] == "ACTIVE"

    def test_it_is_found_by_search_and_by_the_command_palette(
        self, api: TestClient, created: str
    ) -> None:
        """Ctrl+K și câmpul de căutare sunt al doilea drum către el."""
        assert created in names_in(api, {"q": "Zeta", "page": 1, "pageSize": 8})
        assert created in names_in(api, {"q": "zeta nouă", "page": 1, "pageSize": 20})
        # Și fără diacritice, cum tastează majoritatea.
        assert created in names_in(api, {"q": "zeta noua", "page": 1, "pageSize": 20})

    def test_the_page_size_the_screens_ask_for_is_actually_accepted(
        self, api: TestClient, created: str
    ) -> None:
        """`pageSize=200` este chiar maximul serverului.

        Este o margine, nu o valoare comodă: peste ea răspunsul este `422`, iar
        atunci selectorul ar rămâne gol cu totul — nu doar fără clientul nou.
        Testul o fixează, ca nimeni să nu coboare maximul fără să vadă cine cere.
        """
        assert api.get(URL, params={"pageSize": 200}).status_code == 200
        assert api.get(URL, params={"pageSize": 201}).status_code == 422

    def test_it_can_receive_a_document_right_away(self, api: TestClient, created: str) -> None:
        """Drumul întreg din sesizare: creez clientul, apoi îi urc un document.

        Fără el, „apare în listă" ar fi putut fi adevărat și inutil.
        """
        listed = api.get(URL, params={"pageSize": 200}).json()["items"]
        client_id = next(item["id"] for item in listed if item["name"] == created)

        answer = api.post(
            "/api/v1/documents/upload",
            files={
                "file": ("factura.pdf", b"%PDF-1.7\n" + b"0" * 600 + b"\n%%EOF", "application/pdf")
            },
            data={"clientId": client_id},
        )

        assert answer.status_code == 201, answer.text
        assert answer.json()["clientId"] == client_id
