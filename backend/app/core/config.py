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

#: Motoarele de răspuns ale asistentului. `rules` merge fără credențiale;
#: `anthropic` cere o cheie și scoate întrebările din tiparul fix.
ASSISTANT_PROVIDERS = frozenset({"rules", "anthropic"})

# Providerii de extracție care există, toți locali:
#   `mock`      — date sintetice, pentru demonstrație
#   `pdf_text`  — stratul de text al PDF-ului
#   `efactura`  — facturi electronice UBL 2.1 (e-Factura ANAF)
#   `local`     — alege între cele două de mai sus după conținutul fișierului
# `local` este valoarea potrivită pentru un cabinet real: primește în aceeași zi
# XML-uri și PDF-uri, iar `OCR_PROVIDER` este o singură valoare pentru tot procesul.
# Un nume neimplementat trebuie să oprească pornirea, nu să eșueze abia în worker,
# la primul document — adică după ce cineva a crezut că sistemul funcționează.
EXTRACTION_PROVIDERS = frozenset({"mock", "pdf_text", "efactura", "local", "vision", "hybrid"})

# Dintre ei, cei care nu trimit nimic nicăieri și nu au un model în spate. Astăzi
# sunt toți — distincția există pentru verificarea de producție, care trebuie să
# prindă momentul în care apare primul provider extern (Faza 2) fără să dea alarme
# false pentru unul local. `pdf_text` citește text; nu ghicește și nu întreabă pe
# nimeni, deci nu are ce să fie „inconsistent" cu `AI_PROVIDER=mock`.
LOCAL_EXTRACTION_PROVIDERS = frozenset({"mock", "pdf_text", "efactura", "local"})

#: Cei care trimit documentul în afara cabinetului, la un model.
#:
#: `vision` trimite tot ce primește; `hybrid` doar ce nu s-a putut citi local —
#: adică pozele și scanurile. Amândoi cer o cheie, și amândoi sunt o decizie pe
#: care un cabinet o ia explicit: implicit rămâne `mock`, iar recomandarea pentru
#: producție rămâne `local`, care nu trimite nimic nicăieri (R2).
MODEL_EXTRACTION_PROVIDERS = frozenset({"vision", "hybrid"})

#: Mediile ANAF. `test` și `prod` sunt baze separate la ANAF, nu niveluri de log:
#: o factură din mediul de test nu există în producție și invers.
ANAF_ENVIRONMENTS = frozenset({"prod", "test"})

#: Lungimea minimă a cheii care semnează tokenurile. HS256 folosește SHA-256, iar
#: sub 32 de octeți cheia este mai scurtă decât rezultatul funcției — PyJWT însuși
#: avertizează. Nu este o preferință de stil: sub prag, semnătura devine ghicibilă.
MIN_SECRET_KEY_LENGTH = 32

