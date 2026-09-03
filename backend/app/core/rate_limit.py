"""Limitarea încercărilor de autentificare (§43).

**De ce doar autentificarea.** Restul rutelor cer deja o sesiune validă, iar un
utilizator autentificat care încarcă o sută de documente face exact ce trebuie să
facă. Locul unde numărul de încercări chiar contează este cel unde încercarea nu
costă nimic și răspunsul spune dacă ai ghicit: autentificarea.

**Ce înlocuiește.** Nimic — și asta era problema. `RATE_LIMIT_PER_MINUTE` exista
în configurare și în `.env.example` de la început, dar nu îl citea niciun modul. O
variabilă care promite o protecție inexistentă este mai rea decât absența ei: cine
o vede în configurare crede că este protejat.

Singura barieră reală era costul Argon2id — măsurat, ~200 ms pe încercare. Asta
mărginește un atac la câteva mii de parole pe oră, ceea ce pentru o listă de parole
comune nu este de ajuns.

**Se numără eșecurile, nu încercările.** Prima variantă le număra pe toate, iar
suita end-to-end a arătat imediat de ce nu merge: un client care se autentifică de
unsprezece ori într-un minut cu parola **corectă** era refuzat. Cine ghicește
parola este oricum înăuntru, deci contorul nu mai apără nimic după o reușită; ce
merită numărat este eșecul.

**Limita ei.** Contorul stă în proces. Două procese de API înseamnă două contoare,
iar pe o platformă care pornește un proces per cerere nu limitează nimic. Este
protecția potrivită pentru instalarea din documentație — un container de API pe
serverul cabinetului — și trebuie dublată la marginea rețelei acolo unde există un
proxy. Nu pretinde mai mult decât atât.

Fereastră fixă, nu glisantă: la limita dintre două ferestre se pot strecura până la
de două ori mai multe eșecuri. Diferența nu contează pentru un prag de zece pe
minut, iar o fereastră glisantă ar cere memorie per încercare, nu per cheie.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Final

WINDOW_SECONDS: Final = 60.0

# Peste câte chei urmărite se face curățenie. Un atac distribuit ar umple altfel
# dicționarul cu o intrare per adresă, la nesfârșit.
_CLEANUP_THRESHOLD: Final = 4096


@dataclass(frozen=True, slots=True)
class Decision:
    """Ce se știe despre o cheie, chiar acum."""

    allowed: bool
    #: Câte secunde până când fereastra curentă se închide. Ajunge în `Retry-After`.
    retry_after: int = 0


@dataclass
class FixedWindowLimiter:
    """Câte eșecuri per cheie într-o fereastră de un minut.

    Cele două operații sunt separate deliberat: `blocked` se pune **înaintea**
    încercării, `record` **după**, și numai dacă a eșuat. O singură metodă care ar
    face amândouă ar fi trebuit să numere și reușitele — exact greșeala pe care a
    prins-o suita end-to-end.
    """

    limit: int
    _failures: dict[str, tuple[float, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def enabled(self) -> bool:
        """Zero sau negativ înseamnă „fără limită", nu „blochează tot".

        Altfel o configurare greșită ar închide autentificarea pentru toată lumea —
        adică ar transforma protecția într-o pană.
        """
        return self.limit > 0

    def blocked(self, key: str, *, now: float | None = None) -> Decision:
        """Este cheia peste prag chiar acum? Nu modifică nimic.

        `now` există pentru teste: un test care așteaptă un minut real nu este un
        test, este o pauză.
        """
        if not self.enabled:
            return Decision(allowed=True)

        moment = time.monotonic() if now is None else now
        with self._lock:
            started, count = self._failures.get(key, (moment, 0))
            if moment - started >= WINDOW_SECONDS or count < self.limit:
                return Decision(allowed=True)
            remaining = WINDOW_SECONDS - (moment - started)
            return Decision(allowed=False, retry_after=max(1, int(remaining) + 1))

    def record(self, key: str, *, now: float | None = None) -> None:
        """Înregistrează un eșec."""
        if not self.enabled:
            return

        moment = time.monotonic() if now is None else now
        with self._lock:
            self._forget_old(moment)
            started, count = self._failures.get(key, (moment, 0))
            if moment - started >= WINDOW_SECONDS:
                started, count = moment, 0
            self._failures[key] = (started, count + 1)

    def _forget_old(self, moment: float) -> None:
        if len(self._failures) < _CLEANUP_THRESHOLD:
            return
        self._failures = {
            key: value
            for key, value in self._failures.items()
            if moment - value[0] < WINDOW_SECONDS
        }

    def reset(self) -> None:
        """Golește contoarele. Pentru teste; nu are apelant în producție."""
        with self._lock:
            self._failures.clear()


__all__ = ["WINDOW_SECONDS", "Decision", "FixedWindowLimiter"]
