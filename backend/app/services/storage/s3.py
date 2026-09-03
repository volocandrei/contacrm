"""Stocare pe un serviciu compatibil S3 (ADR-004, §51).

Există pentru că `LocalStorageProvider` presupune un disc care supraviețuiește
repornirii. Într-un mediu unde procesul rulează în containere efemere — Vercel,
Cloud Run, orice autoscaler — discul dispare între invocări, iar o probă contabilă
nu are voie să dispară (R8). Vezi `docs/DEPLOY.md`.

Nu este „providerul pentru AWS": este providerul pentru **protocolul** S3. Aceeași
clasă vorbește cu AWS S3, cu Supabase Storage, cu Cloudflare R2 și cu un MinIO
local — se schimbă doar `S3_ENDPOINT_URL`. Asta contează practic: furnizorul de
obiecte poate fi schimbat fără să se atingă o linie de logică.

**Ce rămâne la fel ca la disc**, pentru că sunt garanții ale contractului, nu
detalii de implementare:

- documentele nu sunt publice — nu se generează niciodată URL-uri semnate și
  bucket-ul nu are voie să fie citibil anonim; tot ce iese trece prin API, care
  verifică organizația (§51, §72);
- nu se suprascrie nimic: `save` eșuează dacă cheia există deja (R8);
- cheile sunt validate înainte de a atinge rețeaua, exact ca înainte de a atinge
  discul (§8).

**Ce este diferit, și merită spus pe față.** Local, atomicitatea vine din
`rename`. Aici vine din faptul că `PUT` este atomic prin definiție: un obiect
există complet sau nu există deloc. Ca să existe un `Content-Length` — și ca un
flux care crapă la jumătate să nu ajungă niciodată în rețea — conținutul este
întâi tamponat (în memorie până la un prag, apoi pe disc temporar), și abia
fluxul complet este trimis.

Protecția la suprascriere se sprijină pe două lucruri: o verificare `HEAD`
înainte și `If-None-Match: *` pe `PUT`. A doua este cea care închide cursa între
două scrieri simultane, dar nu toate implementările compatibile S3 o respectă;
acolo unde nu este respectată rămâne doar prima, care este suficientă în practică
(cheile sunt generate din UUID-uri, deci două scrieri pe aceeași cheie înseamnă
deja un bug în altă parte) fără să fie o garanție.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, BinaryIO, Final

from botocore.exceptions import ClientError

from app.core.logging import get_logger
from app.services.storage.base import ObjectNotFoundError, Readable, StorageError, StoredObject
from app.services.storage.keys import InvalidStorageKeyError, validate_key

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer
    from mypy_boto3_s3.client import S3Client

logger = get_logger(__name__)

CHUNK_SIZE: Final = 64 * 1024

# Peste acest prag, tamponul de scriere trece de la memorie la un fișier temporar.
# Un upload de 25 MB nu are voie să stea întreg în heap-ul unui proces care servește
# și alte cereri în paralel.
SPOOL_MAX_BYTES: Final = 2 * 1024 * 1024

# Amprenta se scrie ca metadată la `save`, ca o copiere server-side să nu ne oblige
# ulterior să recitim obiectul doar ca să știm ce conține. S3 coboară cheile de
# metadate la litere mici, deci o scriem deja așa.
SHA256_METADATA: Final = "sha256"

# Ce răspunde un serviciu compatibil S3 când obiectul nu există. `404` apare la
# `head_object`, unde corpul erorii este gol și nu există cod simbolic.
_MISSING_CODES: Final = frozenset({"404", "NoSuchKey", "NotFound"})

# Ce răspunde când `If-None-Match: *` a prins o cheie deja existentă.
_EXISTS_CODES: Final = frozenset({"412", "PreconditionFailed"})


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class _StreamingRaw(io.RawIOBase):
    """Corpul răspunsului S3 prezentat ca fișier binar.

    Fără asta, `open()` ar trebui să descarce tot obiectul ca să întoarcă ceva pe
    care se poate face `read` — adică exact ce promite contractul că nu se
    întâmplă („fără să-l încarce în memorie"). Așa, octeții sunt citiți din rețea
    pe măsură ce cineva îi cere.
    """

    def __init__(self, body: Any) -> None:
        super().__init__()
        self._body = body

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: WriteableBuffer, /) -> int:
        view = memoryview(buffer).cast("B")
        chunk: bytes = self._body.read(len(view))
        if not chunk:
            return 0
        view[: len(chunk)] = chunk
        return len(chunk)

    def close(self) -> None:
        try:
            self._body.close()
        finally:
            super().close()


class S3StorageProvider:
    """Obiecte într-un bucket privat, cu aceleași garanții ca providerul local."""

    def __init__(self, client: S3Client, bucket: str, *, prefix: str = "") -> None:
        if not bucket:
            raise StorageError("S3_BUCKET nu este configurat.")
        self._client = client
        self.bucket = bucket
        # Prefixul separă medii care împart un bucket (`staging/`, `prod/`). Nu este
        # o cheie de document, deci nu trece prin `validate_key`; este însă
        # normalizat, ca să nu producă `//` sau un segment gol.
        self.prefix = prefix.strip("/")

    # ── Chei ────────────────────────────────────────────────────────────────

    def _object(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    # ── Scriere ─────────────────────────────────────────────────────────────

    def save(self, key: str, stream: Readable) -> StoredObject:
        name = self._object(key)
        if self.exists(key):
            raise StorageError(f"Cheia există deja: {key}")

        digest = hashlib.sha256()
        size = 0
        # Se citește tot înainte de a trimite ceva: un flux care aruncă la jumătate
        # nu are cum să lase un obiect trunchiat în bucket, iar `PUT` primește un
        # `Content-Length` real în loc să fie semnat pe bucăți.
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES) as buffer:
            while chunk := stream.read(CHUNK_SIZE):
                buffer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            buffer.seek(0)

            try:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=name,
                    Body=buffer,
                    IfNoneMatch="*",
                    Metadata={SHA256_METADATA: digest.hexdigest()},
                )
            except ClientError as exc:
                if _error_code(exc) in _EXISTS_CODES:
                    raise StorageError(f"Cheia există deja: {key}") from exc
                raise StorageError(f"Scriere eșuată pentru cheia: {key}") from exc

        logger.info("storage_saved", key=key, size=size, backend="s3")
        return StoredObject(key=key, size=size, sha256=digest.hexdigest())

    # ── Citire ──────────────────────────────────────────────────────────────

    def _head(self, key: str) -> dict[str, Any]:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=self._object(key))
        except ClientError as exc:
            if _error_code(exc) in _MISSING_CODES:
                raise ObjectNotFoundError(key) from exc
            raise StorageError(f"Interogare eșuată pentru cheia: {key}") from exc
        return dict(response)

    def _body(self, key: str, *, byte_range: str | None = None) -> Any:
        name = self._object(key)
        try:
            if byte_range is None:
                response = self._client.get_object(Bucket=self.bucket, Key=name)
            else:
                response = self._client.get_object(Bucket=self.bucket, Key=name, Range=byte_range)
        except ClientError as exc:
            if _error_code(exc) in _MISSING_CODES:
                raise ObjectNotFoundError(key) from exc
            raise StorageError(f"Citire eșuată pentru cheia: {key}") from exc
        return response["Body"]

    def open(self, key: str) -> BinaryIO:
        return io.BufferedReader(_StreamingRaw(self._body(key)))

    def iter_chunks(self, key: str, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
        with self.open(key) as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def iter_range(
        self, key: str, start: int, end: int, chunk_size: int = CHUNK_SIZE
    ) -> Iterator[bytes]:
        if end < start:
            return
        # Intervalul se cere serverului, nu se filtrează local: altfel fiecare
        # derulare într-un PDF ar transfera fișierul de la început.
        body = self._body(key, byte_range=f"bytes={start}-{end}")
        with io.BufferedReader(_StreamingRaw(body)) as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def exists(self, key: str) -> bool:
        try:
            self._head(key)
        except (ObjectNotFoundError, InvalidStorageKeyError):
            # O cheie invalidă nu „există", dar nici nu e o eroare de pus în calea
            # apelantului: răspunsul corect la „ai asta?" este nu.
            return False
        return True

    def size(self, key: str) -> int:
        return int(self._head(key)["ContentLength"])

    # ── Mutare, copiere, ștergere ───────────────────────────────────────────

    def delete(self, key: str) -> bool:
        if not self.exists(key):
            return False
        self._client.delete_object(Bucket=self.bucket, Key=self._object(key))
        logger.info("storage_deleted", key=key, backend="s3")
        return True

    def copy(self, source_key: str, target_key: str) -> StoredObject:
        head = self._head(source_key)
        target = self._object(target_key)
        if self.exists(target_key):
            raise StorageError(f"Cheia există deja: {target_key}")

        # Copierea se face de către serviciu: octeții nu trec prin procesul nostru.
        # Arhivarea unui document de 25 MB nu are de ce să însemne 50 MB de trafic.
        try:
            self._client.copy_object(
                Bucket=self.bucket,
                Key=target,
                CopySource={"Bucket": self.bucket, "Key": self._object(source_key)},
                MetadataDirective="COPY",
            )
        except ClientError as exc:
            raise StorageError(f"Copiere eșuată către cheia: {target_key}") from exc

        metadata = head.get("Metadata") or {}
        # Amprenta scrisă la `save` călătorește cu obiectul. Dacă lipsește — obiect
        # pus în bucket de altcineva decât noi — se calculează citind copia, pentru
        # că un `StoredObject` care minte despre `sha256` e mai rău decât unul lent.
        sha256 = str(metadata.get(SHA256_METADATA) or "") or self._digest_of(target_key)

        logger.info("storage_copied", source=source_key, target=target_key, backend="s3")
        return StoredObject(key=target_key, size=int(head["ContentLength"]), sha256=sha256)

    def move(self, source_key: str, target_key: str) -> StoredObject:
        stored = self.copy(source_key, target_key)
        self.delete(source_key)
        logger.info("storage_moved", source=source_key, target=target_key, backend="s3")
        return stored

    def _digest_of(self, key: str) -> str:
        digest = hashlib.sha256()
        for chunk in self.iter_chunks(key):
            digest.update(chunk)
        return digest.hexdigest()


__all__ = ["CHUNK_SIZE", "SHA256_METADATA", "SPOOL_MAX_BYTES", "S3StorageProvider"]
