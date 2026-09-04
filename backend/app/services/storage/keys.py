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

from app.domain.filenames import extension_by_mime

# Segmentele permise: litere mici, cifre, cratimă, underscore, punct. Fără spații,
# fără separatori de cale, fără nimic ce ar putea fi interpretat de un filesystem.
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

MAX_KEY_LENGTH: Final = 1024
MAX_SEGMENTS: Final = 12

ORIGINAL = "original"
ARCHIVE = "archive"
EFACTURA = "efactura"

#: Fișierele care însoțesc o factură electronică descărcată din SPV, cu extensia
#: lor fixă. Sunt **generate**, nu compuse: numele nu vine niciodată din arhiva
#: primită, deci nu poate participa la construirea unei căi.
#:
#: `seal` este arhiva ZIP întreagă, cu sigiliul ANAF — dovada acceptării.
#: `render` este PDF-ul oficial, refăcut oricând din XML.
EFACTURA_FILES: Final = {"seal": "zip", "render": "pdf"}


class InvalidStorageKeyError(ValueError):
    """Cheie care nu poate fi acceptată de niciun provider."""


def extension_for(mime_type: str) -> str:
    """Extensia care corespunde unui tip de conținut deja validat.

    Harta este cea din `app.domain.filenames`, nu una proprie. Aici a existat o a
    treia copie a acelorași perechi, iar când s-a adăugat factura electronică
    două dintre ele au fost aduse la zi și a treia nu: încărcarea unui XML cădea
    cu 500 la scrierea cheii de stocare, după ce fișierul trecuse validarea.
    Defectul s-a văzut abia în suita end-to-end.
    """
    extension = extension_by_mime(mime_type)
    if extension is None:
        raise InvalidStorageKeyError(f"Tip de conținut fără extensie cunoscută: {mime_type}")
    return extension


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


def efactura_key(organization_id: uuid.UUID, document_id: uuid.UUID, *, name: str) -> str:
    """Cheia unui fișier care însoțește factura electronică (§8, §74).

    `name` se alege dintr-o listă închisă, nu se primește liber: extensia și
    numele sunt amândouă ale noastre, deci nimic din ce vine de la ANAF nu ajunge
    într-o cale. Originalul rămâne unde este — XML-ul, sub `original/` — iar
    fișierele astea stau lângă el, nu în locul lui (§16).
    """
    extension = EFACTURA_FILES.get(name)
    if extension is None:
        raise InvalidStorageKeyError(
            f"Fișier e-Factura necunoscut: {name!r}. Valori acceptate: "
            + ", ".join(sorted(EFACTURA_FILES))
        )
    return validate_key(f"{_prefix(organization_id, document_id)}/{EFACTURA}/{name}.{extension}")


def is_within(key: str, organization_id: uuid.UUID) -> bool:
    """Verifică apartenența unei chei la o organizație.

    Folosit ca verificare suplimentară înainte de a servi un fișier: chiar dacă o
    scăpare de autorizare ar lăsa o cerere să treacă, cheia tot nu s-ar potrivi.
    """
    return key.startswith(f"organizations/{organization_id}/")
