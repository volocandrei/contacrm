"""Fiecare rută a aplicației, întrebată fără sesiune (§72, §80).

**De ce încă un sweep.** Există deja verificări per modul — documente, integrări,
perioade — și fiecare își face treaba pe zona ei. Ce lipsea era unul **global**.
Modulul de termene, scris recent, nu era acoperit de niciunul dintre ele: nu
pentru că cineva ar fi decis că nu are nevoie, ci pentru că sweep-urile per modul
nu observă modulele care nu existau când au fost scrise.

**Cum funcționează.** Lista de rute se citește din aplicație, nu din memoria
cuiva. O rută nouă intră automat în verificare. Dacă răspunde altfel decât 401
fără sesiune, testul cade și obligă pe cineva să scrie explicit, mai jos, de ce
are voie să fie publică.

Cele trei zone, și de ce sunt separate:

1. **Restul aplicației** — 401 fără sesiune. Fără excepții tăcute.
2. **Zona publică** — sănătate, autentificare, portalul clientului. Scrisă de
   mână, pentru ca adăugarea unei rute aici să fie o decizie, nu un accident.
3. **Zona de cron** — 404 fără secret. Nu 401: un 401 ar confirma că ruta există,
   iar rutele astea nu au de ce să fie descoperite de nimeni din afară.
"""

from __future__ import annotations

import uuid

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.conftest import requires_db

pytestmark = requires_db

#: Rutele care răspund **fără sesiune**, deliberat.
#:
#: - sănătatea: o citește load balancer-ul, care nu are cont;
#: - `login`: nu ai cum să te autentifici ca să te poți autentifica;
#: - `logout`: șterge cookie-uri; cerut fără sesiune, nu are ce refuza;
#: - portalul: clientul are un token în link, nu un cont în aplicație (§27 —
#:   tokenul stă în cale, nu în query string).
#:
#: `auth/refresh` **nu** este aici: fără cookie de reîmprospătare răspunde 401,
#: ca orice altă rută, și așa trebuie să rămână.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health/info"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        # Starea workerului: o citeste monitorizarea externa, care nu are cont.
        # Nu spune nimic despre date — doar daca mai proceseaza cineva.
        ("GET", "/health/workers"),
        ("GET", "/api/v1/health/workers"),
        ("GET", "/api/v1/health/info"),
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/health/ready"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/portal/{token}"),
        ("POST", "/api/v1/portal/{token}"),
    }
)

#: Rutele pornite de un cron, nu de un om. Se legitimează cu `CRON_SECRET` într-un
#: antet, nu cu o sesiune, și sunt invizibile fără el.
CRON_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/internal/daily-digest"),
        ("GET", "/api/v1/internal/reminders"),
        ("GET", "/api/v1/internal/run-queue"),
    }
)


def declared_routes(client: TestClient) -> set[tuple[str, str]]:
    """Toate rutele aplicației, cu prefixele aplicate.

    Se merge pe arborele **real** de rutare, nu pe schema OpenAPI: rutele de cron
    sunt scoase din schemă (`include_in_schema=False`), iar un sweep citit din
    OpenAPI ar fi trecut exact peste ele.

    Umblatul prin `original_router` atinge structura internă a FastAPI. Dacă ea se
    schimbă, descoperirea se golește — de aceea fiecare test de mai jos verifică
    întâi că a găsit ceva: un sweep care nu descoperă nicio rută trece oricând.
    """

    def walk(node: object, prefix: str) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for route in getattr(node, "routes", []):
            if isinstance(route, APIRoute):
                found |= {
                    (method, prefix + route.path)
                    for method in (route.methods or set()) - {"HEAD", "OPTIONS"}
                }
                continue
            inner = getattr(route, "original_router", None)
            if inner is None:
                continue
            context = getattr(route, "include_context", None)
            found |= walk(inner, prefix + (getattr(context, "prefix", "") or ""))
        return found

    return walk(client.app, "")


def concrete(path: str) -> str:
    """Calea cu parametrii înlocuiți cu valori valide ca formă, dar inexistente.

    Ce se verifică aici este poarta, nu ce e dincolo de ea: refuzul trebuie să
    vină înainte ca aplicația să se uite dacă id-ul chiar există.
    """
    while "{" in path:
        start = path.index("{")
        end = path.index("}", start)
        name = path[start + 1 : end]
        value = "2026-08" if "month" in name else str(uuid.uuid4())
        path = path[:start] + value + path[end + 1 :]
    return path


def test_nothing_answers_without_a_session_except_the_declared_list(api: TestClient) -> None:
    """Singura listă de excepții este cea de mai sus.

    Testul nu întreabă „ruta asta cere sesiune?" pentru rutele pe care le știm; el
    întreabă **care rute nu cer**, și compară răspunsul aplicației cu lista scrisă
    de om. O rută nouă lăsată din greșeală deschisă apare aici, nu în producție.
    """
    routes = declared_routes(api)
    assert len(routes) >= 100, f"descoperire suspect de mică: {len(routes)}"

    open_routes = {
        (method, path)
        for method, path in routes
        if api.request(method, concrete(path)).status_code != 401
    }

    assert open_routes == PUBLIC_ROUTES | CRON_ROUTES


def test_the_cron_routes_are_invisible_without_the_secret(api: TestClient) -> None:
    """404, nu 401: un 401 ar spune „ruta există, mai încearcă"."""
    assert declared_routes(api) >= CRON_ROUTES

    for method, path in CRON_ROUTES:
        assert api.request(method, path).status_code == 404, path
