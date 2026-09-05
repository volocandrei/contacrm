"""Ruta care încheie tranzacția **înainte** de a trimite răspunsul.

**Defectul pe care îl repară.** `get_db` este o dependență cu `yield`, iar în
FastAPI blocul de după `yield` se execută în `request_stack` — un `AsyncExitStack`
care se închide **după** ce răspunsul a plecat spre client (`fastapi/routing.py`:
`await response(scope, receive, send)` stă *înăuntrul* lui). Cu alte cuvinte,
`session.commit()` rula după ce browserul avea deja `200`.

Consecința nu este teoretică. Interfața face exact ce trebuie: după o scriere
reușită invalidează listele și le cere din nou. Cererea aceea pleca la 20-30 ms
după răspuns și, uneori, **ajungea înaintea commit-ului** — deci primea starea de
dinainte. Utilizatorul vedea „am salvat" și, imediat sub, lista neschimbată.

S-a manifestat de două ori în CI, pe Linux, la teste diferite: o sarcină creată
care nu apărea pe kanban, și o cerere de documente după care rândul scria tot
„Necerut". Pe Windows, mai rapid, commit-ul câștiga cursa aproape mereu — de aceea
părea instabilitate de test. Nu era.

**Ce face ruta asta.** Închide tranzacția în interiorul apelului de endpoint, deci
înainte ca octeții răspunsului să plece. Dacă `commit` eșuează, eroarea se ridică
*înainte* de a fi trimis un `200` mincinos și ajunge la handlerele obișnuite.

`get_db` păstrează `rollback` și `close`: acelea au voie să se întâmple după
răspuns, fiindcă nu schimbă ce vede clientul.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session


class CommittingRoute(APIRoute):
    """`APIRoute` care confirmă tranzacția înainte de a trimite răspunsul."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            session: Session | None = getattr(request.state, "db", None)
            # `in_transaction` evită un dus-întors inutil la citiri; nu este o
            # optimizare de dragul ei, ci ține jurnalul bazei curat.
            if session is not None and session.in_transaction():
                session.commit()
            return response

        return handler


__all__ = ["CommittingRoute"]
