"""Validarea fișierelor primite (§9, §10, §50).

Regula de bază: **nimic din ce spune clientul despre fișier nu este de încredere.**
Nici extensia, nici antetul `Content-Type`. Tipul se determină din primii octeți ai
conținutului, iar restul verificărilor pornesc de la rezultatul acela.

Dimensiunea se verifică **în timpul citirii**, nu după: un fișier de 4 GB nu trebuie
să ajungă în memorie sau pe disc doar ca să constatăm apoi că e prea mare. Din
același motiv SHA-256 se calculează în flux, pe măsură ce datele trec (§11).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO, Final

from app.core.config import settings
from app.domain.efactura import looks_like_xml
from app.domain.enums import DocumentErrorCode

READ_CHUNK: Final = 64 * 1024

# Câți octeți sunt de ajuns ca să recunoaștem un format. WEBP are nevoie de 12.
SNIFF_BYTES: Final = 32


class FileValidationError(Exception):
    """Fișier respins. Poartă un cod structurat, nu doar un mesaj (§53)."""

    def __init__(self, code: DocumentErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class InspectedFile:
    """Ce am aflat despre fișier citindu-l, nu ce ni s-a spus despre el."""

    mime_type: str
    size: int
    sha256: str


def sniff_mime_type(head: bytes) -> str | None:
    """Tipul de conținut, dedus din semnătura fișierului.

    Doar formatele pe care le acceptăm. Orice altceva — inclusiv un executabil
    redenumit `.pdf` — întoarce None și este respins de apelant.
    """
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # RIFF....WEBP — cei patru octeți dintre marcaje sunt dimensiunea.
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    # Factura electronică. Se cere declarația explicită `<?xml`, nu orice fișier
    # care începe cu `<`: altfel un HTML ar trece drept document contabil și ar fi
    # respins abia la extracție, cu un mesaj despre altceva.
    if looks_like_xml(head):
        return "application/xml"
    return None


class ValidatingReader:
    """Flux care se validează singur în timp ce este citit.

    Antetul se inspectează la construire, deci un format nesuportat este respins
    **înainte** de a se scrie ceva pe disc. Restul — dimensiunea și hash-ul — se
    calculează pe măsură ce `StorageProvider.save` citește.

    Se dă direct lui `save`: nicăieri nu există fișierul întreg în memorie.
    """

    def __init__(
        self,
        source: BinaryIO,
        *,
        max_size: int | None = None,
        allowed_mime_types: frozenset[str] | None = None,
    ) -> None:
        self._limit = settings.max_upload_size_bytes if max_size is None else max_size
        allowed = allowed_mime_types or settings.allowed_mime_type_set

        head = source.read(SNIFF_BYTES)
        if not head:
            raise FileValidationError(DocumentErrorCode.INVALID_FILE, "Fișierul este gol.")

        mime_type = sniff_mime_type(head)
        if mime_type is None:
            raise FileValidationError(
                DocumentErrorCode.UNSUPPORTED_FORMAT,
                "Formatul fișierului nu este recunoscut. Acceptăm PDF, JPEG, PNG și WebP.",
            )
        if mime_type not in allowed:
            raise FileValidationError(
                DocumentErrorCode.UNSUPPORTED_FORMAT,
                f"Tipul {mime_type} nu este acceptat.",
            )

        self.mime_type = mime_type
        self._source = source
        self._pending = head
        self._digest = hashlib.sha256()
        self._size = 0
        self._exhausted = False

    # ── Interfața de flux ───────────────────────────────────────────────────

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._pending + self._source.read()
            self._pending = b""
            self._exhausted = True
        elif self._pending:
            chunk = self._pending[:size]
            self._pending = self._pending[size:]
            if len(chunk) < size:
                chunk += self._source.read(size - len(chunk))
        else:
            chunk = self._source.read(size)

        if not chunk:
            self._exhausted = True
        self._account(chunk)
        return chunk

    def _account(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._size += len(chunk)
        if self._size > self._limit:
            # Se oprește aici, nu după ce fișierul a ajuns întreg pe disc.
            raise FileValidationError(
                DocumentErrorCode.FILE_TOO_LARGE,
                f"Fișierul depășește limita de {self._limit // (1024 * 1024)} MB.",
            )
        self._digest.update(chunk)

    # ── Rezultatul ──────────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self._exhausted

    @property
    def result(self) -> InspectedFile:
        """Ce s-a citit efectiv. Valabil doar după consumarea integrală a fluxului."""
        if not self._exhausted:
            raise RuntimeError("Fluxul nu a fost citit până la capăt.")
        return InspectedFile(
            mime_type=self.mime_type,
            size=self._size,
            sha256=self._digest.hexdigest(),
        )


def sha256_of(stream: BinaryIO, *, chunk_size: int = READ_CHUNK) -> str:
    """SHA-256 în flux, fără să încarce fișierul în memorie (§11)."""
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()
