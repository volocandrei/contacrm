"""Reguli de configurare care trebuie să oprească pornirea, nu să treacă tăcut."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def _settings(**overrides: object) -> Settings:
    # `_env_file=None` izolează testul de `.env`-ul local al dezvoltatorului.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_keep_documents_on_this_machine() -> None:
    """R2: în development niciun document nu pleacă la un provider extern."""
    settings = _settings()
    assert settings.ocr_provider == "mock"
    assert settings.ai_provider == "mock"
    assert settings.notifications_enabled is False
    assert settings.retention_enabled is False


def test_cors_rejects_wildcard() -> None:
    with pytest.raises(ValidationError):
        _settings(cors_allowed_origins="*")

    with pytest.raises(ValidationError):
        _settings(cors_allowed_origins="http://localhost:5173,https://*.exemplu.ro")


def test_cors_origins_are_parsed_and_trimmed() -> None:
    settings = _settings(cors_allowed_origins="http://a.test, http://b.test ,")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_production_refuses_default_secret_key() -> None:
    settings = _settings(environment=Environment.PRODUCTION)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.assert_production_ready()


def test_production_accepts_a_real_secret_key() -> None:
    settings = _settings(environment=Environment.PRODUCTION, secret_key="x" * 64)
    settings.assert_production_ready()


def test_production_refuses_inconsistent_ocr_and_ai_providers() -> None:
    settings = _settings(
        environment=Environment.PRODUCTION,
        secret_key="x" * 64,
        ocr_provider="google_docai",
        ai_provider="mock",
    )
    with pytest.raises(RuntimeError, match="inconsistentă"):
        settings.assert_production_ready()


def test_api_schema_is_hidden_in_production() -> None:
    assert _settings(environment=Environment.PRODUCTION).docs_enabled is False
    assert _settings(environment=Environment.DEVELOPMENT).docs_enabled is True


def test_upload_limits_are_derived_not_duplicated() -> None:
    settings = _settings(max_upload_size_mb=25)
    assert settings.max_upload_size_bytes == 26_214_400
    assert "application/pdf" in settings.allowed_mime_type_set
