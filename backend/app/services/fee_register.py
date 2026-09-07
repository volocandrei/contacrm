"""Onorariile lunii, ca fișier.

**Golul pe care îl umple.** Ecranul spune cine cât are de plătit și cine a
plătit, dar cifrele rămâneau pe el. Cine emite facturile lucrează în alt program,
iar cine ține evidența le vrea în Excel — și amândoi le retastau, client cu
client, uitându-se la ecran. Aceeași motivație ca la registrul de documente: un
număr care nu poate ieși din aplicație se copiază de mână, iar la a treia copiere
apare prima greșeală.

**Ce conține.** Rândurile lunii, exact cele de pe ecran, în aceeași ordine —
inclusiv clienții fără onorariu stabilit și cei nefacturați încă. Un fișier care
i-ar tăcea ar arăta identic într-un cabinet pus la punct și în unul care a uitat
jumătate din listă.

**Nu calculează nimic.** Nici totaluri, nici conversii între monede. Totalul îl
trage cine deschide fișierul, cu formula lui, pe coloana pe care o vrea — iar un
total pus de noi peste două monede ar fi un număr fără sens.

Forma fișierului — separator, BOM, virgulă la zecimale — stă în `excel_csv.py`.
"""

from __future__ import annotations

import uuid
from typing import Final

from app.services.excel_csv import day, number, render
from app.services.fees import FeeRow

HEADER: Final = (
    "Client",
    "Luna",
    "Onorariu",
    "Monedă",
    "Facturat",
    "Încasat la",
    "Încasat de",
    "Documente",
    "Observații",
)


def rows_for(entries: list[FeeRow], documents: dict[uuid.UUID, int]) -> list[list[str]]:
    """Antetul plus câte un rând pe client."""
    rows: list[list[str]] = [list(HEADER)]
    for entry in entries:
        rows.append(
            [
                entry.client_name,
                entry.period,
                number(entry.configured),
                entry.currency,
                number(entry.amount),
                day(entry.paid_on),
                entry.paid_by_name or "",
                str(documents.get(entry.client_id, 0)),
                entry.note or "",
            ]
        )
    return rows


def to_csv(entries: list[FeeRow], documents: dict[uuid.UUID, int]) -> str:
    """Fișierul întreg, gata de trimis ca răspuns."""
    return render(rows_for(entries, documents))


def filename(reference_month: str) -> str:
    """Numele sub care ajunge fișierul pe disc.

    Poartă luna, ca două exporturi succesive să nu se suprascrie în „Descărcări"
    și ca peste un an să se știe ce conține.
    """
    return f"onorarii-{reference_month}.csv"


__all__ = ["HEADER", "filename", "rows_for", "to_csv"]
