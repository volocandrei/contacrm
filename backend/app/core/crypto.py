"""Criptarea secretelor care trebuie să supraviețuiască repornirii.

Un singur lucru intră azi pe aici: **refresh tokenul Microsoft**. Spre deosebire
de parole, el nu poate fi stocat hash-uit — trebuie folosit, deci trebuie citit
înapoi. Iar ce poate fi citit înapoi dintr-un dump de bază de date dă acces la
OneDrive-ul cabinetului, adică la documentele tuturor clienților lui.

**Cheia este separată de `SECRET_KEY`, deliberat.** Ar fi fost mai comod să o
derivăm de acolo, dar `SECRET_KEY` se rotește: exact după o scurgere, adică exact
în momentul în care nimeni nu vrea să descopere că a pierdut și legăturile cu
OneDrive. Două secrete cu cicluri de viață diferite stau în două locuri diferite.

Fără cheie, nu se stochează nimic: conectarea unui drive refuză cu un mesaj
explicit, în loc să scrie tokenul în clar „temporar".
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenEncryptionUnavailableError(RuntimeError):
    """Nu există cheie de criptare configurată."""


class TokenDecryptionError(RuntimeError):
    """Valoarea stocată nu poate fi descifrată cu cheia de acum."""


@lru_cache
def _cipher() -> Fernet:
    key = settings.drive_token_key.strip()
    if not key:
        raise TokenEncryptionUnavailableError(
            "DRIVE_TOKEN_KEY nu este configurată. Generează una cu:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise TokenEncryptionUnavailableError(
            "DRIVE_TOKEN_KEY nu este o cheie Fernet validă (32 de octeți, base64 urlsafe)."
        ) from exc


def encryption_available() -> bool:
    """Se poate conecta un drive? Ecranul de administrare întreabă înainte să ofere."""
    try:
        _cipher()
    except TokenEncryptionUnavailableError:
        return False
    return True


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Descifrează, sau explică de ce nu se poate.

    Cheia schimbată este cazul obișnuit, și trebuie să iasă ca mesaj limpede:
    legătura cu OneDrive se reface printr-o reconectare, nu prin ghicit.
    """
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError(
            "Tokenul stocat nu poate fi descifrat cu DRIVE_TOKEN_KEY de acum. "
            "Reconectează contul Microsoft."
        ) from exc
