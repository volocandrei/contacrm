"""Termenele de depunere, ca mecanism — nu ca lege scrisă în cod.

**Golul.** Aplicația avea **un singur** termen, global: ziua 25, folosită de
numărătoarea inversă a lunii. Un cabinet nu trăiește așa. Un client pe TVA
trimestrial depune altcând decât unul pe lunar; salariile au termenul lor;
bilanțul, cu totul altul. Iar consecința unui termen ratat nu este o neplăcere de
interfață, este o amendă — la client, plătită de cabinet.

**Ce este certitudine aici și ce nu.** Mecanismul este cert: o obligație are o
periodicitate, iar termenul ei cade la atâtea luni după sfârșitul perioadei, în
ziua cutare. Ce **nu** este treaba aplicației: să pretindă că știe legea. Ziua și
decalajul sunt configurabile per organizație, iar catalogul de mai jos este doar
**conținutul inițial** al tabelului — la fel ca `document_types.py`.

TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: termenele din catalogul de
mai jos trebuie confirmate de un contabil, pe fiecare declarație în parte, și
ajustate din ecranul de administrare acolo unde cabinetul știe altfel. Ele sunt
puncte de plecare uzuale, nu o afirmație a aplicației despre ce spune legea.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from app.domain.enums import ObligationFrequency

#: Lunile în care se **încheie** o perioadă, pe periodicitate.
#:
#: Lunar: toate. Trimestrial: martie, iunie, septembrie, decembrie. Anual:
#: decembrie. Nu există aici nicio regulă fiscală — doar aritmetica unui calendar.
_CLOSING_MONTHS: dict[ObligationFrequency, frozenset[int]] = {
    ObligationFrequency.MONTHLY: frozenset(range(1, 13)),
    ObligationFrequency.QUARTERLY: frozenset({3, 6, 9, 12}),
    ObligationFrequency.ANNUAL: frozenset({12}),
}


@dataclass(frozen=True, slots=True)
class ObligationSeed:
    code: str
    label: str
    frequency: ObligationFrequency
    #: Câte luni după sfârșitul perioadei cade termenul. `1` = luna următoare.
    months_after: int
    #: Ziua din luna termenului. Se retează la ultima zi a lunii, vezi `_day_in`.
    deadline_day: int


#: Conținutul inițial al catalogului. Se administrează din aplicație după aceea.
#:
#: Sunt numele formularelor, nu interpretări ale legii. Fiecare termen rămâne de
#: confirmat de un contabil — vezi TODO-ul din capul fișierului.
DEFAULT_OBLIGATIONS: tuple[ObligationSeed, ...] = (
    ObligationSeed("D300", "D300 — decont TVA", ObligationFrequency.MONTHLY, 1, 25),
    ObligationSeed(
        "D300_TRIM", "D300 — decont TVA (trimestrial)", ObligationFrequency.QUARTERLY, 1, 25
    ),
    ObligationSeed("D394", "D394 — declarație informativă", ObligationFrequency.MONTHLY, 1, 30),
    ObligationSeed("D112", "D112 — salarii și contribuții", ObligationFrequency.MONTHLY, 1, 25),
    ObligationSeed("D390", "D390 — declarație recapitulativă", ObligationFrequency.MONTHLY, 1, 25),
    ObligationSeed("D100", "D100 — obligații de plată", ObligationFrequency.QUARTERLY, 1, 25),
    ObligationSeed("SAFT", "D406 — SAF-T", ObligationFrequency.MONTHLY, 1, 30),
    ObligationSeed("BILANT", "Situații financiare anuale", ObligationFrequency.ANNUAL, 5, 30),
)


def _day_in(year: int, month: int, day: int) -> date:
    """Ziua cerută, dar niciodată una care nu există.

    Un termen pe 30 nu are ce căuta în februarie. Retezat la ultima zi a lunii,
    nu sărit: un termen care **dispare** exact în luna în care cade este mai rău
    decât unul mutat cu două zile, fiindcă nu se vede că lipsește.
    """
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _shift(year: int, month: int, months: int) -> tuple[int, int]:
    index = (year * 12 + month - 1) + months
    return index // 12, index % 12 + 1


def closes_a_period(frequency: ObligationFrequency, month: int) -> bool:
    """Luna aceasta încheie o perioadă a obligației?"""
    return month in _CLOSING_MONTHS[frequency]


def deadline_for(
    frequency: ObligationFrequency,
    period: str,
    *,
    months_after: int,
    deadline_day: int,
) -> date:
    """Termenul perioadei care se încheie în luna `period` (`YYYY-MM`)."""
    year, month = int(period[:4]), int(period[5:7])
    shifted_year, shifted_month = _shift(year, month, months_after)
    return _day_in(shifted_year, shifted_month, deadline_day)


@dataclass(frozen=True, slots=True)
class Due:
    """O perioadă și termenul ei."""

    #: Luna în care se **încheie** perioada, `YYYY-MM`. Pentru trimestrul III
    #: 2026 este `2026-09`, nu `2026-07`: perioada se numește după ce acoperă,
    #: iar cine se uită la un termen vrea să știe ce închide, nu când a început.
    period: str
    deadline: date


def due_between(
    frequency: ObligationFrequency,
    *,
    months_after: int,
    deadline_day: int,
    since: date,
    until: date,
) -> list[Due]:
    """Perioadele al căror termen cade în fereastră, în ordine cronologică.

    Se plimbă pe luni, nu pe zile, și pornește din urmă cu `months_after`: un
    termen care cade azi aparține unei perioade încheiate acum câteva luni, iar
    o fereastră calculată doar înainte l-ar fi pierdut tocmai pe cel întârziat.
    """
    if since > until:
        return []

    first_year, first_month = _shift(since.year, since.month, -months_after - 1)
    last_year, last_month = _shift(until.year, until.month, -months_after + 1)

    found: list[Due] = []
    year, month = first_year, first_month
    while (year, month) <= (last_year, last_month):
        if closes_a_period(frequency, month):
            period = f"{year:04d}-{month:02d}"
            deadline = deadline_for(
                frequency, period, months_after=months_after, deadline_day=deadline_day
            )
            if since <= deadline <= until:
                found.append(Due(period=period, deadline=deadline))
        year, month = _shift(year, month, 1)

    found.sort(key=lambda due: due.deadline)
    return found


__all__ = [
    "DEFAULT_OBLIGATIONS",
    "Due",
    "ObligationSeed",
    "closes_a_period",
    "deadline_for",
    "due_between",
]
