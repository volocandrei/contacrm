"""Contractul cu un serviciu de fișiere în cloud.

Aceeași disciplină ca la stocare (ADR-004) și extracție (ADR-005): serviciul de
sincronizare nu știe niciodată că în spate stă Microsoft Graph. Vorbește doar cu
protocolul de aici.

Motivul nu este eleganța, ci testabilitatea. Nu putem chema Microsoft dintr-un
test — nici din CI, nici de pe laptop — deci tot ce contează trebuie să poată fi
exercitat cu o implementare falsă. Ce rămâne neverificat este strict clientul HTTP
real, care este deliberat subțire: construiește URL-uri și citește JSON.

**Ce nu face acest strat:** nu scrie nimic înapoi în OneDrive. Documentele
clienților rămân exact cum le-au pus ei — noi doar citim. Un sistem care
redenumește fișierele în dosarul altcuiva este un sistem care, într-o zi, le
strică.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class DriveAccount:
    """Cine este contul conectat. Se afișează, nu se folosește la autorizare."""

    email: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class DriveItem:
    """Un fișier sau un dosar, așa cum îl vede Graph."""

    id: str
    name: str
    #: Calea lizibilă, pentru ecran. Poate lipsi la elementele întoarse de delta.
    path: str
    drive_id: str
    is_folder: bool
    size: int = 0
    #: Ce declară Microsoft. Ca peste tot, nu îl credem: tipul real se stabilește
    #: din primii octeți la încărcare (§50).
    mime_type: str | None = None
    modified_at: datetime | None = None
    #: `True` când elementul a fost **șters** din dosar. Nu ștergem nimic la noi —
    #: un document ajuns în contabilitate rămâne (R8) — dar nu îl reluăm nici.
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class DeltaPage:
    """Ce s-a schimbat într-un dosar de la ultima citire."""

    items: tuple[DriveItem, ...] = ()
    #: Tokenul de dat la următoarea cerere. `None` doar dacă providerul nu îl dă,
    #: caz în care următorul tur recitește dosarul.
    delta_token: str | None = None
    #: Mai sunt pagini de citit acum. Un dosar cu un an de documente nu trebuie să
    #: blocheze coada la prima conectare.
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class DriveTokens:
    """Ce întoarce Microsoft după consimțământ."""

    access_token: str
    refresh_token: str
    scopes: tuple[str, ...] = field(default_factory=tuple)


class DriveError(Exception):
    """Providerul nu a putut răspunde. Poartă dacă merită reîncercat."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class DriveAuthError(DriveError):
    """Consimțământul nu mai este valabil: trebuie reconectat un om.

    Se ține separat pentru că este singura eroare pe care o reîncercare nu o
    rezolvă niciodată, iar remediul nu este tehnic — cineva trebuie să apese
    „Conectează" din nou.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@runtime_checkable
class DriveClient(Protocol):
    """Ce trebuie să știe orice provider de fișiere în cloud."""

    def exchange_code(self, code: str, redirect_uri: str) -> DriveTokens:
        """Schimbă codul de consimțământ pe tokenuri."""
        ...

    def account(self, refresh_token: str) -> DriveAccount:
        """Cine este contul din spatele tokenului."""
        ...

    def list_folders(self, refresh_token: str, *, parent_id: str | None) -> tuple[DriveItem, ...]:
        """Subdosarele unui dosar, ca administratorul să poată alege.

        `parent_id=None` înseamnă rădăcina drive-ului. Se întorc **doar** dosare:
        ecranul de mapare nu are ce face cu fișiere.
        """
        ...

    def delta(
        self, refresh_token: str, *, drive_id: str, item_id: str, token: str | None, limit: int
    ) -> DeltaPage:
        """Ce s-a schimbat în dosar de la `token` încoace."""
        ...

    def download(self, refresh_token: str, *, drive_id: str, item_id: str) -> BinaryIO:
        """Conținutul unui fișier, ca flux.

        Flux, nu `bytes`: fișierul merge direct în `ValidatingReader`, care îi
        calculează dimensiunea și hash-ul în timp ce trece. Un PDF de 20 MB nu
        are de ce să existe întreg în memorie.
        """
        ...
