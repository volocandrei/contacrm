"""Perioada contabilă a unui document și starea unei luni (§18, §19, ADR-008).

Două lucruri, amândouă pure — fără bază de date, fără efecte:

1. **În ce lună intră un document.** Vezi ADR-008: implicit luna documentului, cu
   alternativa „luna primirii" ca setare. Fără dată nu se derivă nimic; o lună
   greșită este mai rea decât una absentă, pentru că absența se vede.

2. **Cât de departe este o lună de a fi completă.** Regulile sunt portul exact al
   contractului din `frontend/src/api/mock/seed.ts` (`periodProgress`,
   `derivePeriodStatus`), iar `tests/test_periods_domain.py` le compară cu sursa
   TypeScript, ca cele două să nu se poată despărți în tăcere.

Ce contează în a doua parte: o lună este **completă** doar când fiecare document
așteptat a sosit — nu când s-a atins un total. Un total se poate atinge cu documente
de alt tip, iar „documente complete" este semnalul după care se închide luna. Dacă
minte, se închide o lună cu documente obligatorii lipsă.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.domain.enums import PeriodStatus

REFERENCE_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Peste acest procent din documentele așteptate, luna se citește ca „în lucru" și nu
# ca „abia începută". Este **doar ergonomie de interfață**: nu decide nimic contabil,
# iar pragul de completitudine rămâne „toate", nu un procent.
PARTIAL_THRESHOLD = 0.6


class ReferencePeriodStrategy(StrEnum):
    """Din ce se derivă luna contabilă (ADR-008)."""

    # Luna scrisă pe document. Implicit, și cazul covârșitor.
    DOCUMENT_DATE = "document_date"
    # Luna în care documentul a ajuns la cabinet. Unele cabinete lucrează așa.
    RECEIVED_AT = "received_at"


def format_reference_month(moment: date | datetime) -> str:
    return f"{moment.year:04d}-{moment.month:02d}"


def is_valid_reference_month(value: str | None) -> bool:
    return bool(value) and bool(REFERENCE_MONTH_PATTERN.match(value or ""))


def derive_reference_month(
    *,
    document_date: date | None,
    received_at: datetime | None,
    strategy: ReferencePeriodStrategy = ReferencePeriodStrategy.DOCUMENT_DATE,
) -> str | None:
    """Luna contabilă propusă, sau `None` dacă nu se poate ști.

    `None` nu este un eșec: este răspunsul corect când documentul nu are dată. Cine
    primește `None` trimite documentul la verificare cu motivul scris — nu inventează
    o lună.

    TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: dacă strategia trebuie să
    difere pe tip de document (un extras de cont față de o factură de intrare) sau pe
    client, nu pe cabinet. Vezi ADR-008.
    """
    if strategy is ReferencePeriodStrategy.RECEIVED_AT:
        return format_reference_month(received_at) if received_at else None
    return format_reference_month(document_date) if document_date else None


def split_reference_month(reference_month: str) -> tuple[int, int]:
    """`"2026-08"` → `(2026, 8)`. Presupune o valoare deja validată."""
    year, month = reference_month.split("-")
    return int(year), int(month)


# ── Checklistul lunii ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChecklistEntry:
    """Un tip de document așteptat într-o lună, și câte au sosit."""

    document_type: str
    document_type_label: str
    expected_min_count: int
    received_count: int

    @property
    def is_satisfied(self) -> bool:
        return self.received_count >= self.expected_min_count


@dataclass(frozen=True, slots=True)
class Progress:
    satisfied: int
    expected: int


def period_progress(checklist: list[ChecklistEntry]) -> Progress:
    """Câte dintre documentele **așteptate** au sosit.

    `min(primite, minim cerut)` per tip, nu totalul primit: o factură în plus nu
    compensează un extras de cont lipsă.
    """
    satisfied = sum(min(item.received_count, item.expected_min_count) for item in checklist)
    expected = sum(item.expected_min_count for item in checklist)
    return Progress(satisfied=satisfied, expected=expected)


def derive_period_status(
    checklist: list[ChecklistEntry], received_count: int, *, is_closed: bool
) -> PeriodStatus:
    """Starea lunii, calculată din ce s-a primit — nu ținută într-o coloană.

    Un status stocat se desincronizează de contoarele lui în tăcere; exact asta s-a
    întâmplat în backendul simulat, unde perioade marcate „complete" aveau documente
    obligatorii lipsă. Singurul fapt care se **păstrează** este închiderea: aceea
    este o decizie umană, nu un calcul.
    """
    if is_closed:
        return PeriodStatus.FINALIZED
    if received_count == 0:
        return PeriodStatus.NOT_STARTED
    if not checklist:
        return PeriodStatus.COLLECTING
    if all(item.is_satisfied for item in checklist):
        return PeriodStatus.COMPLETE

    progress = period_progress(checklist)
    if progress.expected > 0 and progress.satisfied / progress.expected >= PARTIAL_THRESHOLD:
        return PeriodStatus.PARTIAL
    return PeriodStatus.COLLECTING


def missing_entries(checklist: list[ChecklistEntry]) -> list[ChecklistEntry]:
    """Ce se așteaptă și încă nu a sosit (§19)."""
    return [item for item in checklist if not item.is_satisfied]


__all__ = [
    "PARTIAL_THRESHOLD",
    "ChecklistEntry",
    "Progress",
    "ReferencePeriodStrategy",
    "derive_period_status",
    "derive_reference_month",
    "format_reference_month",
    "is_valid_reference_month",
    "missing_entries",
    "period_progress",
    "split_reference_month",
]


def filing_deadline(reference_month: str, *, day: int) -> date:
    """Termenul de depunere pentru o lună încheiată.

    Este în luna **următoare**: documentele lui august se depun până pe 25
    septembrie. Ziua este mărginită la 28 în configurare, deci există în orice
    lună — inclusiv februarie, unde altfel termenul ar fi dispărut exact când
    contează.
    """
    year, month = split_reference_month(reference_month)
    return date(year + 1, 1, day) if month == 12 else date(year, month + 1, day)
