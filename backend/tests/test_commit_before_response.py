"""Tranzacția se încheie înainte ca răspunsul să plece.

**Defectul.** `get_db` era o dependență cu `yield`, iar în FastAPI blocul de după
`yield` se execută într-un `AsyncExitStack` care se închide **după** ce răspunsul
a plecat spre client. `session.commit()` rula, așadar, după ce browserul avea deja
`200` — iar o cerere trimisă imediat după putea citi starea de dinainte.

Interfața face exact ce trebuie: după o scriere reușită invalidează listele și le
cere din nou, la 20-30 ms. Uneori cererea aceea ajungea înaintea commit-ului, iar
omul vedea „am salvat" și, sub, lista neschimbată.

**De ce nu se poate reproduce într-un test obișnuit.** `TestClient` cheamă
aplicația ASGI și așteaptă terminarea completă a apelului — inclusiv închiderea
dependențelor — înainte să întoarcă răspunsul. Cursa există doar cu un server
adevărat și doi clienți care se succed rapid: exact ce face browserul. De aceea
s-a văzut numai în CI, pe Linux, la două teste E2E diferite.

Ce se poate verifica aici este **montajul**: fiecare rută trece prin ruta care
confirmă la timp, și niciun router nou nu poate uita.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.api.route import CommittingRoute
from app.api.v1.router import api_router


def test_every_route_commits_before_answering() -> None:
    """Un router nou care uită `route_class` reintroduce cursa în tăcere."""
    plain = [
        route.path
        for route in api_router.routes
        if isinstance(route, APIRoute) and not isinstance(route, CommittingRoute)
    ]

    assert plain == [], (
        "rute care confirmă tranzacția abia după ce au răspuns: "
        + ", ".join(sorted(plain))
        + ". Adaugă `route_class=CommittingRoute` pe routerul lor."
    )


def test_the_dependency_no_longer_commits_on_teardown() -> None:
    """Dublul commit n-ar strica nimic; cel din `get_db` însă ar rămâne târziu.

    Dacă cineva îl pune la loc „ca să fie sigur", cursa revine pentru rutele care
    nu mai ajung la `CommittingRoute` — și revine tăcut.
    """
    import inspect

    from app.core.db import get_db

    body = inspect.getsource(get_db)
    after_yield = body.split("yield session", 1)[1]

    assert "commit" not in after_yield, (
        "`get_db` confirmă din nou după `yield`, adică după ce răspunsul a plecat"
    )


def test_the_session_is_reachable_from_the_route() -> None:
    """`CommittingRoute` o găsește pe `request.state`; fără asta n-ar avea ce confirma."""
    import inspect

    from app.core.db import get_db

    assert "request.state.db = session" in inspect.getsource(get_db)
