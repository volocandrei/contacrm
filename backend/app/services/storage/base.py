"""Contractul de stocare (ADR-004, §7).

`DocumentService` nu știe niciodată dacă fișierele stau pe disc, în S3 sau în
OneDrive — vorbește doar cu interfața asta. Implementările pentru cloud se adaugă
fără să atingă logica de business.

Metodele sunt deliberat puține și fără semantică ascunsă: cine cheamă `save` știe
că datele au ajuns la destinație sau că a primit o excepție. Nu există „poate a
mers".
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable


@runtime_checkable
class Readable(Protocol):
    """Tot ce îi trebuie lui `save`: o sursă de octeți.

    Deliberat mai îngust decât `BinaryIO` — nu avem nevoie de `seek`, `tell` sau
    `close`. Așa poate primi și un fișier, și un flux care se validează în timp ce
    este citit, fără ca vreunul să pretindă că e mai mult decât este.
    """

    def read(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Ce a rezultat efectiv din scriere — citit de la destinație, nu presupus."""

    key: str
    size: int
    sha256: str


class StorageError(Exception):
    """Eșec de stocare. Nu se confundă cu o eroare de validare a fișierului."""


class ObjectNotFoundError(StorageError):
    def __init__(self, key: str) -> None:
        # Cheia apare în log, niciodată într-un răspuns HTTP (§73).
        super().__init__(f"Obiect inexistent: {key}")
        self.key = key


@runtime_checkable
class StorageProvider(Protocol):
    """Operațiile pe care le poate cere restul aplicației."""

    def save(self, key: str, stream: Readable) -> StoredObject:
        """Scrie conținutul la cheia dată și întoarce ce s-a scris efectiv.

        Scrierea este atomică din punctul de vedere al cititorilor: nimeni nu vede
        un fișier pe jumătate scris. Dacă `key` există deja, scrierea eșuează —
        suprascrierea tăcută a unui document contabil nu este niciodată intenția
        cuiva (R8).
        """
        ...

    def open(self, key: str) -> BinaryIO:
        """Deschide obiectul pentru citire în flux, fără să-l încarce în memorie."""
        ...

    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Citește obiectul în bucăți — folosit pentru streaming HTTP."""
        ...

    def iter_range(
        self, key: str, start: int, end: int, chunk_size: int = 64 * 1024
    ) -> Iterator[bytes]:
        """Citește octeții din intervalul [start, end] inclusiv.

        Browserele cer intervale când afișează un PDF: fără asta, fiecare derulare
        ar reciti fișierul de la început.
        """
        ...

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int: ...

    def delete(self, key: str) -> bool:
        """Șterge obiectul. Întoarce False dacă nu exista — ștergerea e idempotentă."""
        ...

    def copy(self, source_key: str, target_key: str) -> StoredObject:
        """Copiază. Originalul rămâne neatins — asta folosește arhivarea (§16)."""
        ...

    def move(self, source_key: str, target_key: str) -> StoredObject: ...
