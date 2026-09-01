"""Stocare pe disc local — implementarea de MVP (ADR-004).

Trei lucruri merită atenție:

1. **Fiecare cheie este validată de două ori.** O dată de `validate_key`, care
   refuză tot ce ar putea traversa directoare, și încă o dată după rezolvarea căii,
   comparând rezultatul cu rădăcina. A doua verificare prinde și cazurile de
   symlink, unde textul cheii este inofensiv dar destinația nu.

2. **Scrierea este atomică.** Se scrie într-un fișier temporar din același director
   și se redenumește la final. Un cititor nu vede niciodată conținut parțial, iar o
   întrerupere nu lasă un document trunchiat care ar trece drept complet.

3. **Nu se suprascrie nimic.** `save` eșuează dacă cheia există deja.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.core.logging import get_logger
from app.services.storage.base import ObjectNotFoundError, Readable, StorageError, StoredObject
from app.services.storage.keys import InvalidStorageKeyError, validate_key

logger = get_logger(__name__)

CHUNK_SIZE = 64 * 1024


class LocalStorageProvider:
    """Fișiere sub un director rădăcină, care nu este servit direct de niciun webserver (§51)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Rezolvarea căilor ───────────────────────────────────────────────────

    def _path(self, key: str) -> Path:
        validate_key(key)
        candidate = (self.root / key).resolve()
        # A doua barieră: după rezolvare, calea trebuie să fie tot sub rădăcină.
        # `validate_key` a exclus deja `..`, dar un symlink plasat în arbore ar putea
        # trimite în altă parte, iar asta se vede doar aici.
        if not candidate.is_relative_to(self.root):
            raise StorageError(f"Cheia iese din spațiul de stocare: {key}")
        return candidate

    # ── Scriere ─────────────────────────────────────────────────────────────

    def save(self, key: str, stream: Readable) -> StoredObject:
        target = self._path(key)
        if target.exists():
            # Suprascrierea unui document contabil nu este niciodată intenția
            # cuiva; dacă e nevoie de o versiune nouă, se folosește altă cheie.
            raise StorageError(f"Cheia există deja: {key}")

        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        # Temporarul stă în același director ca destinația, ca `replace` să fie o
        # redenumire atomică și nu o copiere între volume.
        descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                while chunk := stream.read(CHUNK_SIZE):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                handle.flush()
                # Forțăm scrierea pe disc înainte de redenumire: altfel un crash
                # poate lăsa un fișier cu nume corect și conținut lipsă.
                os.fsync(handle.fileno())
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        logger.info("storage_saved", key=key, size=size)
        return StoredObject(key=key, size=size, sha256=digest.hexdigest())

    # ── Citire ──────────────────────────────────────────────────────────────

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.open("rb")

    def iter_chunks(self, key: str, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
        with self.open(key) as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def iter_range(
        self, key: str, start: int, end: int, chunk_size: int = CHUNK_SIZE
    ) -> Iterator[bytes]:
        remaining = end - start + 1
        if remaining <= 0:
            return
        with self.open(key) as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except (StorageError, InvalidStorageKeyError):
            # O cheie invalidă nu „există", dar nici nu e o eroare de pus în calea
            # apelantului: răspunsul corect la „ai asta?" este nu.
            return False

    def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.stat().st_size

    # ── Mutare, copiere, ștergere ───────────────────────────────────────────

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        logger.info("storage_deleted", key=key)
        return True

    def copy(self, source_key: str, target_key: str) -> StoredObject:
        source = self._path(source_key)
        if not source.is_file():
            raise ObjectNotFoundError(source_key)
        with source.open("rb") as handle:
            return self.save(target_key, handle)

    def move(self, source_key: str, target_key: str) -> StoredObject:
        stored = self.copy(source_key, target_key)
        self._path(source_key).unlink()
        logger.info("storage_moved", source=source_key, target=target_key)
        return stored


__all__ = ["CHUNK_SIZE", "LocalStorageProvider"]
