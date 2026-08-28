"""Health checks.

Trei endpoint-uri distincte, pentru că răspund la trei întrebări diferite:

- `/health/live`  — procesul răspunde? (orchestratorul îl repornește dacă nu)
- `/health/ready` — poate servi trafic? (verifică dependențele; 503 dacă nu)
- `/health/info`  — ce versiune și ce configurare rulează? (fără secrete)
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.db import check_database
from app.schemas.common import ApiModel

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(ApiModel):
    status: str


class ReadinessResponse(ApiModel):
    status: str
    database: bool


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


@router.get("/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    database_ok = check_database()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if database_ok else "degraded", database=database_ok)


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
