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


@pytest.mark.parametrize("key", ["", "   ", "abc", "x" * 31])
def test_production_refuses_a_secret_key_too_short_to_sign_with(key: str) -> None:
    """Cheia asta semnează tokenurile de acces. Scurtă, oricine își face unul.

    Verificarea se uita doar la valoarea implicită, deci `SECRET_KEY=` gol trecea:
    șirul gol nu începe cu „dev-only". Pe multe platforme o variabilă nedefinită
    ajunge la proces exact așa — ca șir gol.
    """
    settings = _settings(
        environment=Environment.PRODUCTION, secret_key=key, ocr_provider="pdf_text"
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.assert_production_ready()


def test_production_accepts_a_real_secret_key() -> None:
    settings = _settings(
        environment=Environment.PRODUCTION, secret_key="x" * 64, ocr_provider="pdf_text"
    )
    settings.assert_production_ready()


def test_production_refuses_the_provider_that_invents_data() -> None:
    """`mock` scrie furnizori, sume și date inventate în câmpuri contabile.

    Pe ecranul de verificare arată exact ca niște valori citite de pe document —
    cu proveniență și scor de încredere — deci operatorul nu are cum să le
    distingă. Pentru demonstrații rămâne `staging`.
    """
    settings = _settings(environment=Environment.PRODUCTION, secret_key="x" * 64)
    assert settings.ocr_provider == "mock"

    with pytest.raises(RuntimeError, match="inventează"):
        settings.assert_production_ready()


def test_a_demonstration_environment_is_not_held_to_the_production_rules() -> None:
    """Ruta de scăpare pe care o indică mesajul de mai sus trebuie să existe.

    Altfel nu ar mai fi niciun mod de a arăta aplicația fără documente reale, iar
    presiunea ar fi să se pună `ENVIRONMENT=production` cu `mock` oricum.
    """
    assert _settings(environment=Environment.STAGING).is_production is False


def test_production_refuses_inconsistent_ocr_and_ai_providers() -> None:
    """Un OCR bazat pe model, cu AI simulat, este o configurare care minte.

    Numele este atribuit **după** construire, ocolind validatorul: azi nu există
    niciun provider bazat pe model, deci nicio valoare acceptabilă nu ar putea
    declanșa regula. Verificarea trebuie totuși să existe și să funcționeze
    înainte ca un astfel de provider să apară (Faza 2), nu după.
    """
    settings = _settings(environment=Environment.PRODUCTION, secret_key="x" * 64)
    settings.ocr_provider = "google_docai"

    with pytest.raises(RuntimeError, match="inconsistentă"):
        settings.assert_production_ready()


def test_an_unimplemented_extraction_provider_stops_startup() -> None:
    """Altfel eșecul apare abia în worker, la primul document — adică după ce
    cineva a crezut că sistemul funcționează."""
    with pytest.raises(ValidationError):
        _settings(ocr_provider="google_docai")


def test_reading_a_pdf_locally_is_not_an_inconsistent_configuration() -> None:
    """`pdf_text` nu este un model: nu are ce să fie inconsistent cu `AI_PROVIDER`."""
    settings = _settings(
        environment=Environment.PRODUCTION, secret_key="x" * 64, ocr_provider="pdf_text"
    )
    settings.assert_production_ready()


def test_api_schema_is_hidden_in_production() -> None:
    assert _settings(environment=Environment.PRODUCTION).docs_enabled is False
    assert _settings(environment=Environment.DEVELOPMENT).docs_enabled is True


def test_upload_limits_are_derived_not_duplicated() -> None:
    settings = _settings(max_upload_size_mb=25)
    assert settings.max_upload_size_bytes == 26_214_400
    assert "application/pdf" in settings.allowed_mime_type_set


def test_the_cron_route_is_off_until_a_secret_exists() -> None:
    """Un endpoint care executa munca nu porneste deschis."""
    assert _settings().cron_secret == ""


class TestEngineForItsEnvironment:
    """Poolingul se alege dupa cine il face — greseala se vede abia sub trafic."""

    def test_a_long_lived_process_keeps_its_own_pool(self) -> None:
        from app.core.db import build_engine

        engine = build_engine(_settings(db_pool_size=7, db_max_overflow=3))
        assert engine.pool.size() == 7
        engine.dispose()

    def test_behind_an_external_pooler_we_keep_none(self) -> None:
        """Un pool peste alt pool tine conexiuni degeaba si epuizeaza baza."""
        from sqlalchemy.pool import NullPool

        from app.core.db import build_engine

        engine = build_engine(_settings(db_external_pooler=True))
        assert isinstance(engine.pool, NullPool)
        engine.dispose()

    def test_behind_an_external_pooler_prepared_statements_are_off(self) -> None:
        """Poolerul da alta sesiune la fiecare tranzactie: o instructiune pregatita
        intr-una nu exista in urmatoarea."""
        from app.core.db import connect_arguments

        assert connect_arguments(_settings(db_external_pooler=True))["prepare_threshold"] is None

    def test_a_direct_connection_keeps_prepared_statements(self) -> None:
        from app.core.db import connect_arguments

        assert "prepare_threshold" not in connect_arguments(_settings())
