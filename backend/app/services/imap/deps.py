"""Clientul IMAP, ca dependență.

Stă separat de implementare pentru ca testele să îl poată înlocui cu unul fals
prin `app.dependency_overrides`, exact ca la Microsoft. Fără asta, orice test de
rută ar cere o cutie poștală adevărată — deci nu s-ar rula niciodată.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.services.imap.base import ImapClient
from app.services.imap.client import ImapMailClient


@lru_cache
def _client() -> ImapMailClient:
    return ImapMailClient()


def get_imap_client() -> ImapClient:
    """Unul singur pentru tot procesul: nu ține conexiuni deschise între apeluri."""
    return _client()


ImapClientDep = Annotated[ImapClient, Depends(get_imap_client)]
