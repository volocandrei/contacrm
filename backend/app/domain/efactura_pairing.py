"""Aceeași factură, în două exemplare: XML-ul și PDF-ul (§16, §17).

**Ce se întâmplă azi într-un cabinet.** Aceeași factură ajunge de două ori și pe
două drumuri: XML-ul din SPV, descărcat automat de la ANAF, și PDF-ul trimis de
furnizor pe email sau adus de client. Sunt **același document**, nu două.

Fără o legătură între ele, cabinetul are două rânduri în registru pentru o
singură factură: unul cu date exacte și fără facsimil, altul cu facsimil și date
citite. Contabilul le potrivește cu ochiul, la fiecare factură, în fiecare lună.

**De ce nu sunt duplicate.** Detecția de duplicate spune „aruncă unul". Aici
amândouă rămân, fiindcă fiecare are ceva ce celălalt nu are: XML-ul este
originalul fiscal, cu valori exacte; PDF-ul este ce se poate privi și ce se
tipărește. Legătura nu elimină, **unește**.

**Cheia este identitatea legală a facturii**: codul fiscal al furnizorului, seria
și numărul. Tripletul identifică o factură în mod unic — de aceea el, și nu suma:
dacă furnizorul, seria și numărul coincid, o sumă diferită înseamnă că una dintre
cele două a fost citită greșit, iar **asta** trebuie arătat cuiva, nu ascuns.

**Stările, și de ce fiecare există.**

- `MATCHED` — identitate exactă, un singur candidat. Se leagă singur: nu este o
  ghicire, este aceeași factură după cheia care o definește legal.
- `PROBABLE` — se potrivesc numărul și suma, dar CUI-ul lipsește de pe una dintre
  ele. Se propune, nu se leagă.
- `MULTIPLE_CANDIDATES` — două sau mai multe PDF-uri arată la fel de bine. A alege
  unul ar fi o monedă aruncată; ecranul le arată pe amândouă.
- `CONFLICT` — identitate identică, dar **sume diferite**. Este cazul care merită
  cel mai mult atenția și cel mai ușor de ascuns: una dintre valori este greșită.
- `MISSING` — nu există pereche. Nu este o eroare: majoritatea documentelor nu au.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

#: Cât de mult pot să difere sumele fără ca diferența să însemne ceva. Zero: o
#: factură este aceeași sumă în amândouă exemplarele, la bănuț. Un „aproape" aici
#: ar fi ascuns exact greșeala de citire pe care starea `CONFLICT` o scoate la
#: iveală.
AMOUNT_TOLERANCE: Final = Decimal("0.00")

#: Cât de departe pot fi datele de emitere. Zile, nu zero: XML-ul poartă data
#: emiterii, iar PDF-ul poate fi generat cu o zi diferită de un ERP care rotunjește
#: fusul orar. Peste atât, nu mai este aceeași factură.
MAX_DAYS_APART: Final = 3


class PairingState(StrEnum):
    """Ce s-a găsit pentru documentul acesta."""

    MATCHED = "MATCHED"
    PROBABLE = "PROBABLE"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    CONFLICT = "CONFLICT"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class Identity:
    """Ce identifică o factură, indiferent în ce exemplar."""

    document_id: str
    #: `True` pentru factura electronică (XML), `False` pentru exemplarul clasic.
    is_electronic: bool
    supplier_tax_id: str | None
    series: str | None
    number: str | None
    total: Decimal | None
    document_date: date | None


@dataclass(frozen=True, slots=True)
class Pairing:
    """Perechea propusă sau găsită, cu motivele ei."""

    document_id: str
    state: PairingState
    reasons: tuple[str, ...]

    @property
    def is_certain(self) -> bool:
        """Se poate lega fără să întrebe pe nimeni?"""
        return self.state is PairingState.MATCHED


@dataclass(frozen=True, slots=True)
class Result:
    """Ce s-a găsit pentru un document: starea, și candidații cu motivele lor."""

    state: PairingState
    candidates: tuple[Pairing, ...]

    @property
    def certain(self) -> Pairing | None:
        """Singurul candidat sigur, dacă există exact unul."""
        sure = [item for item in self.candidates if item.is_certain]
        return sure[0] if len(sure) == 1 else None


def _same(left: str | None, right: str | None) -> bool:
    """Două valori text, comparate ca identitate: fără spații, fără majuscule."""
    if left is None or right is None:
        return False
    return "".join(left.split()).upper() == "".join(right.split()).upper()


def _days_apart(left: date | None, right: date | None) -> int | None:
    if left is None or right is None:
        return None
    return abs((left - right).days)


def compare(subject: Identity, candidate: Identity) -> Pairing | None:
    """Cum stau cele două una față de alta. `None` = nu au nicio legătură.

    Se compară doar exemplare de **feluri diferite**: un XML cu un PDF. Două
    XML-uri cu aceeași identitate nu sunt o pereche, sunt un duplicat — și au
    modulul lor.
    """
    if subject.is_electronic == candidate.is_electronic:
        return None

    if not _same(subject.number, candidate.number):
        # Fără număr comun nu există nimic: numărul este ce scrie pe factură și ce
        # caută omul. O potrivire fără el ar fi o coincidență de sume.
        return None

    reasons: list[str] = ["același număr de factură"]

    same_series = _same(subject.series, candidate.series) or (
        subject.series is None and candidate.series is None
    )
    if subject.series is not None and candidate.series is not None:
        if not same_series:
            # Serii diferite înseamnă facturi diferite care se întâmplă să aibă
            # același număr. Se întâmplă des: fiecare furnizor își are seria lui.
            return None
        reasons.append("aceeași serie")

    days = _days_apart(subject.document_date, candidate.document_date)
    if days is not None and days > MAX_DAYS_APART:
        return None

    tax_ids_known = subject.supplier_tax_id is not None and candidate.supplier_tax_id is not None
    tax_ids_match = _same(subject.supplier_tax_id, candidate.supplier_tax_id)
    if tax_ids_known:
        if not tax_ids_match:
            return None
        reasons.append("CUI furnizor identic")

    amounts_known = subject.total is not None and candidate.total is not None
    if amounts_known:
        difference = abs((subject.total or Decimal(0)) - (candidate.total or Decimal(0)))
        if difference > AMOUNT_TOLERANCE:
            # Identitate identică, sume diferite: una dintre ele este citită
            # greșit. Se **arată**, nu se ascunde sub o potrivire reușită.
            return Pairing(
                document_id=candidate.document_id,
                state=PairingState.CONFLICT,
                reasons=(*reasons, f"sume diferite: {subject.total} față de {candidate.total}"),
            )
        reasons.append("aceeași sumă")

    if days is not None:
        reasons.append("aceeași dată" if days == 0 else f"date la {days} zile")

    # **Sigur** înseamnă identitatea legală completă: CUI, serie (unde există),
    # număr — plus suma, când amândouă o au. Orice lipsă coboară la „probabil",
    # iar acolo decide un om.
    certain = tax_ids_match and amounts_known
    return Pairing(
        document_id=candidate.document_id,
        state=PairingState.MATCHED if certain else PairingState.PROBABLE,
        reasons=tuple(reasons),
    )


def evaluate(subject: Identity, candidates: list[Identity]) -> Result:
    """Perechea documentului, printre candidații dați."""
    found = [pairing for candidate in candidates if (pairing := compare(subject, candidate))]

    if not found:
        return Result(state=PairingState.MISSING, candidates=())

    conflicts = [item for item in found if item.state is PairingState.CONFLICT]
    if conflicts:
        # Conflictul câștigă asupra oricărei potriviri reușite: dacă există un
        # exemplar cu aceeași identitate și altă sumă, aceea este informația.
        return Result(state=PairingState.CONFLICT, candidates=tuple(found))

    certain = [item for item in found if item.is_certain]
    if len(certain) == 1:
        return Result(state=PairingState.MATCHED, candidates=tuple(found))
    if len(certain) > 1:
        return Result(state=PairingState.MULTIPLE_CANDIDATES, candidates=tuple(found))

    if len(found) > 1:
        return Result(state=PairingState.MULTIPLE_CANDIDATES, candidates=tuple(found))
    return Result(state=PairingState.PROBABLE, candidates=tuple(found))


__all__ = [
    "AMOUNT_TOLERANCE",
    "MAX_DAYS_APART",
    "Identity",
    "Pairing",
    "PairingState",
    "Result",
    "compare",
    "evaluate",
]
