"""Clientul ANAF, ca dependență.

Stă separat de `client.py` pentru ca testele să îl poată înlocui cu unul fals
prin `app.dependency_overrides`, exact cum înlocuiesc sesiunea de bază de date
sau clientul Microsoft. Fără asta, orice test de rută ar cere certificat digital.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.services.anaf.base import AnafClient
from app.services.anaf.client import AnafApiClient


@lru_cache
def _client() -> AnafApiClient:
    return AnafApiClient(
        client_id=settings.anaf_client_id,
        client_secret=settings.anaf_client_secret,
        environment=settings.anaf_environment,
    )


def get_anaf_client() -> AnafClient:
    """Clientul configurat, unul singur pentru tot procesul."""
    return _client()


AnafClientDep = Annotated[AnafClient, Depends(get_anaf_client)]
