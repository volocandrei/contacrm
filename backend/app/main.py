"""Punctul de intrare al API-ului.

`create_app()` este o fabrică, nu un modul cu efecte secundare la import: testele
construiesc aplicația cu altă configurare fără să atingă starea globală.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "startup",
        environment=settings.environment.value,
        ocr_provider=settings.ocr_provider,
        ai_provider=settings.ai_provider,
        storage_provider=settings.storage_provider,
    )
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        # Schema API nu se publică în producție.
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Originile sunt enumerate explicit; `Settings` refuză caracterul universal.
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # Health-ul stă și în afara prefixului: orchestratorul nu trebuie să știe versiunea API.
    app.include_router(api_router)

    return app


app = create_app()
