"""Cum trebuie să arate un CSV ca să se deschidă corect în Excel pe românește.

Fiecare regulă de aici a fost plătită o dată. Le ține la un loc pentru că un al
doilea export scris de la zero le-ar fi respectat pe unele și nu pe toate — iar
un fișier care se deschide „aproape bine" se repară de mână, de fiecare dată.

- **separatorul este `;`**, nu virgulă: cu virgulă, Excel în setările românești
  pune tot rândul într-o singură coloană;
- **BOM la început**: fără el, Excel citește UTF-8 ca ANSI și „Rată" devine
  „RatÄƒ";
- **sfârșit de linie CRLF**, pentru că Windows este destinația;
- **virgulă la zecimale**: `1234.56` scris cu punct nu este un număr pentru Excel
  în setările românești. Îl ia ca text, îl aliniază la stânga și nu îl adună.
  Este cea mai perfidă dintre cele patru, fiindcă fișierul pare bun până când
  cineva trage un total pe coloană și primește zero;
- **fără separator de mii**: `1.234,56` ar fi frumos de citit și ar reintroduce
  exact ambiguitatea pe care o rezolvă virgula.

Valorile trec prin `csv.writer`, care scapă singur ghilimelele și separatorii din
interiorul lor: un client care are `;` în denumire nu are voie să rupă coloanele.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import Final

#: Separatorul așteptat de Excel în setările românești.
DELIMITER: Final = ";"

#: Fără el, Excel citește fișierul ca ANSI și diacriticele se strică.
BOM: Final = "﻿"

#: Windows este destinația.
LINE_ENDING: Final = "\r\n"


def render(rows: list[list[str]]) -> str:
    """Rândurile, ca fișier gata de trimis ca răspuns."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator=LINE_ENDING)
    writer.writerows(rows)
    return BOM + buffer.getvalue()


def number(value: Decimal | float | None, *, decimals: int = 2) -> str:
    """Un număr pe care Excel românesc îl recunoaște ca număr.

    Gol pentru `None`, nu zero: într-un registru contabil, „nu s-a citit suma"
    și „suma este zero" sunt două lucruri diferite, iar al doilea se aprobă.
    """
    if value is None:
        return ""
    return f"{value:.{decimals}f}".replace(".", ",")


def day(value: dt.date | None) -> str:
    """Data în forma pe care o citește un contabil, `31.08.2026`.

    ISO ar fi fost mai comod de sortat, dar fișierul este pentru om și pentru
    Excel, nu pentru un parser: în setările românești `31.08.2026` intră ca dată,
    iar `2026-08-31` intră ca text.
    """
    return "" if value is None else value.strftime("%d.%m.%Y")


__all__ = ["BOM", "DELIMITER", "LINE_ENDING", "day", "number", "render"]
