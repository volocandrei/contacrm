"""Parole și tokenuri — testabile fără bază de date."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    ALGORITHM,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    token_permissions,
    verify_password,
)


class TestPasswords:
    def test_hash_is_argon2id_and_verifies(self) -> None:
        digest = hash_password("parola-corecta")
        assert digest.startswith("$argon2id$")
        assert verify_password("parola-corecta", digest)

    def test_wrong_password_is_rejected(self) -> None:
        assert not verify_password("altceva", hash_password("parola-corecta"))

    def test_same_password_hashes_differently(self) -> None:
        """Sare unică per parolă: două conturi cu aceeași parolă nu se văd egale."""
        assert hash_password("aceeasi") != hash_password("aceeasi")

    def test_malformed_hash_does_not_raise(self) -> None:
        assert not verify_password("orice", "nu-este-un-hash")


class TestTokens:
    def test_access_token_carries_permissions(self) -> None:
        user_id, org_id = uuid.uuid4(), uuid.uuid4()
        token, expires = create_access_token(user_id, org_id, ["documents:read"])

        claims = decode_token(token, "access")
        assert claims.subject == user_id
        assert claims.organization_id == org_id
        assert token_permissions(token) == ["documents:read"]
        assert expires > datetime.now(UTC)

    def test_refresh_token_is_not_accepted_as_access_token(self) -> None:
        """Confuzia de tip ar transforma un token de 14 zile într-unul de acces."""
        token, _, _ = create_refresh_token(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(TokenError):
            decode_token(token, "access")

    def test_access_token_is_not_accepted_as_refresh_token(self) -> None:
        token, _ = create_access_token(uuid.uuid4(), uuid.uuid4(), [])
        with pytest.raises(TokenError):
            decode_token(token, "refresh")

    def test_expired_token_is_rejected(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "org": str(uuid.uuid4()),
                "typ": "access",
                "jti": "x",
                "exp": int(past.timestamp()),
            },
            settings.secret_key,
            algorithm=ALGORITHM,
        )
        with pytest.raises(TokenError):
            decode_token(forged, "access")

    def test_token_signed_with_another_key_is_rejected(self) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "org": str(uuid.uuid4()),
                "typ": "access",
                "jti": "x",
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            "cheia-atacatorului",
            algorithm=ALGORITHM,
        )
        with pytest.raises(TokenError):
            decode_token(forged, "access")

    def test_unsigned_token_is_rejected(self) -> None:
        """`alg: none` este atacul clasic pe JWT."""
        forged = jwt.encode({"sub": "x", "typ": "access", "jti": "x"}, "", algorithm="none")
        with pytest.raises(TokenError):
            decode_token(forged, "access")

    def test_refresh_tokens_are_stored_hashed(self) -> None:
        token, _, _ = create_refresh_token(uuid.uuid4(), uuid.uuid4())
        digest = hash_token(token)
        assert digest != token
        assert len(digest) == 64
        assert hash_token(token) == digest

    def test_two_tokens_never_share_an_id(self) -> None:
        _, first, _ = create_refresh_token(uuid.uuid4(), uuid.uuid4())
        _, second, _ = create_refresh_token(uuid.uuid4(), uuid.uuid4())
        assert first != second
