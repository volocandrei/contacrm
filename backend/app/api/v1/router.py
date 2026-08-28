"""Agregarea rutelor v1.

Un singur loc care știe ce module compun API-ul. Rutele de business se adaugă aici
pe măsură ce apar (M3: auth, M4: clients, M5: documents…).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