#: Ziua maximă acceptată ca termen. Peste 28, ziua nu există în februarie.
MAX_DEADLINE_DAY = 28


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
    #: Adresa la care ajunge un om din afară — clientul care primește un link de
    #: trimitere. Nu se poate deduce din cererea curentă: linkul se compune pe
    #: server, ajunge într-un email, și trebuie să funcționeze de oriunde.
    #: Implicit adresa de development, ca linkul să meargă și fără configurare.
    public_base_url: str = "http://localhost:5173"
    # Câte încercări de autentificare acceptă o adresă IP într-un minut.
    #
    # Se numea `rate_limit_per_minute` și nu o citea niciun modul: o promisiune
    # de protecție care nu exista. Numele spune acum exact ce limitează, iar
    # `app/core/rate_limit.py` scrie ce acoperă și ce nu.
    #
    # Zece pe minut este generos pentru un om care își greșește parola și
    # strâmt pentru cineva care încearcă o listă. Zero oprește limitarea.
    login_attempts_per_minute: int = 10
    # Și câte acceptă adresa aceea în total, peste toate conturile.
    #
    # Există separat pentru că cele două atacuri sunt diferite: unul încearcă
    # multe parole pe un cont, celălalt o parolă pe multe conturi. Un prag
    # singur ar trebui ori atât de mic încât să blocheze un birou întreg din
    # spatele unei singure adrese publice, ori atât de mare încât să nu apere
    # niciun cont.
    login_attempts_per_address_per_minute: int = 60
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

    # ── ANAF SPV / e-Factura (M11) ───────────────────────────────────────────
    # Aplicația înregistrată în portalul OAuth al ANAF. Fără `anaf_client_id`,
    # ecranul spune că integrarea nu este configurată — nu oferă un buton care
    # eșuează.
    #
    # Autorizarea inițială **nu se poate automatiza**: pasul `authorize` cere
    # certificatul digital calificat prezentat de browser, la propriu. După el,
    # refresh tokenul ține un an. O intervenție umană pe an, nu una pe zi.
    anaf_client_id: str = ""
    anaf_client_secret: str = ""
    anaf_redirect_uri: str = "http://localhost:5173/administrare/anaf"
    # `prod` lucrează pe facturile reale, `test` pe mediul de test al ANAF. Cele
    # două au baze complet separate: un token de test nu vede nimic în producție.
    anaf_environment: str = "prod"
    # Câte facturi ia un tur, per client. ANAF limitează cererile pe zi, iar o
    # împuternicire nouă poate avea un an de facturi în urmă: se iau pe bucăți,
    # iar turul următor continuă de unde a rămas.
    anaf_sync_batch: int = 25
    # Cât în urmă se uită prima sincronizare a unui client. ANAF nu acceptă
    # ferestre mai lungi de 60 de zile într-o singură cerere.
    anaf_lookback_days: int = 30

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
    #: Cheia modelului care **vede** documentele (`vision`, `hybrid`).
    #:
    #: Separată de `ASSISTANT_API_KEY` fiindcă sunt două decizii diferite: un
    #: cabinet poate vrea un asistent care răspunde la întrebări fără să trimită
    #: nicăieri documentele clienților. Aceeași cheie se poate pune în amândouă,
    #: dar alegerea rămâne a lui.
    ai_api_key: str = ""
    #: Modelul care citește pozele. Trebuie să vadă imagini și PDF-uri.
    ai_model: str = "claude-sonnet-5"
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

    # ── Termenul lunii ───────────────────────────────────────────────────────
    # Ziua din luna **următoare** până la care trebuie depuse declarațiile pentru
    # luna încheiată. 25 este termenul obișnuit în România (D300, D394), dar
    # rămâne configurabil: un cabinet care își impune un termen intern mai
    # devreme trebuie să-l poată pune, iar legea se poate schimba fără noi.
    #
    # Nu se acceptă peste 28: ziua trebuie să existe în orice lună, inclusiv
    # februarie, altfel panoul ar rămâne fără termen exact în luna în care
    # contează.
    filing_deadline_day: int = 25

    # ── Asistentul din aplicație (M13) ───────────────────────────────────────
    # `rules` răspunde din unelte deterministe, fără nicio credențială și fără
    # să trimită nimic în afara rețelei cabinetului. Un motor de limbaj se
    # adaugă prin același seam, cu aceleași unelte și aceleași permisiuni.
    assistant_provider: str = "rules"
    assistant_api_key: str = ""
    #: Modelul implicit. Sonnet este raportul potrivit între cost și calitate
    #: pentru un asistent care cheamă unelte peste seturi mici de date.
    assistant_model: str = "claude-sonnet-5"
    #: Câte runde de unelte poate cere modelul înainte să răspundă. Trei
    #: acoperă „găsește clientul, apoi vezi ce-i lipsește"; peste atât, un
    #: dialog care nu se termină costă bani fără să dea un răspuns.
    assistant_max_tool_rounds: int = 3

    # ── Notificări ───────────────────────────────────────────────────────────
    notifications_enabled: bool = False

    # ── Retenție (§64) ───────────────────────────────────────────────────────
    # Nicio ștergere automată nu rulează fără o regulă explicit activată (R8).
    retention_enabled: bool = False

    @field_validator("assistant_provider")
    @classmethod
    def _known_assistant_provider(cls, value: str) -> str:
        if value not in ASSISTANT_PROVIDERS:
            raise ValueError(
                f"ASSISTANT_PROVIDER necunoscut: {value!r}. Valori acceptate: "
                + ", ".join(sorted(ASSISTANT_PROVIDERS))
            )
        return value

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

    @field_validator("filing_deadline_day")
    @classmethod
    def _valid_deadline_day(cls, value: int) -> int:
        if not 1 <= value <= MAX_DEADLINE_DAY:
            raise ValueError(
                f"FILING_DEADLINE_DAY trebuie să fie între 1 și {MAX_DEADLINE_DAY}: "
                "ziua trebuie să existe în orice lună, inclusiv februarie."
            )
        return value

    @field_validator("anaf_environment")
    @classmethod
    def _known_anaf_environment(cls, value: str) -> str:
        if value not in ANAF_ENVIRONMENTS:
            raise ValueError(
                f"ANAF_ENVIRONMENT necunoscut: {value!r}. Valori acceptate: "
                + ", ".join(sorted(ANAF_ENVIRONMENTS))
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
        elif len(self.secret_key.strip()) < MIN_SECRET_KEY_LENGTH:
            # Verificarea de mai sus se uita **doar** la valoarea implicită, deci
            # un `SECRET_KEY=` gol o trecea: șirul gol nu începe cu „dev-only".
            # Iar cheia asta semnează tokenurile de acces — cu una goală, oricine
            # își semnează singur unul valabil. Cazul nu este teoretic: pe multe
            # platforme o variabilă nedefinită ajunge la proces ca șir gol.
            problems.append(
                f"SECRET_KEY are sub {MIN_SECRET_KEY_LENGTH} de caractere. "
                'Generează una cu: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
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
        if self.ocr_provider in MODEL_EXTRACTION_PROVIDERS and not self.ai_api_key.strip():
            # Fără cheie, fiecare poză ar marca documentul `OCR_FAILED`. Se vede,
            # dar abia după ce se strâng o sută de documente eșuate; oprirea la
            # pornire este singurul moment în care cineva chiar citește mesajul.
            problems.append(
                f"OCR_PROVIDER={self.ocr_provider} fără AI_API_KEY: "
                "citirea documentelor fotografiate ar eșua la fiecare document."
            )
        if self.public_base_url.startswith("http://localhost"):
            # Un link de trimitere compus cu `localhost` ajunge la client și nu
            # duce nicăieri. Se descoperă abia când cineva îl deschide — adică
            # exact la clientul pe care voiai să-l ajuți.
            problems.append(
                "PUBLIC_BASE_URL a rămas pe localhost: "
                "linkurile trimise clienților nu ar funcționa."
            )
        if self.storage_provider == "s3" and not self.s3_bucket:
            problems.append("STORAGE_PROVIDER=s3 fără S3_BUCKET.")
        if self.assistant_provider == "anthropic" and not self.assistant_api_key.strip():
            # Fără cheie, fiecare întrebare ar cădea în motorul cu reguli, iar
            # cabinetul ar crede că modelul răspunde. Oprirea la pornire este
            # singurul moment în care cineva chiar citește mesajul.
            problems.append("ASSISTANT_PROVIDER=anthropic fără ASSISTANT_API_KEY.")
        if problems:
            raise RuntimeError("Configurare invalidă pentru producție: " + " ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        settings.assert_production_ready()
    return settings


settings = get_settings()
