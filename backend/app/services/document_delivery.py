"""Servirea fișierelor către browser (§27-§30, §50, §51).

Conținutul ăsta este **încărcat de utilizatori** și este servit de pe originea
aplicației. De aceea răspunsurile poartă un set fix de antete:

- `Content-Type` din tipul **validat la upload**, niciodată din ce a declarat
  clientul (§50);
- `X-Content-Type-Options: nosniff` — browserul nu are voie să ghicească altceva;
- `Content-Security-Policy: default-src 'none'; sandbox` — un PDF poate conține
  JavaScript, iar afișat inline pe aceeași origine ar rula cu drepturile
  aplicației. Sandbox-ul îi taie orice acces;
- `Cache-Control: private, no-store` — documentele contabile nu au ce căuta în
  cache-uri intermediare.

Numele de fișier din `Content-Disposition` este cel standardizat sau numele
original curățat — niciodată o cale internă (§29, §73).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote

from app.models.document import Document
from app.services.storage import StorageProvider
from app.services.storage.keys import EXTENSION_BY_MIME

CHUNK_SIZE: Final = 64 * 1024

# Antetele care însoțesc orice fișier servit.
SECURITY_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    # Un PDF cu JavaScript nu trebuie să poată face nimic pe originea noastră.
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
}

# Ce rămâne dintr-un nume de fișier pus într-un antet HTTP: fără ghilimele, fără
# separatori de cale, fără caractere de control care ar putea sparge antetul.
_UNSAFE_IN_HEADER = re.compile(r'[\x00-\x1f\x7f"\\/]')


class RangeNotSatisfiableError(Exception):
    """Interval cerut în afara fișierului."""

    def __init__(self, size: int) -> None:
        super().__init__("Interval invalid.")
        self.size = size


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int  # inclusiv

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """Interpretează `Range: bytes=…`.

    Acceptă doar un singur interval — forma pe care o folosesc browserele pentru
    PDF-uri. Orice altceva este ignorat și se servește fișierul întreg, ceea ce
    rămâne un răspuns corect.
    """
    if not header or size <= 0:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if match is None:
        return None

    raw_start, raw_end = match.group(1), match.group(2)
    if not raw_start and not raw_end:
        return None

    if not raw_start:
        # `bytes=-500`: ultimii 500 de octeți.
        length = int(raw_end)
        if length <= 0:
            raise RangeNotSatisfiableError(size)
        start, end = max(0, size - length), size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
        end = min(end, size - 1)

    if start >= size or start > end:
        raise RangeNotSatisfiableError(size)
    return ByteRange(start=start, end=end)


def safe_filename(document: Document) -> str:
    """Numele sub care documentul ajunge la utilizator.

    Cel standardizat dacă documentul a fost arhivat; altfel numele original,
    curățat. Nu conține niciodată o cale.
    """
    candidate = document.stored_filename or document.original_filename
    # Numai ultimul segment: un nume primit ca `a/b/c.pdf` devine `c.pdf`.
    candidate = candidate.replace("\\", "/").split("/")[-1]
    cleaned = _UNSAFE_IN_HEADER.sub("", candidate).strip()
    if not cleaned:
        extension = EXTENSION_BY_MIME.get(document.mime_type, "bin")
        return f"document-{document.id}.{extension}"
    return cleaned[:200]


def content_disposition(document: Document, *, inline: bool) -> str:
    """Antetul de dispoziție, cu nume ASCII plus varianta UTF-8 (RFC 5987).

    Numele românești conțin diacritice, iar un antet HTTP este ASCII: fără
    `filename*`, browserul ar salva fișierul cu numele stricat.
    """
    name = safe_filename(document)
    ascii_name = name.encode("ascii", "replace").decode("ascii")
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def stream(
    storage: StorageProvider,
    document: Document,
    *,
    byte_range: ByteRange | None = None,
) -> Iterator[bytes]:
    """Conținutul documentului, în bucăți. Fișierul nu ajunge niciodată întreg în memorie."""
    key = document.archive_key or document.storage_key
    if byte_range is None:
        return storage.iter_chunks(key, CHUNK_SIZE)
    return storage.iter_range(key, byte_range.start, byte_range.end, CHUNK_SIZE)


def stored_size(storage: StorageProvider, document: Document) -> int:
    """Dimensiunea reală de pe disc, nu cea din baza de date.

    Cele două ar trebui să coincidă; dacă nu coincid, `Content-Length` trebuie să
    descrie ce se trimite efectiv, altfel conexiunea se blochează.
    """
    return storage.size(document.archive_key or document.storage_key)
