"""Stocare și chei — inclusiv tentativele de a ieși din spațiul de stocare.

Nu are nevoie de bază de date: rulează întotdeauna.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest

from app.services.storage import (
    InvalidStorageKeyError,
    LocalStorageProvider,
    ObjectNotFoundError,
    StorageError,
    archive_key,
    original_key,
    validate_key,
)
from app.services.storage.keys import extension_for, is_within

ORG = uuid.UUID(int=1)
DOC = uuid.UUID(int=2)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


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


# ── Provider ─────────────────────────────────────────────────────────────────


class TestLocalStorage:
    def test_save_reports_what_was_actually_written(self, storage: LocalStorageProvider) -> None:
        content = b"%PDF-1.7" + b"x" * 1000
        stored = storage.save("a/b.pdf", io.BytesIO(content))

        assert stored.size == len(content)
        assert stored.key == "a/b.pdf"
        assert storage.exists("a/b.pdf")
        assert storage.size("a/b.pdf") == len(content)

    def test_round_trip_preserves_bytes(self, storage: LocalStorageProvider) -> None:
        content = bytes(range(256)) * 10
        storage.save("a/b.pdf", io.BytesIO(content))
        with storage.open("a/b.pdf") as handle:
            assert handle.read() == content

    def test_iter_chunks_streams_the_whole_object(self, storage: LocalStorageProvider) -> None:
        content = b"y" * 200_000
        storage.save("a/b.pdf", io.BytesIO(content))
        assert b"".join(storage.iter_chunks("a/b.pdf", chunk_size=4096)) == content

    def test_existing_key_is_never_overwritten(self, storage: LocalStorageProvider) -> None:
        """Suprascrierea tăcută a unui document contabil nu e intenția nimănui (R8)."""
        storage.save("a/b.pdf", io.BytesIO(b"primul"))
        with pytest.raises(StorageError):
            storage.save("a/b.pdf", io.BytesIO(b"al doilea"))
        with storage.open("a/b.pdf") as handle:
            assert handle.read() == b"primul"

    def test_missing_object_raises_not_found(self, storage: LocalStorageProvider) -> None:
        with pytest.raises(ObjectNotFoundError):
            storage.open("a/lipsa.pdf")
        with pytest.raises(ObjectNotFoundError):
            storage.size("a/lipsa.pdf")

    def test_delete_is_idempotent(self, storage: LocalStorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"x"))
        assert storage.delete("a/b.pdf") is True
        assert storage.delete("a/b.pdf") is False

    def test_copy_keeps_the_source(self, storage: LocalStorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"continut"))
        stored = storage.copy("a/b.pdf", "c/d.pdf")

        assert storage.exists("a/b.pdf")
        assert storage.exists("c/d.pdf")
        assert stored.size == len(b"continut")

    def test_move_removes_the_source(self, storage: LocalStorageProvider) -> None:
        storage.save("a/b.pdf", io.BytesIO(b"continut"))
        storage.move("a/b.pdf", "c/d.pdf")

        assert not storage.exists("a/b.pdf")
        assert storage.exists("c/d.pdf")

    def test_copying_a_missing_object_fails(self, storage: LocalStorageProvider) -> None:
        with pytest.raises(ObjectNotFoundError):
            storage.copy("a/lipsa.pdf", "c/d.pdf")

    def test_nothing_is_written_outside_the_root(
        self, storage: LocalStorageProvider, tmp_path: Path
    ) -> None:
        with pytest.raises(InvalidStorageKeyError):
            storage.save("../scapat.pdf", io.BytesIO(b"x"))
        assert not (tmp_path / "scapat.pdf").exists()

    def test_a_partial_write_leaves_nothing_behind(self, storage: LocalStorageProvider) -> None:
        """Scrierea e atomică: un flux care explodează nu lasă un fișier trunchiat."""

        class Exploding(io.BytesIO):
            def read(self, size: int = -1) -> bytes:  # type: ignore[override]
                raise OSError("disc plin")

        with pytest.raises(OSError, match="disc plin"):
            storage.save("a/b.pdf", Exploding(b"x"))

        assert not storage.exists("a/b.pdf")
        # Nici temporarul nu rămâne.
        assert list((storage.root / "a").glob("*")) == []

    def test_exists_says_no_for_an_invalid_key(self, storage: LocalStorageProvider) -> None:
        assert storage.exists("../../etc/passwd") is False
