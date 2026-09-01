"""Configurarea aplicației.

Toate valorile vin din mediu (`.env` la rădăcina repo-ului) — niciun secret în cod.
Câmpurile de aici oglindesc `.env.example`; ce nu are o valoare implicită sigură nu
primește una, ca aplicația să refuze pornirea în loc să meargă greșit configurată.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Aplicație ────────────────────────────────────────────────────────────
    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "ContaCRM"
    api_v1_prefix: str = "/api/v1"
    default_locale: str = "ro"
    # Fusul orar este configurabil, nu presupus în logică (§71).
    default_timezone: str = "Europe/Bucharest"
    log_level: str = "INFO"

    # ── Securitate ───────────────────────────────────────────────────────────
    secret_key: str = "dev-only-secret-schimba-inainte-de-orice-deploy"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    cors_allowed_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 120

    # ── Bază de date ─────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg://contacrm:contacrm_dev_password@localhost:5432/contacrm"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # ── Storage (ADR-004) ────────────────────────────────────────────────────
    storage_provider: str = "local"
    storage_path: str = "./storage"
    archive_root: str = "./storage/ARHIVA"
    max_upload_size_mb: int = 25
    allowed_mime_types: str = "application/pdf,image/jpeg,image/png,image/webp"

    # ── OCR / AI (ADR-005) ───────────────────────────────────────────────────
    # `mock` este implicit: în development niciun document nu părăsește mașina (R2).
    ocr_provider: str = "mock"
    ai_provider: str = "mock"
    prompt_version: str = "v1"
    confidence_auto_threshold: float = 0.90
    confidence_review_threshold: float = 0.70
    # Implicit oprita. Aprobarea unei probe contabile fara ca un om sa se uite este
    # o decizie de business, nu un implicit tehnic — chiar si peste pragul automat.
    auto_approve_enabled: bool = False
    # Cate reprocesari automate incearca workerul inainte sa lase documentul in ERROR.
    max_processing_attempts: int = 3
    # Dupa cat timp un job ramas `RUNNING` se considera abandonat de un proces mort.
    # Peste acest prag, o cerere noua de reprocesare — sau `app.cli recover-processing` —
    # il readuce in coada. Sub el, presupunem ca cineva chiar lucreaza la el.
    processing_stale_after_minutes: int = 15
    # Din ce se derivă luna contabilă a unui document (ADR-008): `document_date`
    # (implicit, si cazul coplesitor) sau `received_at`. Fara data, nu se derivă
    # nimic — o luna gresita este mai rea decat una absenta.
    reference_period_strategy: str = "document_date"

    # ── Notificări ───────────────────────────────────────────────────────────
    notifications_enabled: bool = False

    # ── Retenție (§64) ───────────────────────────────────────────────────────
    # Nicio ștergere automată nu rulează fără o regulă explicit activată (R8).
    retention_enabled: bool = False

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_cors(cls, value: str) -> str:
        if "*" in value:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS nu poate conține caracterul universal: "
                "originile trebuie enumerate explicit."
            )
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_mime_type_set(self) -> frozenset[str]:
        return frozenset(m.strip() for m in self.allowed_mime_types.split(",") if m.strip())

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Schema API nu se publică în producție."""
        return not self.is_production

    def assert_production_ready(self) -> None:
        """Verificări care trebuie să oprească pornirea, nu să producă un avertisment."""
        problems: list[str] = []
        if self.secret_key.startswith(("dev-only", "schimba")):
            problems.append("SECRET_KEY are încă valoarea implicită.")
        if self.ocr_provider != "mock" and self.ai_provider == "mock":
            problems.append("OCR_PROVIDER real cu AI_PROVIDER=mock — configurare inconsistentă.")
        if problems:
            raise RuntimeError("Configurare invalidă pentru producție: " + " ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        settings.assert_production_ready()
    return settings


settings = get_settings()
