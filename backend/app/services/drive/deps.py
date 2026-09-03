"""Clientul de drive, ca dependență.

Stă separat de `microsoft.py` pentru ca testele să îl poată înlocui cu unul fals
prin `app.dependency_overrides`, exact cum înlocuiesc sesiunea de bază de date.
Fără asta, orice test de rută ar cere credențiale Microsoft.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.services.drive.base import DriveClient
from app.services.drive.microsoft import MicrosoftGraphClient


@lru_cache
def _client() -> MicrosoftGraphClient:
    return MicrosoftGraphClient(
        client_id=settings.ms_client_id,
        client_secret=settings.ms_client_secret,
        tenant=settings.ms_tenant_id,
    )


def get_drive_client() -> DriveClient:
    """Providerul configurat, unul singur pentru tot procesul."""
    return _client()


DriveClientDep = Annotated[DriveClient, Depends(get_drive_client)]
