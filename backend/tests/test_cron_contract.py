"""Ce declară `vercel.json` și ce așteaptă codul trebuie să spună același lucru.

**Ce apără.** Pe Vercel nu există niciun proces care să pornească singur. Tot ce
se întâmplă fără ca cineva să apese ceva se întâmplă pentru că un cron cheamă o
rută din `/internal`. O rută fără cron nu dă eroare, nu apare în loguri și nu
lipsește din interfață: pur și simplu nu se execută niciodată.

Pentru un cabinet, asta înseamnă reamintiri care nu pleacă la clienți — adică
exact lucrul pentru care a fost cumpărată aplicația, tăcut, la nesfârșit.

Al doilea lucru păzit aici este acordul dintre intervalul cronului și pragul de
la care workerul este declarat mort (`CRON_TICK_SECONDS`). Sunt în două fișiere
diferite; dacă pleacă unul fără celălalt, alarma minte — vezi
`test_heartbeat_threshold.py`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.config import CRON_TICK_SECONDS, REPO_ROOT, settings
from app.main import create_app

VERCEL_JSON = REPO_ROOT / "vercel.json"


def cron_entries() -> list[dict[str, str]]:
    config = json.loads(Path(VERCEL_JSON).read_text(encoding="utf-8"))
    return list(config.get("crons", []))


def mounted_paths(router: object, prefix: str = "") -> Iterator[str]:
    """Toate căile pe care le răspunde aplicația, cu prefixele aplicate.

    FastAPI include routerele **leneș**: `app.routes` conține obiecte care
    păstrează routerul original și prefixul cu care a fost montat, nu rutele
    desfăcute. Se coboară prin ele, ca să obținem calea publică — aceeași pe care
    o scrie cineva în `vercel.json`.
    """
    for route in getattr(router, "routes", []):
        context = getattr(route, "include_context", None)
        if context is not None:
            yield from mounted_paths(context.included_router, prefix + context.prefix)
        elif isinstance(route, APIRoute):
            yield prefix + route.path


def internal_routes() -> set[str]:
    """Rutele care nu au cine să le cheme din interfață.

    Se citesc din aplicația construită, nu dintr-o listă scrisă de mână: o rută
    nouă intră singură în verificare, ceea ce este tot rostul acestui fișier.
    """
    prefix = f"{settings.api_v1_prefix}/internal"
    return {path for path in mounted_paths(create_app().router) if path.startswith(prefix)}


class TestEveryScheduledRouteIsScheduled:
    def test_there_are_internal_routes_to_check(self) -> None:
        """Contra-proba: dacă prefixul s-ar schimba, restul ar trece pe gol."""
        assert internal_routes()

    @pytest.mark.parametrize("path", sorted(internal_routes()))
    def test_the_route_has_a_cron(self, path: str) -> None:
        """Testul pentru care există fișierul."""
        declared = {entry["path"] for entry in cron_entries()}
        assert path in declared, (
            f"{path} nu are cron în vercel.json. Pe Vercel nu există proces "
            "continuu: o rută internă fără cron nu se execută niciodată, fără "
            "nicio eroare nicăieri."
        )


class TestEveryCronPointsSomewhere:
    def test_no_cron_calls_a_route_that_does_not_exist(self) -> None:
        """Cealaltă direcție: o rută redenumită ar lăsa cronul să sune în gol.

        Vercel ar cere calea, ar primi 404 și ar trece mai departe. Nimic nu ar
        spune că munca nu s-a făcut.
        """
        routes = internal_routes()
        for entry in cron_entries():
            assert entry["path"] in routes, f"cronul {entry['path']} nu duce nicăieri"


class TestTheQueueTickMatchesTheCode:
    def test_the_heartbeat_threshold_is_built_for_this_interval(self) -> None:
        """`CRON_TICK_SECONDS` și `*/5 * * * *` sunt în fișiere diferite."""
        queue = f"{settings.api_v1_prefix}/internal/run-queue"
        schedules = [entry["schedule"] for entry in cron_entries() if entry["path"] == queue]

        assert schedules == ["*/5 * * * *"], (
            "Dacă intervalul cozii se schimbă, CRON_TICK_SECONDS din "
            "app/core/config.py trebuie schimbat odată cu el — altfel pragul "
            "workerului rămâne calculat pentru alt ritm."
        )
        minutes, _ = schedules[0].split(" ", 1)
        assert int(minutes.removeprefix("*/")) * 60 == CRON_TICK_SECONDS
