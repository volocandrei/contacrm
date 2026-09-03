"""Stocare și chei — inclusiv tentativele de a ieși din spațiul de stocare.

Nu are nevoie de bază de date: rulează întotdeauna.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services.storage import (
    InvalidStorageKeyError,
    LocalStorageProvider,
    ObjectNotFoundError,
    S3StorageProvider,
    StorageError,
    StorageProvider,
    archive_key,
    build_storage_provider,
    original_key,
    validate_key,
)
from app.services.storage.keys import extension_for, is_within
from app.services.storage.s3 import SHA256_METADATA

ORG = uuid.UUID(int=1)
DOC = uuid.UUID(int=2)

S3_BUCKET = "contacrm-test"
S3_REGION = "eu-central-1"


# ── Chei ─────────────────────────────────────────────────────────────────────


class TestKeyGeneration:
    def test_key_is_built_from_ids_only(self) -> None:
        """Numele trimis de expeditor nu participă niciodată la construirea cheii."""
        key = original_key(ORG, DOC, mime_type="application/pdf")
        assert key == (f"organizations/{ORG}/documents/{DOC}/original/source.pdf")

    def test_extension_comes_from_the_verified_content_type(self) -> None:
        assert original_key(ORG, DOC, mime_type="image/jpeg").endswith("/source.jpg")
        assert original_key(ORG, DOC, mime_type="image/png").endswith("/source.png")

    def test_unknown_content_type_has_no_key(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            extension_for("application/x-msdownload")

    def test_every_accepted_type_can_be_stored(self) -> None:
        """Ce trece de validarea la încărcare trebuie să poată primi o cheie.

        Aici a fost defectul: extensiile erau scrise de trei ori — în
        `domain/filenames.py`, în `lib/filename.ts` și încă o dată aici. Când s-a
        adăugat factura electronică, două au fost aduse la zi și a treia nu, iar
        încărcarea unui XML cădea cu 500 **după** ce fișierul trecuse validarea.
        Testul citește lista acceptată din configurare, nu una ținută minte, ca
        următorul tip adăugat să nu poată repeta povestea.
        """
        for mime_type in settings.allowed_mime_type_set:
            assert extension_for(mime_type), mime_type

    def test_archive_key_is_separate_from_the_original(self) -> None:
        """Originalul nu se suprascrie la arhivare (§16)."""
        original = original_key(ORG, DOC, mime_type="application/pdf")
        archive = archive_key(ORG, DOC, mime_type="application/pdf")
        assert original != archive
        assert "/original/" in original
        assert "/archive/" in archive

    def test_archive_versions_do_not_collide(self) -> None:
        first = archive_key(ORG, DOC, mime_type="application/pdf", version=1)
        second = archive_key(ORG, DOC, mime_type="application/pdf", version=2)
        assert first != second

    def test_keys_are_scoped_to_the_organization(self) -> None:
        key = original_key(ORG, DOC, mime_type="application/pdf")
        assert is_within(key, ORG)
        assert not is_within(key, uuid.uuid4())


class TestKeyValidation:
    """§8, §14 — nicio cheie nu are voie să iasă din spațiul de stocare."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../etc/passwd",
            "a/../../b",
            "/etc/passwd",
            "/absolute",
            "..",
            "a/../b",
            "a//b",
            "a/./b",
            "",
        ],
        ids=[
            "traversare",
            "traversare-imbricata",
            "absoluta-unix",
            "absoluta",
            "doar-punct-punct",
            "punct-punct-in-mijloc",
            "segment-gol",
            "punct-curent",
            "goala",
        ],
    )
    def test_path_traversal_is_refused(self, hostile: str) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_key(hostile)

    def test_windows_paths_are_refused(self) -> None:
        for hostile in ("C:\\Windows\\system32", "a\\b", "..\\..\\secret"):
            with pytest.raises(InvalidStorageKeyError):
                validate_key(hostile)

    def test_control_characters_are_refused(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_key("a/b\x00c")
        with pytest.raises(InvalidStorageKeyError):
            validate_key("a/\x1fb")

    def test_uppercase_and_spaces_are_refused(self) -> None:
        """Cheile sunt generate, deci pot fi ținute într-un alfabet strict."""
        with pytest.raises(InvalidStorageKeyError):
            validate_key("Organizations/x")
        with pytest.raises(InvalidStorageKeyError):
            validate_key("a/nume cu spatii")

    def test_a_generated_key_always_validates(self) -> None:
        for mime in ("application/pdf", "image/jpeg", "image/png", "image/webp"):
            validate_key(original_key(uuid.uuid4(), uuid.uuid4(), mime_type=mime))
            validate_key(archive_key(uuid.uuid4(), uuid.uuid4(), mime_type=mime))


# ── Provideri ────────────────────────────────────────────────────────────────
#
# Ce urmează descrie **contractul**, nu o implementare. De aceea fiecare test
# rulează de două ori: o dată pe disc, o dată pe un serviciu compatibil S3.
#
# Asta contează dincolo de acoperire. Un provider nou nu se validează citindu-l:
# se validează punându-l sub aceleași întrebări la care răspunde deja cel vechi —
# nu suprascrii nimic? spui adevărul despre ce ai scris? refuzi o cheie ostilă?
# Dacă răspunde la fel, `DocumentService` nu are cum să simtă diferența, iar asta
# este exact promisiunea din ADR-004.
#
# S3-ul este simulat (`moto`): testele nu ating rețeaua și nu cer credențiale.


@pytest.fixture
def local_storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def s3_storage() -> Iterator[S3StorageProvider]:
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.create_bucket(
            Bucket=S3_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": S3_REGION},
        )
        yield S3StorageProvider(client, S3_BUCKET)


@pytest.fixture(params=["local", "s3"])
def storage(request: pytest.FixtureRequest) -> StorageProvider:
    """Același test, pe fiecare provider care există."""
    provider: StorageProvider = request.getfixturevalue(f"{request.param}_storage")
    return provider


class TestStorageContract:
    """Ce trebuie să facă orice provider, indiferent unde ajung octeții."""

    def test_save_reports_what_was_actually_written(self, storage: StorageProvider) -> None:
        content = b"%PDF-1.7" + b"x" * 1000
        stored = storage.save("a/b.pdf", io.BytesIO(content))

        assert stored.size == len(content)
        assert stored.key == "a/b.pdf"
        assert stored.sha256 == hashlib.sha256(content).hexdigest()
        assert storage.exists("a/b.pdf")
        assert storage.size("a/b.pdf") == len(content)

    def test_round_trip_preserves_bytes(self, storage: StorageProvider) -> None:
        content = bytes(range(256)) * 10
        storage.save("a/b.pdf", io.BytesIO(content))
        with storage.open("a/b.pdf") as handle:
            assert handle.read() == content

    def test_iter_chunks_streams_the_whole_object(self, storage: StorageProvider) -> None:
        content = b"y" * 200_000
        storage.save("a/b.pdf", io.BytesIO(content))
        assert b"".join(storage.iter_chunks("a/b.pdf", chunk_size=4096)) == content

    def test_iter_range_returns_exactly_the_asked_bytes(self, storage: StorageProvider) -> None:
        """Browserul cere intervale când afișează un PDF; capetele sunt inclusive."""
        content = bytes(range(256)) * 40
        storage.save("a/b.pdf", io.BytesIO(content))

        assert b"".join(storage.iter_range("a/b.pdf", 0, 9)) == content[:10]
        assert b"".join(storage.iter_range("a/b.pdf", 100, 199)) == content[100:200]
        assert b"".join(storage.iter_range("a/b.pdf", 5, 5)) == content[5:6]

    def test_an_empty_range_yields_nothing(self, storage: StorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"continut"))
        assert b"".join(storage.iter_range("a/b.pdf", 5, 4)) == b""

    def test_existing_key_is_never_overwritten(self, storage: StorageProvider) -> None:
        """Suprascrierea tăcută a unui document contabil nu e intenția nimănui (R8)."""
        storage.save("a/b.pdf", io.BytesIO(b"primul"))
        with pytest.raises(StorageError):
            storage.save("a/b.pdf", io.BytesIO(b"al doilea"))
        with storage.open("a/b.pdf") as handle:
            assert handle.read() == b"primul"

    def test_missing_object_raises_not_found(self, storage: StorageProvider) -> None:
        with pytest.raises(ObjectNotFoundError):
            storage.open("a/lipsa.pdf")
        with pytest.raises(ObjectNotFoundError):
            storage.size("a/lipsa.pdf")

    def test_delete_is_idempotent(self, storage: StorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"x"))
        assert storage.delete("a/b.pdf") is True
        assert storage.delete("a/b.pdf") is False

    def test_copy_keeps_the_source(self, storage: StorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"continut"))
        stored = storage.copy("a/b.pdf", "c/d.pdf")

        assert storage.exists("a/b.pdf")
        assert storage.exists("c/d.pdf")
        assert stored.size == len(b"continut")
        assert stored.sha256 == hashlib.sha256(b"continut").hexdigest()

    def test_a_copy_holds_the_same_bytes(self, storage: StorageProvider) -> None:
        content = b"%PDF-1.7" + bytes(range(256))
        storage.save("a/b.pdf", io.BytesIO(content))
        storage.copy("a/b.pdf", "c/d.pdf")
        with storage.open("c/d.pdf") as handle:
            assert handle.read() == content

    def test_copying_over_an_existing_key_is_refused(self, storage: StorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"primul"))
        storage.save("c/d.pdf", io.BytesIO(b"al doilea"))
        with pytest.raises(StorageError):
            storage.copy("a/b.pdf", "c/d.pdf")
        with storage.open("c/d.pdf") as handle:
            assert handle.read() == b"al doilea"

    def test_move_removes_the_source(self, storage: StorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"continut"))
        storage.move("a/b.pdf", "c/d.pdf")

        assert not storage.exists("a/b.pdf")
        assert storage.exists("c/d.pdf")

    def test_copying_a_missing_object_fails(self, storage: StorageProvider) -> None:
        with pytest.raises(ObjectNotFoundError):
            storage.copy("a/lipsa.pdf", "c/d.pdf")

    def test_a_hostile_key_never_reaches_the_backend(self, storage: StorageProvider) -> None:
        with pytest.raises(InvalidStorageKeyError):
            storage.save("../scapat.pdf", io.BytesIO(b"x"))

    def test_exists_says_no_for_an_invalid_key(self, storage: StorageProvider) -> None:
        assert storage.exists("../../etc/passwd") is False

    def test_a_partial_write_leaves_nothing_behind(self, storage: StorageProvider) -> None:
        """Un flux care explodează la jumătate nu are voie să lase un obiect trunchiat."""

        class Exploding(io.BytesIO):
            def read(self, size: int = -1) -> bytes:  # type: ignore[override]
                raise OSError("disc plin")

        with pytest.raises(OSError, match="disc plin"):
            storage.save("a/b.pdf", Exploding(b"x"))

        assert not storage.exists("a/b.pdf")


