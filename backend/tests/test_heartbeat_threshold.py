"""Pragul de la care un worker este declarat mort.

**Ce apără.** Pe Vercel nu există worker continuu: coada se execută prin cron, la
cinci minute. Implicitul de nouăzeci de secunde este pentru un proces care bate
la fiecare tur — pe cron ar fi depășit **între oricare două bătăi**, deci
`/health/workers` ar răspunde 503 permanent, pe o instalare perfect sănătoasă.

Consecința nu este un 503 în plus. Este că alarma își pierde înțelesul: un
monitor care sună la fiecare verificare se tace după a treia zi, iar semnalul
construit exact ca să prindă un worker mort ajunge primul ignorat.

Reparația de până acum era o propoziție în documentație — „ridică variabila cu
mâna". Un bilet lipit pe monitor nu este o reparație.
"""

from __future__ import annotations

import pytest

from app.core.config import CRON_TICK_SECONDS, Settings


def settings_for(**overrides: object) -> Settings:
    """`Settings` construit direct: `get_settings` este memorat cu `lru_cache`."""
    base: dict[str, object] = {
        "secret_key": "o-cheie-de-test-suficient-de-lunga-pentru-hs256",
        "public_base_url": "https://cabinet.example.ro",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def on_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")


@pytest.fixture
def on_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)


class TestOnAnOrdinaryServer:
    def test_the_continuous_worker_keeps_its_threshold(self, on_a_server: None) -> None:
        """Contra-proba: fără ea, s-ar putea ridica pragul peste tot.

        Pe un server, workerul bate la fiecare tur — deci un prag lung ar
        însemna minute întregi de tăcere după ce procesul a murit.
        """
        assert settings_for().heartbeat_timeout_seconds == 90


class TestOnServerless:
    def test_the_default_would_have_been_permanently_stale(self, on_a_server: None) -> None:
        """Testul care arată **de ce** există restul fișierului.

        Dacă implicitul ar fi fost oricum peste intervalul cronului, tot ce
        urmează ar fi decor.
        """
        assert settings_for().worker_heartbeat_timeout_seconds < CRON_TICK_SECONDS

    def test_the_threshold_survives_a_missed_tick(self, on_vercel: None) -> None:
        """Cronul poate întârzia. O întârziere nu este o moarte.

        Cel puțin două ture ratate înainte de alarmă — altfel prima întârziere a
        platformei sună un om noaptea, degeaba.
        """
        assert settings_for().heartbeat_timeout_seconds >= 2 * CRON_TICK_SECONDS

    def test_but_a_dead_queue_is_still_found_the_same_morning(self, on_vercel: None) -> None:
        """Marginea cealaltă: un prag oricât de mare ar fi tăcut la fel de rău.

        Documentele așteaptă deja până la cinci minute; ce nu are voie este să
        aștepte o zi.
        """
        assert settings_for().heartbeat_timeout_seconds <= 6 * CRON_TICK_SECONDS

    def test_an_explicit_value_still_wins(self, on_vercel: None) -> None:
        """Cine pune variabila cu mâna nu este contrazis de un implicit.

        Un cron mai des, sau mai rar, se reglează din mediu — fără să atingem
        codul.
        """
        assert settings_for(worker_heartbeat_timeout_seconds=45).heartbeat_timeout_seconds == 45
