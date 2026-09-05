"""Configurarea care rulează chiar acum (§16, §73).

**De ce există.** Ecranul de setări afișa valori scrise de mână în TSX —
`"local"`, `"0,90"`, `"mock"` — sub un banner care declara că vin din variabile de
mediu și din tabelul `system_settings`. Nu veneau. Dacă cineva punea
`STORAGE_PROVIDER=s3` în producție, pagina continua să spună `local`, cu
convingere. Un ecran de administrare care minte despre configurare este mai rău
decât unul care lipsește: cineva ia decizii pe el.

**Lista este o listă albă, nu un filtru.** Se expune exact ce este enumerat mai
jos. Un câmp nou în `Settings` **nu** apare aici de la sine — asta este intenția:
altfel prima cheie de API adăugată în configurare ar fi ajuns pe un ecran, iar
nimeni nu ar fi observat. `SECRET_KEY`, `DATABASE_URL`, credențialele S3 și
căile de pe disc nu au ce căuta într-un răspuns HTTP (§73), iar
`test_settings_api.py` verifică asta pe fiecare câmp existent, nu doar pe cele
la care ne-am gândit.

**Doar citire.** Nu există `system_settings` încă; totul vine din mediu, deci se
schimbă modificând deployment-ul. Ecranul spune asta, în loc să promită o editare
care nu există.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Final

from fastapi import APIRouter

from app.api.deps import require_permission
from app.api.route import CommittingRoute
from app.core.config import Settings, settings
from app.domain.filenames import ARCHIVE_ROOT
from app.domain.permissions import Permission
from app.models.user import User
from app.schemas.common import ApiModel

router = APIRouter(route_class=CommittingRoute, prefix="/settings", tags=["admin"])

SettingsReader = Annotated[User, require_permission(Permission.ADMIN_SETTINGS)]

# Structura de arhivare (§11) — un tipar, nu o cale reală de pe disc.
ARCHIVE_PATTERN: Final = f"{ARCHIVE_ROOT}/{{an}}/{{luna}}/{{client}}/"


class SettingGroup(StrEnum):
    """Gruparea de pe ecran. Cum se numesc grupurile în română decide interfața."""

    PROCESSING = "PROCESSING"
    STORAGE = "STORAGE"
    EXTRACTION = "EXTRACTION"
    PERIODS = "PERIODS"
    NOTIFICATIONS = "NOTIFICATIONS"
    RETENTION = "RETENTION"
    SECURITY = "SECURITY"


class SettingOut(ApiModel):
    """O valoare de configurare, cu numele sub care se dă în mediu.

    `key` este chiar numele variabilei de mediu, nu o etichetă: cine se uită la
    ecran trebuie să știe ce anume să schimbe, nu doar ce este acum.
    """

    key: str
    group: SettingGroup
    value: str


def _yes_no(value: bool) -> str:
    # Textul de pe ecran nu se decide aici, dar valoarea trebuie să fie un șir
    # stabil, nu „True"/„False" cu majusculă de Python.
    return "true" if value else "false"


# Lista albă. Perechea (cheie, grup, cum se citește) — nimic implicit.
EXPOSED: Final[tuple[tuple[str, SettingGroup, Callable[[Settings], str]], ...]] = (
    (
        "CONFIDENCE_AUTO_THRESHOLD",
        SettingGroup.PROCESSING,
        lambda s: f"{s.confidence_auto_threshold:.2f}",
    ),
    (
        "CONFIDENCE_REVIEW_THRESHOLD",
        SettingGroup.PROCESSING,
        lambda s: f"{s.confidence_review_threshold:.2f}",
    ),
    ("AUTO_APPROVE_ENABLED", SettingGroup.PROCESSING, lambda s: _yes_no(s.auto_approve_enabled)),
    ("MAX_PROCESSING_ATTEMPTS", SettingGroup.PROCESSING, lambda s: str(s.max_processing_attempts)),
    (
        "PROCESSING_STALE_AFTER_MINUTES",
        SettingGroup.PROCESSING,
        lambda s: str(s.processing_stale_after_minutes),
    ),
    # Numele providerului, nu unde scrie. Bucket-ul, endpointul și cheile rămân
    # unde le e locul: în mediu (§73).
    ("STORAGE_PROVIDER", SettingGroup.STORAGE, lambda s: s.storage_provider),
    ("MAX_UPLOAD_SIZE_MB", SettingGroup.STORAGE, lambda s: str(s.max_upload_size_mb)),
    ("ALLOWED_MIME_TYPES", SettingGroup.STORAGE, lambda s: s.allowed_mime_types),
    # Tiparul de arhivare, nu rădăcina configurată: structura este utilă
    # administratorului, calea de pe disc nu este treaba niciunui browser.
    ("ARCHIVE_PATTERN", SettingGroup.STORAGE, lambda _: ARCHIVE_PATTERN),
    ("OCR_PROVIDER", SettingGroup.EXTRACTION, lambda s: s.ocr_provider),
    ("AI_PROVIDER", SettingGroup.EXTRACTION, lambda s: s.ai_provider),
    # Modelul care citește pozele — util administratorului când compară costuri
    # sau explică de ce un document a fost citit altfel decât altul.
    ("AI_MODEL", SettingGroup.EXTRACTION, lambda s: s.ai_model),
    # `AI_API_KEY` nu apare aici și nici nu va apărea, nici măcar ca
    # „configurată/lipsește": lista nu poartă nume de secrete (§73), iar
    # regula nu depinde de ce valoare pune azi cineva acolo. Că există o
    # cheie se vede din faptul că aplicația a pornit: fără ea, verificarea
    # de producție oprește pornirea.
    ("PROMPT_VERSION", SettingGroup.EXTRACTION, lambda s: s.prompt_version),
    (
        "REFERENCE_PERIOD_STRATEGY",
        SettingGroup.PERIODS,
        lambda s: s.reference_period_strategy,
    ),
    ("DEFAULT_TIMEZONE", SettingGroup.PERIODS, lambda s: s.default_timezone),
    (
        "NOTIFICATIONS_ENABLED",
        SettingGroup.NOTIFICATIONS,
        lambda s: _yes_no(s.notifications_enabled),
    ),
    ("RETENTION_ENABLED", SettingGroup.RETENTION, lambda s: _yes_no(s.retention_enabled)),
    # Numărul de proxy-uri, nu adresele lor. Are ce căuta pe ecran pentru că de
    # el depinde dacă IP-ul din jurnalul de audit înseamnă ceva: pus pe 0 în
    # spatele unui proxy, toate intrările notează adresa platformei; pus prea
    # mare, notează o adresă pe care clientul și-o poate alege singur. Un audit
    # despre care nu se știe în ce caz se află nu se poate folosi într-o dispută.
    ("TRUSTED_PROXY_COUNT", SettingGroup.SECURITY, lambda s: str(s.trusted_proxy_count)),
    # Doar dacă integrarea este configurată, nu și cu ce. Client id-ul nu este un
    # secret, dar nu are ce căuta pe un ecran: nu spune nimic util și adaugă o
    # valoare în plus de scăpat.
    (
        "ONEDRIVE",
        SettingGroup.SECURITY,
        lambda s: _yes_no(bool(s.ms_client_id and s.ms_client_secret)),
    ),
)


@router.get("", response_model=list[SettingOut])
def list_settings(_: SettingsReader) -> list[SettingOut]:
    """Ce este configurat acum, în procesul care răspunde la această cerere."""
    return [SettingOut(key=key, group=group, value=read(settings)) for key, group, read in EXPOSED]
