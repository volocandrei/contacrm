"""Cheile de stocare (§8, §74).

O cheie de stocare este un identificator abstract, **nu** o cale de filesystem.
`StorageProvider` decide unde ajunge fizic; baza de date nu știe și nu trebuie să
știe asta.

Cheile se **generează**, nu se compun din date venite de la utilizator. Numele
fișierului trimis de expeditor nu participă niciodată la construirea unei chei —
singura lui urmă este extensia, și doar după ce a fost verificată față de o listă
albă. Așa nu există niciun drum prin care `../../etc/passwd` sau `C:\\Windows\\…`
să ajungă într-o cale.

`validate_key` există ca a doua barieră: chiar dacă cineva ar construi o cheie
altfel decât prin funcțiile de aici, providerul o respinge înainte de a atinge
discul.
"""

from __future__ import annotations

import re
import uuid
from typing import Final

# Segmentele permise: litere mici, cifre, cratimă, underscore, punct. Fără spații,
# fără separatori de cale, fără nimic ce ar putea fi interpretat de un filesystem.
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

MAX_KEY_LENGTH: Final = 1024
MAX_SEGMENTS: Final = 12

# Extensiile pe care le poate purta o cheie. Extensia nu se ia din numele trimis de
# client, ci se derivă din tipul de conținut verificat.
EXTENSION_BY_MIME: Final[dict[str, str]] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

ORIGINAL = "original"
ARCHIVE = "archive"


class InvalidStorageKeyError(ValueError):
    """Cheie care nu poate fi acceptată de niciun provider."""


def extension_for(mime_type: str) -> str:
    """Extensia care corespunde unui tip de conținut deja validat."""
    try:
        return EXTENSION_BY_MIME[mime_type]
    except KeyError as exc:
        raise InvalidStorageKeyError(
            f"Tip de conținut fără extensie cunoscută: {mime_type}"
        ) from exc


def validate_key(key: str) -> str:
    """Acceptă o cheie doar dacă nu poate ieși din spațiul providerului.

    Refuză explicit: cale absolută, `..`, backslash, byte-uri de control, segment gol
    (deci și `//`), segmente care încep cu punct.
    """
    if not key or len(key) > MAX_KEY_LENGTH:
        raise InvalidStorageKeyError("Cheie goală sau prea lungă.")
    if key.startswith("/") or key.startswith("\\"):
        raise InvalidStorageKeyError("Cheia nu poate fi o cale absolută.")
    if "\\" in key:
        raise InvalidStorageKeyError("Backslash-ul este separator de cale pe Windows.")
    if any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise InvalidStorageKeyError("Cheia conține caractere de control.")

    segments = key.split("/")
    if len(segments) > MAX_SEGMENTS:
        raise InvalidStorageKeyError("Prea multe segmente.")
    for segment in segments:
        if not segment:
            raise InvalidStorageKeyError("Segment gol în cheie.")
        if segment in {".", ".."}:
            raise InvalidStorageKeyError("Cheia nu poate conține `.` sau `..`.")
        if not _SEGMENT.match(segment):
            raise InvalidStorageKeyError(f"Segment invalid: {segment!r}")
    return key


def _prefix(organization_id: uuid.UUID, document_id: uuid.UUID) -> str:
    # UUID-urile sunt deja sigure: hex plus cratime, litere mici.
    return f"organizations/{organization_id}/documents/{document_id}"


def original_key(organization_id: uuid.UUID, document_id: uuid.UUID, *, mime_type: str) -> str:
    """Cheia fișierului primit, exact așa cum a venit.

    Numele este fix (`source.<ext>`): nu depinde de ce a trimis expeditorul, deci nu
    poate fi manipulat. Originalul stă separat de arhivă și nu se suprascrie (§16).
    """
    return validate_key(
        f"{_prefix(organization_id, document_id)}/{ORIGINAL}/source.{extension_for(mime_type)}"
    )


def archive_key(
    organization_id: uuid.UUID, document_id: uuid.UUID, *, mime_type: str, version: int = 1
) -> str:
    """Cheia copiei standardizate, creată la arhivare.

    Numele standardizat, lizibil pentru om, trăiește în `documents.stored_filename`
    și se folosește la descărcare; cheia rămâne una generată, ca originalul.
    """
    if version < 1:
        raise InvalidStorageKeyError("Versiunea începe de la 1.")
    suffix = "" if version == 1 else f"-{version}"
    return validate_key(
        f"{_prefix(organization_id, document_id)}/{ARCHIVE}/"
        f"document{suffix}.{extension_for(mime_type)}"
    )


def is_within(key: str, organization_id: uuid.UUID) -> bool:
    """Verifică apartenența unei chei la o organizație.

    Folosit ca verificare suplimentară înainte de a servi un fișier: chiar dacă o
    scăpare de autorizare ar lăsa o cerere să treacă, cheia tot nu s-ar potrivi.
    """
    return key.startswith(f"organizations/{organization_id}/")
