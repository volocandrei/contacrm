"""Ce zi este, pentru cabinet (§33, §34).

**De ce nu `datetime.now(UTC).date()`.** Momentele se stochează in UTC, si asa
trebuie sa ramana: un `received_at` fara fus nu se poate compara cu nimic. Dar
**ziua** nu este un moment, este o intrare in calendarul cabinetului — iar
calendarul acela este la Bucuresti, unde ceasul merge cu doua ore inaintea UTC
iarna si cu trei vara.

Diferenta se vede intre miezul noptii si ora 2 sau 3 dimineata, cand ziua locala
s-a schimbat si cea UTC inca nu. Acolo:

- un onorariu marcat platit la 01:00 pe 1 septembrie s-ar fi scris **31 august**,
  adica in luna trecuta a cabinetului, dupa ce ea fusese inchisa;
- un reminder trimis de planificator la 01:30 pe 26 s-ar fi comparat cu ziua 25 si
  ar fi plecat catre client **dupa termen**, cu fraza „ca sa depunem la timp";
- o declaratie s-ar fi aratat scadenta o zi mai tarziu decat este.

Nimic din toate astea nu apare in vreo consola. Se vede in registre.

Panoul principal facea deja socoteala corect, cu `ZoneInfo(default_timezone)`.
Restul aplicatiei se uita la UTC. Doua raspunsuri diferite la aceeasi intrebare,
in acelasi produs; fisierul asta le face unul singur.

**Se poate inlocui la test.** `now()` este o functie, nu un apel imprastiat prin
cod: un test o inlocuieste si verifica exact minutul in care cele doua zile difera.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def now() -> datetime:
    """Momentul, in UTC. Singurul loc din care se citeste ceasul."""
    return datetime.now(UTC)


def zone() -> ZoneInfo:
    """Fusul cabinetului, din configurare."""
    return ZoneInfo(settings.default_timezone)


def today() -> date:
    """Ziua din calendarul cabinetului, nu din cel al serverului."""
    return now().astimezone(zone()).date()


__all__ = ["now", "today", "zone"]
