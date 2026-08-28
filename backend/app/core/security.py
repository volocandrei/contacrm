"""Parole și tokenuri.

Parolele: Argon2id, cu parametrii bibliotecii — deliberat nu îi coborâm „ca să
meargă mai repede", pentru că exact costul acela protejează o bază furată.

Tokenurile: JWT semnat HS256. Access-ul este scurt și poartă permisiunile;
refresh-ul este lung, opac pentru client și **stocat doar ca hash** — o bază de
date furată nu trebuie să conțină tokenuri folosibile.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

ALGORITHM: Final = "HS256"
TokenType = Literal["access", "refresh"]

_hasher = PasswordHasher()


# ── Parole ───────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True când parametrii Argon2 s-au întărit de la ultima autentificare."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def dummy_verify() -> None:
    """Consumă timp de hashing pentru un email inexistent.

    Fără asta, durata răspunsului spune atacatorului care emailuri există.
    """
    _hasher.verify(
        _hasher.hash("timing-equalisation"),
        "timing-equalisation",
    )


# ── Tokenuri ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: uuid.UUID
    organization_id: uuid.UUID
    token_type: TokenType
    token_id: str
    expires_at: datetime


class TokenError(Exception):
    """Token absent, expirat, cu semnătură invalidă sau de tipul greșit."""


def _encode(
    subject: uuid.UUID,
    organization_id: uuid.UUID,
    token_type: TokenType,
    lifetime: timedelta,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + lifetime
    token_id = secrets.token_urlsafe(16)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "org": str(organization_id),
        "typ": token_type,
        "jti": token_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), token_id, expires_at


def create_access_token(
    subject: uuid.UUID, organization_id: uuid.UUID, permissions: list[str]
) -> tuple[str, datetime]:
    token, _, expires_at = _encode(
        subject,
        organization_id,
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
        # Permisiunile călătoresc în token ca autorizarea să nu ceară o interogare
        # pe fiecare cerere. Tokenul e scurt, deci o revocare de rol prinde repede.
        {"perms": permissions},
    )
    return token, expires_at


def create_refresh_token(
    subject: uuid.UUID, organization_id: uuid.UUID
) -> tuple[str, str, datetime]:
    """Întoarce (token, token_id, expirare). `token_id` leagă tokenul de rândul din DB."""
    return _encode(
        subject,
        organization_id,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "typ", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        # Un refresh token nu trebuie să treacă niciodată drept access token.
        raise TokenError(f"tip de token neașteptat: {payload.get('typ')!r}")

    try:
        return TokenClaims(
            subject=uuid.UUID(payload["sub"]),
            organization_id=uuid.UUID(payload["org"]),
            token_type=expected_type,
            token_id=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("payload invalid") from exc


def token_permissions(token: str) -> list[str]:
    """Permisiunile dintr-un access token deja validat."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    perms = payload.get("perms", [])
    return [str(p) for p in perms] if isinstance(perms, list) else []


def hash_token(token: str) -> str:
    """Refresh tokenurile se stochează hash-uite, niciodată în clar."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