class TestLocalStorageSpecifics:
    """Ce ține de disc și nu are corespondent în altă parte."""

    def test_nothing_is_written_outside_the_root(
        self, local_storage: LocalStorageProvider, tmp_path: Path
    ) -> None:
        with pytest.raises(InvalidStorageKeyError):
            local_storage.save("../scapat.pdf", io.BytesIO(b"x"))
        assert not (tmp_path / "scapat.pdf").exists()

    def test_a_failed_write_leaves_no_temporary_file(
        self, local_storage: LocalStorageProvider
    ) -> None:
        """Atomicitatea vine din `rename`; temporarul nu are voie să supraviețuiască."""

        class Exploding(io.BytesIO):
            def read(self, size: int = -1) -> bytes:  # type: ignore[override]
                raise OSError("disc plin")

        with pytest.raises(OSError, match="disc plin"):
            local_storage.save("a/b.pdf", Exploding(b"x"))

        assert list((local_storage.root / "a").glob("*")) == []


class TestS3StorageSpecifics:
    """Ce ține de protocolul S3 și nu are corespondent pe disc."""

    def test_the_prefix_separates_environments_sharing_a_bucket(
        self, s3_storage: S3StorageProvider
    ) -> None:
        staging = S3StorageProvider(s3_storage._client, S3_BUCKET, prefix="staging")
        production = S3StorageProvider(s3_storage._client, S3_BUCKET, prefix="prod")

        staging.save("a/b.pdf", io.BytesIO(b"din staging"))

        assert staging.exists("a/b.pdf")
        assert not production.exists("a/b.pdf")
        # Și nici la rădăcină: prefixul chiar ajunge în cheia obiectului.
        assert not s3_storage.exists("a/b.pdf")

    def test_a_prefix_with_slashes_does_not_produce_empty_segments(
        self, s3_storage: S3StorageProvider
    ) -> None:
        provider = S3StorageProvider(s3_storage._client, S3_BUCKET, prefix="/medii/test/")
        assert provider._object("a/b.pdf") == "medii/test/a/b.pdf"

    def test_the_digest_travels_with_the_object(self, s3_storage: S3StorageProvider) -> None:
        """Copierea se face server-side; amprenta vine din metadate, nu dintr-o recitire."""
        content = b"%PDF-1.7" + b"z" * 500
        s3_storage.save("a/b.pdf", io.BytesIO(content))

        head = s3_storage._client.head_object(Bucket=S3_BUCKET, Key="a/b.pdf")
        assert head["Metadata"][SHA256_METADATA] == hashlib.sha256(content).hexdigest()

    def test_an_object_without_our_metadata_still_gets_a_truthful_digest(
        self, s3_storage: S3StorageProvider
    ) -> None:
        """Un obiect pus în bucket de altcineva nu are metadata noastră.

        `StoredObject` care minte despre `sha256` ar fi mai rău decât unul obținut
        lent, deci în cazul ăsta amprenta se calculează citind copia.
        """
        content = b"pus de altcineva"
        s3_storage._client.put_object(Bucket=S3_BUCKET, Key="a/strain.pdf", Body=content)

        stored = s3_storage.copy("a/strain.pdf", "c/copie.pdf")
        assert stored.sha256 == hashlib.sha256(content).hexdigest()

    def test_a_bucketless_provider_refuses_to_exist(self, s3_storage: S3StorageProvider) -> None:
        """Mai bine o excepție la construire decât un `NoSuchBucket` la primul upload."""
        with pytest.raises(StorageError):
            S3StorageProvider(s3_storage._client, "")


class TestProviderChoice:
    """`STORAGE_PROVIDER` chiar decide ce se construiește."""

    def test_local_is_the_default(self, tmp_path: Path) -> None:
        config = Settings(storage_path=str(tmp_path / "storage"))
        assert isinstance(build_storage_provider(config), LocalStorageProvider)

    def test_s3_is_built_when_asked(self) -> None:
        config = Settings(
            storage_provider="s3",
            s3_bucket="contacrm",
            s3_access_key_id="test",
            s3_secret_access_key="test",
        )
        provider = build_storage_provider(config)
        assert isinstance(provider, S3StorageProvider)
        assert provider.bucket == "contacrm"

    def test_an_unknown_provider_stops_startup(self) -> None:
        """O valoare scrisă greșit nu are voie să cadă tăcut pe disc local."""
        with pytest.raises(ValidationError):
            Settings(storage_provider="s4")

    def test_production_refuses_s3_without_a_bucket(self) -> None:
        config = Settings(
            environment="production",
            secret_key="un-secret-real-si-suficient-de-lung",
            storage_provider="s3",
        )
        with pytest.raises(RuntimeError, match="S3_BUCKET"):
            config.assert_production_ready()
