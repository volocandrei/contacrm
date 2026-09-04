"""Preluarea facturilor electronice din SPV-ul ANAF (M11).

`base` ține contractul, `client` singura parte care atinge rețeaua, `archive`
despachetarea arhivei primite, `sync` tot ce se întâmplă cu facturile aduse.
Restul aplicației vede doar `AnafClient` și `AnafSyncService`.

Faza aceasta **doar citește**. Trimiterea facturilor (`/upload`, `stareMesaj`)
nu este implementată: a emite un document fiscal în numele unui client este altă
răspundere decât a-l descărca pe cel deja emis.
"""

from app.services.anaf.archive import AnafArchive, AnafArchiveError, unpack
from app.services.anaf.base import (
    AnafAuthError,
    AnafClient,
    AnafError,
    AnafMandateError,
    AnafTokens,
    SpvMessage,
    SpvPage,
)
from app.services.anaf.sync import AnafSyncResult, AnafSyncService, MandateResult

__all__ = [
    "AnafArchive",
    "AnafArchiveError",
    "AnafAuthError",
    "AnafClient",
    "AnafError",
    "AnafMandateError",
    "AnafSyncResult",
    "AnafSyncService",
    "AnafTokens",
    "MandateResult",
    "SpvMessage",
    "SpvPage",
    "unpack",
]
