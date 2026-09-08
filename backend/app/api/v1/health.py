"""Health checks.

Patru endpoint-uri distincte, pentru că răspund la patru întrebări diferite:

- `/health/live`    — procesul răspunde? (orchestratorul îl repornește dacă nu)
- `/health/ready`   — **instanța asta** poate servi trafic? (503 dacă nu)
- `/health/workers` — mai procesează cineva documentele? (503 dacă nu)
- `/health/info`    — ce versiune și ce configurare rulează? (fără secrete)

**De ce workerul are endpoint separat, și nu intră în `ready`.**

`/health/ready` este citit de load balancer ca să decidă dacă trimite cereri
acestei instanțe. Dacă workerul mort ar face `ready` să răspundă 503, load
balancerul ar scoate din rotație **toate** instanțele de API — o problemă de
procesare s-ar transforma într-o cădere totală, exact în momentul în care
cabinetul are nevoie să vadă ecranul cozii ca să înțeleagă ce se întâmplă.

Un worker mort trebuie să **sune un om**, nu să oprească aplicația. De aceea:

- `ready` = pot servi eu? (aplicație + bază de date);
- `workers` = mai procesează cineva? — endpointul pe care îl urmărește
  monitorizarea externă și care declanșează alerta.

Starea workerului apare **și** în corpul lui `ready`, ca cine se uită acolo să o
vadă, dar fără să influențeze codul HTTP. Vezi
`docs/PRODUCTION_MONITORING.md` pentru ce trebuie configurat.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.route import CommittingRoute
from app.core.config import settings
from app.core.db import check_database, session_scope
from app.core.logging import get_logger
from app.schemas.common import ApiModel
from app.services import worker_health

logger = get_logger(__name__)

router = APIRouter(route_class=CommittingRoute, prefix="/health", tags=["health"])


class LivenessResponse(ApiModel):
    status: str


class WorkerStatusOut(ApiModel):
    """Ce știm despre worker, în cuvinte pe care le poate citi o alertă."""

    name: str
    healthy: bool
    #: `None` = nu a raportat niciodată. Altceva decât „a raportat demult".
    age_seconds: int | None
    timeout_seconds: int
    #: Care mașină și care proces — util când sunt mai multe.
    hostname: str | None
    detail: str


class ReadinessResponse(ApiModel):
    """Poate **instanța asta** să servească cereri?

    `worker` este informativ aici: nu schimbă codul HTTP. Motivul, în capul
    fișierului.
    """

    status: str
    database: bool
    worker: WorkerStatusOut | None = None


class WorkersResponse(ApiModel):
    status: str
    workers: list[WorkerStatusOut]


class InfoResponse(ApiModel):
    app_name: str
    environment: str
    api_version: str
    default_locale: str
    default_timezone: str
    ocr_provider: str
    ai_provider: str
    storage_provider: str


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


def _worker_out(state: worker_health.WorkerStatus) -> WorkerStatusOut:
    return WorkerStatusOut(
        name=state.name,
        healthy=state.is_fresh,
        age_seconds=state.age_seconds,
        timeout_seconds=state.timeout_seconds,
        hostname=state.hostname,
        detail=state.describe(),
    )


def _worker_state() -> worker_health.WorkerStatus | None:
    """Starea workerului, sau `None` dacă nu se poate afla.

    **Sesiunea se deschide aici, nu prin `Depends`.** O dependență de sesiune ar
    fi rulat **înaintea** funcției: cu baza căzută, cererea ar fi murit în
    dependență și ar fi ieșit 500 cu urmă de excepție, în loc de 503-ul controlat
    pe care îl așteaptă load balancerul. Exact asta s-a întâmplat prima oară.

    Rutele de sănătate trebuie să răspundă **mai ales** când ceva este stricat.
    """
    try:
        with session_scope() as session:
            return worker_health.status(session)
    except Exception:
        logger.warning("worker_status_unavailable", exc_info=True)
        return None


@router.get("/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    """Poate instanța asta să servească trafic?

    503 **doar** pentru ce o împiedică pe ea să răspundă. Starea workerului se
    raportează, dar nu scoate API-ul din rotație — vezi capul fișierului.
    """
    database_ok = check_database()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # Fără bază nu se poate citi nici starea workerului; a spune „worker
        # sănătos" în clipa asta ar fi o afirmație pe care nu o putem susține.
        return ReadinessResponse(status="degraded", database=False, worker=None)

    state = _worker_state()
    return ReadinessResponse(
        status="ok",
        database=True,
        worker=None if state is None else _worker_out(state),
    )


@router.get("/workers", response_model=WorkersResponse)
def workers(response: Response) -> WorkersResponse:
    """Mai procesează cineva documentele?

    **Acesta este endpointul pe care îl urmărește monitorizarea externă.** 503
    înseamnă: documentele intră și nu le mai ia nimeni. Nu înseamnă că aplicația
    a căzut — ecranele merg mai departe, iar coada se vede în
    *Documente → În procesare*.

    Un worker care nu a raportat **niciodată** este tot 503: o instalare în care
    workerul nu a fost pornit deloc arată exact ce este.
    """
    state = _worker_state()
    if state is None:
        # Nu se poate citi starea — cel mai probabil baza este jos. Nu se
        # raportează „sănătos": tăcerea aici ar fi cea mai proastă minciună.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return WorkersResponse(status="unknown", workers=[])

    if not state.is_fresh:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return WorkersResponse(
        status="ok" if state.is_fresh else "stale",
        workers=[_worker_out(state)],
    )


@router.get("/info", response_model=InfoResponse)
def info() -> InfoResponse:
    """Doar valori neconfidențiale — niciun secret nu iese pe aici."""
    return InfoResponse(
        app_name=settings.app_name,
        environment=settings.environment.value,
        api_version="v1",
        default_locale=settings.default_locale,
        default_timezone=settings.default_timezone,
        ocr_provider=settings.ocr_provider,
        ai_provider=settings.ai_provider,
        storage_provider=settings.storage_provider,
    )
