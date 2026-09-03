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

# Providerii de stocare care există. Enumerarea are rost: o valoare scrisă greșit
# în mediu trebuie să oprească pornirea, nu să cadă tăcut pe implicit — adică pe
# disc local, exact acolo unde documentele s-ar pierde la prima repornire.
STORAGE_PROVIDERS = frozenset({"local", "s3"})

# Providerii de extracție care există, toți locali:
#   `mock`      — date sintetice, pentru demonstrație
#   `pdf_text`  — stratul de text al PDF-ului
#   `efactura`  — facturi electronice UBL 2.1 (e-Factura ANAF)
#   `local`     — alege între cele două de mai sus după conținutul fișierului
# `local` este valoarea potrivită pentru un cabinet real: primește în aceeași zi
# XML-uri și PDF-uri, iar `OCR_PROVIDER` este o singură valoare pentru tot procesul.
# Un nume neimplementat trebuie să oprească pornirea, nu să eșueze abia în worker,
# la primul document — adică după ce cineva a crezut că sistemul funcționează.
EXTRACTION_PROVIDERS = frozenset({"mock", "pdf_text", "efactura", "local"})

# Dintre ei, cei care nu trimit nimic nicăieri și nu au un model în spate. Astăzi
# sunt toți — distincția există pentru verificarea de producție, care trebuie să
# prindă momentul în care apare primul provider extern (Faza 2) fără să dea alarme
# false pentru unul local. `pdf_text` citește text; nu ghicește și nu întreabă pe
# nimeni, deci nu are ce să fie „inconsistent" cu `AI_PROVIDER=mock`.
LOCAL_EXTRACTION_PROVIDERS = frozenset({"mock", "pdf_text", "efactura", "local"})


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
    # Secretul cu care un planificator extern (cron) are voie să ceară un tur de
    # coadă. Gol înseamnă **oprit**: ruta refuză orice, inclusiv o cerere corectă.
    # Un endpoint care execută muncă nu are voie să fie public nici măcar o clipă.
    cron_secret: str = ""
    # Câte proxy-uri de încredere stau **obligatoriu** în fața aplicației: 0 când
    # este expusă direct, 1 în spatele Vercel sau al unui singur reverse proxy.
    # Sub acest număr, `X-Forwarded-For` se ignoră cu totul — un antet citit fără
    # să știm cine l-a scris înseamnă că oricine își poate alege IP-ul din audit.
    trusted_proxy_count: int = 0

    # ── Microsoft OneDrive / SharePoint (M9) ─────────────────────────────────
    # Aplicația înregistrată în Entra ID prin care se citesc dosarele clienților.
    # Fără `ms_client_id`, ecranul de administrare spune că integrarea nu este
    # configurată — nu o oferă și apoi eșuează.
    ms_client_id: str = ""
    ms_client_secret: str = ""
    # `common` acceptă orice cont Microsoft (personal sau de firmă). Un cabinet cu
    # tenant propriu pune id-ul lui și restrânge accesul la propriii utilizatori.
    ms_tenant_id: str = "common"
    # Unde trimite Microsoft browserul înapoi. Trebuie să fie identic cu ce e
    # înregistrat în Entra ID, altfel consimțământul eșuează cu o eroare opacă.
    ms_redirect_uri: str = "http://localhost:5173/administrare/surse"
    # Cheia cu care se criptează refresh tokenul înainte de a atinge baza de date.
    # Separată de SECRET_KEY: aceea se rotește, iar rotirea ei nu are voie să rupă
    # tăcut legăturile cu OneDrive. Vezi `app/core/crypto.py`.
    drive_token_key: str = ""
    # Câte fișiere ia un tur de sincronizare, per dosar. Un dosar cu un an de
    # documente nu trebuie să blocheze coada la prima conectare.
    drive_sync_batch: int = 50
    # Cate mesaje ia un tur, per dosar de email. Mai mic decat la drive: fiecare
    # mesaj cu atasamente costa inca o cerere pentru metadatele lor.
    mail_sync_batch: int = 25

    # ── Bază de date ─────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg://contacrm:contacrm_dev_password@localhost:5432/contacrm"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Se pune pe `true` când `DATABASE_URL` arată către un pooler în mod tranzacție
    # (PgBouncer, Supabase pe `:6543`) — situația obișnuită când procesele apar și
    # dispar odată cu cererile. Un pooler în modul ăsta rupe două lucruri tăcut:
    # instrucțiunile pregătite, pentru că sesiunea din spate se schimbă între
    # cereri, și rostul unui pool propriu, pentru că poolerul e deja poolul.
    db_external_pooler: bool = False

    # ── Storage (ADR-004) ────────────────────────────────────────────────────
    # `local` scrie pe disc, `s3` într-un bucket compatibil S3. Restul aplicației
    # nu află niciodată care dintre ele este activ.
    storage_provider: str = "local"
    storage_path: str = "./storage"
    archive_root: str = "./storage/ARHIVA"
    max_upload_size_mb: int = 25
    # `application/xml` este factura electronică (e-Factura, UBL 2.1) — de la 1
    # iulie 2024 forma obligatorie între firme, deci partea covârșitoare a
    # facturilor unui cabinet.
    allowed_mime_types: str = "application/pdf,application/xml,image/jpeg,image/png,image/webp"

    # Folosite doar când STORAGE_PROVIDER=s3. Endpoint-ul gol înseamnă AWS; pentru
    # Supabase Storage, Cloudflare R2 sau MinIO se pune adresa lor.
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "eu-central-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Separă medii care împart un bucket. Gol în cazul obișnuit.
    s3_prefix: str = ""

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

    @field_validator("storage_provider")
    @classmethod
    def _known_storage_provider(cls, value: str) -> str:
        if value not in STORAGE_PROVIDERS:
            raise ValueError(
                f"STORAGE_PROVIDER necunoscut: {value!r}. Valori acceptate: "
                + ", ".join(sorted(STORAGE_PROVIDERS))
            )
        return value

    @field_validator("ocr_provider")
    @classmethod
    def _known_extraction_provider(cls, value: str) -> str:
        if value not in EXTRACTION_PROVIDERS:
            raise ValueError(
                f"OCR_PROVIDER necunoscut sau neimplementat: {value!r}. Valori acceptate: "
                + ", ".join(sorted(EXTRACTION_PROVIDERS))
            )
        return value

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
        if self.ocr_provider == "mock":
            # `mock` inventează furnizori, sume și date. Într-o demonstrație este
            # exact ce trebuie; într-o instalare de producție ar scrie valori
            # false în câmpuri contabile, iar ecranul de verificare le-ar arăta
            # cu proveniență și scor de încredere, adică exact ca pe niște valori
            # citite de pe document. Pentru o demonstrație există `staging`.
            problems.append(
                "OCR_PROVIDER=mock în producție: providerul inventează date contabile. "
                "Folosește pdf_text, sau ENVIRONMENT=staging pentru o demonstrație."
            )
        if self.ocr_provider not in LOCAL_EXTRACTION_PROVIDERS and self.ai_provider == "mock":
            problems.append("OCR_PROVIDER real cu AI_PROVIDER=mock — configurare inconsistentă.")
        if self.storage_provider == "s3" and not self.s3_bucket:
            problems.append("STORAGE_PROVIDER=s3 fără S3_BUCKET.")
        if problems:
            raise RuntimeError("Configurare invalidă pentru producție: " + " ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        settings.assert_production_ready()
    return settings


settings = get_settings()
