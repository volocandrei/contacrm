"""Numele de fișier și căile de arhivă (§10, §11, R7).

**Acesta este un port identic al lui `frontend/src/lib/filename.ts`.** Regula
trăiește conceptual într-un singur loc, chiar dacă este scrisă în două limbaje;
`frontend/src/lib/filename.test.ts` este specificația executabilă, iar
`tests/test_filenames.py` rulează aceleași cazuri — inclusiv unele citite direct
din fișierul TypeScript, ca cele două să nu se poată despărți în tăcere.

Regula de bază: numele venit de la utilizator sau de la expeditor nu ajunge
**niciodată** nemodificat într-o cale. Tot ce iese de aici este compus din segmente
sanitizate.

De reținut: ce se întoarce de aici este un nume **lizibil pentru om** — cel pe care
îl vede contabilul și cel din `Content-Disposition`. Cheia de stocare rămâne una
generată (`app/services/storage/keys.py`) și nu se atinge de textul ăsta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# Caractere interzise în nume de fișier pe Windows/POSIX, separatorii de cale și
# caracterele de control. Cratima și underscore rămân permise — apar în serii reale.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Nume rezervate pe Windows — un fișier numit „CON.pdf" nu poate fi creat.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)

MAX_SEGMENT_LENGTH = 60
MAX_FILENAME_LENGTH = 180

_ALLOWED_EXTENSIONS = frozenset({"pdf", "xml", "jpg", "jpeg", "png", "webp", "tif", "tiff"})
DEFAULT_EXTENSION = "pdf"

_EXTENSION_BY_MIME = {
    "application/pdf": "pdf",
    # Factura electronică rămâne XML în arhivă: este documentul original, iar §16
    # spune că originalul nu se transformă.
    "application/xml": "xml",
    "text/xml": "xml",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/tiff": "tif",
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^(0[1-9]|1[0-2])$")

ARCHIVE_ROOT = "/ARHIVA"
NO_PERIOD = "fara-perioada"
NO_DATE = "fara-data"
NO_CLIENT = "ClientNeidentificat"
DEFAULT_TYPE_LABEL = "Document"


def sanitize_segment(value: str, max_length: int = MAX_SEGMENT_LENGTH) -> str:
    """Transformă un text arbitrar într-un segment sigur de nume de fișier.

    Fără diacritice, fără caractere ilegale, fără separatori de cale, lungime
    limitată. Nu întoarce niciodată șirul gol: un segment gol ar face numele final
    ambiguu, iar în cale ar produce `//`.
    """
    # Descompunerea separă litera de semnul diacritic; semnele combinate se elimină.
    decomposed = unicodedata.normalize("NFD", value)
    without_diacritics = "".join(c for c in decomposed if not unicodedata.combining(c))

    # ș/ț cu virgulă sau sedilă și ligaturi care nu se descompun peste tot.
    # Ca în TypeScript, înlocuirea este insensibilă la registru și dă litera mică.
    without_diacritics = re.sub(r"[șş]", "s", without_diacritics, flags=re.IGNORECASE)
    without_diacritics = re.sub(r"[țţ]", "t", without_diacritics, flags=re.IGNORECASE)
    without_diacritics = without_diacritics.replace("ß", "ss")

    cleaned = _ILLEGAL_CHARS.sub("", without_diacritics)
    # Punctele repetate ar permite „..", deci și traversare de cale.
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    # Windows nu acceptă nume care se termină cu punct sau spațiu.
    cleaned = re.sub(r"^[.\s]+|[.\s]+$", "", cleaned)

    truncated = cleaned[:max_length]

    if truncated == "" or truncated.lower() in _RESERVED_NAMES:
        return f"_{truncated}"
    return truncated


def extension_by_mime(mime_type: str) -> str | None:
    """Extensia unui tip de conținut deja verificat, sau `None` dacă nu îl știm.

    Sursa unică a perechilor. Stocarea o folosește ca să compună cheia, numele de
    arhivă ca să compună fișierul — și trebuie să fie aceeași: o a doua copie a
    listei s-a despărțit tăcut de prima când a apărut factura electronică.
    """
    return _EXTENSION_BY_MIME.get(mime_type)


def normalize_extension(filename: str, mime_type: str | None = None) -> str:
    """Extensia se ia din lista permisă, nu din ce a trimis expeditorul.

    Tipul de conținut are prioritate: el a fost verificat pe octeți, pe când
    extensia este doar o afirmație a clientului.
    """
    if mime_type and mime_type in _EXTENSION_BY_MIME:
        return _EXTENSION_BY_MIME[mime_type]

    candidate = ""
    if "." in filename:
        candidate = re.sub(r"[^a-z0-9]", "", filename.rsplit(".", 1)[-1].lower())
    return candidate if candidate in _ALLOWED_EXTENSIONS else DEFAULT_EXTENSION


@dataclass(frozen=True, slots=True)
class FilenameInput:
    """Datele din care se compune numele. Oglinda lui `FilenameInput` din TypeScript."""

    # Numele original — folosit **doar** pentru a deduce extensia.
    original_filename: str
    document_date: date | str | None = None
    document_type_label: str | None = None
    client_name: str | None = None
    series: str | None = None
    document_number: str | None = None
    mime_type: str | None = None
    # Sufix anti-coliziune, adăugat de apelant când numele există deja.
    collision_suffix: int | None = None


def build_document_filename(data: FilenameInput) -> str:
    """Convenția (§10): `YYYY-MM-DD_[TipDocument]_[NumeClient]_[SerieNumar].ext`.

    Când documentul nu are serie și număr, ultimul segment lipsește pur și simplu —
    nu se inventează un substitut.
    """
    iso_date = _iso_date(data.document_date)
    segments = [
        iso_date if iso_date is not None else NO_DATE,
        sanitize_segment(data.document_type_label or DEFAULT_TYPE_LABEL),
        sanitize_segment(data.client_name or NO_CLIENT),
    ]

    serial_source = (data.series or "") + (data.document_number or "")
    # `sanitize_segment("")` întoarce "_", deci verificăm sursa, nu rezultatul.
    if serial_source != "":
        segments.append(sanitize_segment(serial_source, 30))

    if data.collision_suffix is not None and data.collision_suffix > 0:
        segments.append(str(data.collision_suffix))

    extension = normalize_extension(data.original_filename, data.mime_type)
    stem = "_".join(segments)[: MAX_FILENAME_LENGTH - len(extension) - 1]
    return f"{stem}.{extension}"


def build_archive_path(
    reference_month: str | None, client_name: str | None, root: str = ARCHIVE_ROOT
) -> str:
    """Structura de arhivare (§11): `/ARHIVA/{an}/{lună}/{client}/`.

    Fiecare segment este sanitizat separat, deci „../" nu poate ieși din rădăcină —
    nici prin numele clientului, nici prin perioada de referință.
    """
    parts = (reference_month or "").split("-")
    year = parts[0] if len(parts) > 0 else ""
    month = parts[1] if len(parts) > 1 else ""

    safe_year = year if _YEAR.match(year) else NO_PERIOD
    safe_month = month if _MONTH.match(month) else "00"
    safe_client = sanitize_segment(client_name or NO_CLIENT)
    return f"{root}/{safe_year}/{safe_month}/{safe_client}/"


def _iso_date(value: date | str | None) -> str | None:
    """`YYYY-MM-DD` dacă data este reală, altfel `None`.

    „2026-02-30" respectă formatul, dar nu este o zi; lipsa datei se marchează
    explicit în nume, nu se inventează.
    """
    if isinstance(value, date):
        return value.isoformat()
    if not value or not _ISO_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


__all__ = [
    "ARCHIVE_ROOT",
    "MAX_FILENAME_LENGTH",
    "MAX_SEGMENT_LENGTH",
    "FilenameInput",
    "build_archive_path",
    "build_document_filename",
    "normalize_extension",
    "sanitize_segment",
]
