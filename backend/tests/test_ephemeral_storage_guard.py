"""Documentele nu au voie să ajungă pe un disc care dispare (§3).

**Cazul concret.** Pe Vercel, fiecare invocare de funcție primește un filesystem
propriu, aruncat la final. `STORAGE_PROVIDER=local` acolo **nu eșuează**:
scrierea în `/tmp` reușește, providerul întoarce o cheie, documentul primește
rând în baza de date și apare pe ecran ca orice alt document.

Abia la invocarea următoare fișierul nu mai există — iar atunci există deja un
rând care spune că există. Un registru care trimite către fișiere inexistente se
descoperă la un control, luni mai târziu, când nu mai este de unde să fie refăcut.

Este exact categoria pe care auditul o numește blocantă: **pierdere tăcută de
date**. De aceea pornirea se oprește, în loc să avertizeze.

**Ce nu face verificarea:** nu interzice `local` în general. Pe un server
obișnuit, cu volum persistent, `local` este configurarea corectă și rămâne
implicitul.
"""

from __future__ import annotations

import pytest

from app.core.config import EPHEMERAL_FILESYSTEM_MARKERS, Environment, Settings


def settings_for(**overrides: object) -> Settings:
    """`Settings` construit direct, fără cache.

    `get_settings` este memorat cu `lru_cache`, deci nu se poate folosi într-un
    test care schimbă mediul: ar întoarce obiectul construit de primul test care
    a apucat să-l ceară.
    """
    base: dict[str, object] = {
        "secret_key": "o-cheie-de-test-suficient-de-lunga-pentru-hs256",
        "public_base_url": "https://cabinet.example.ro",
        "storage_provider": "local",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestOnAnOrdinaryServer:
    def test_local_storage_is_fine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Contra-proba: fără ea, verificarea ar putea interzice `local` peste tot."""
        for marker in EPHEMERAL_FILESYSTEM_MARKERS:
            monkeypatch.delenv(marker, raising=False)

        settings = settings_for()

        assert not settings.runs_on_ephemeral_filesystem
        settings.assert_storage_is_persistent()  # nu ridică nimic


class TestOnAnEphemeralPlatform:
    @pytest.mark.parametrize("marker", EPHEMERAL_FILESYSTEM_MARKERS)
    def test_local_storage_stops_the_boot(
        self, marker: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Testul pentru care există fișierul."""
        monkeypatch.setenv(marker, "1")

        settings = settings_for()

        assert settings.runs_on_ephemeral_filesystem
        with pytest.raises(RuntimeError, match="efemer"):
            settings.assert_storage_is_persistent()

    def test_the_message_says_what_to_do(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un refuz care nu spune cum se repară se ocolește, nu se rezolvă."""
        monkeypatch.setenv("VERCEL", "1")

        with pytest.raises(RuntimeError) as caught:
            settings_for().assert_storage_is_persistent()

        message = str(caught.value)
        assert "STORAGE_PROVIDER=s3" in message
        assert "S3_BUCKET" in message

    def test_s3_storage_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configurarea corectă pentru Vercel trece."""
        monkeypatch.setenv("VERCEL", "1")

        settings = settings_for(storage_provider="s3", s3_bucket="documente-cabinet")

        settings.assert_storage_is_persistent()  # nu ridică nimic

    def test_it_does_not_depend_on_the_environment_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verificarea nu trece prin `assert_production_ready`, deliberat.

        Aceea rulează doar cu `ENVIRONMENT=production`. Un deploy pe Vercel lăsat
        pe `development` ar fi sărit peste toate verificările — iar discul este
        efemer indiferent cum numim mediul.
        """
        monkeypatch.setenv("VERCEL", "1")

        for environment in (Environment.DEVELOPMENT, Environment.STAGING):
            settings = settings_for(environment=environment)
            with pytest.raises(RuntimeError, match="efemer"):
                settings.assert_storage_is_persistent()
