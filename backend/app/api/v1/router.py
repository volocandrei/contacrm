"""Agregarea rutelor v1.

Un singur loc care știe ce module compun API-ul. Rutele de business se adaugă aici
pe măsură ce apar (M5: documents plus contoarele din bara laterală;
M6: perioadele și restul tabloului de bord).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    anaf,
    audit,
    auth,
    clients,
    dashboard,
    documents,
    health,
    integrations,
    internal,
    periods,
    reports,
    settings,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(clients.router)
api_router.include_router(dashboard.router)
api_router.include_router(documents.router)
api_router.include_router(integrations.router)
api_router.include_router(anaf.router)
api_router.include_router(periods.router)
api_router.include_router(reports.router)
api_router.include_router(settings.router)
api_router.include_router(tasks.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
# Ruta de cron nu este o rută de utilizator: fără sesiune, fără organizație, fără
# loc în navigație. Stă totuși sub același prefix, ca să treacă prin aceleași
# middleware-uri (request id, loguri) ca orice altceva.
api_router.include_router(internal.router)
