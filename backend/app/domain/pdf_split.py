"""Unde se termină un document și începe altul, într-un teanc scanat (§8).

**Problema, așa cum arată ea într-un cabinet.** Clientul pune zece facturi în
scanner și trimite `scan_001.pdf`. Astăzi asta devine **un** document: un singur
număr, un singur furnizor, un singur total — toate ale primei facturi, restul
pierdute. Contabilul le desface de mână, în alt program, și le urcă una câte una.

**Ce face fișierul acesta.** Primește textul fiecărei pagini și spune unde crede
că sunt granițele, cu **motivul** fiecărei tăieturi. Nu taie nimic: tăierea o face
serviciul, iar aplicarea o cere un om.

**De ce nu ghicește mai mult decât poate.** O factură tăiată greșit în două
produce două jumătăți care arată ca documente adevărate: fiecare cu numărul ei
citit greșit, fiecare cu un total parțial. Un teanc netăiat este o supărare
cunoscută; un teanc tăiat greșit este o eroare contabilă care intră în decont.
De aceea, la îndoială, **nu se taie**.

**Semnalele, în ordinea în care contează.**

1. **Un antet de document nou, sus pe pagină.** „FACTURĂ", „CHITANȚĂ", „AVIZ DE
   ÎNSOȚIRE", „BON FISCAL". Sus, nu oriunde: cuvântul „factură" apare în corpul
   oricărei facturi de zece ori („conform facturii", „factura se achită").
2. **Alt număr de document decât al paginii dinainte.** Cel mai tare semnal care
   există, și singurul care poate tăia și fără antet.
3. **Marcajul de paginare.** „pagina 1 din 3" începe un document; „pagina 2 din 3"
   **interzice** o tăietură, oricâte alte semnale ar fi.

Regula finală: o pagină începe un document nou dacă are antet **și** un număr
diferit, sau dacă are doar unul dintre ele și pagina dinainte s-a terminat curat
(nu era la mijlocul unei numerotări).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

#: Câte **rânduri** de sus se consideră antet.
#:
#: Rânduri, nu un procent din text — iar diferența a fost găsită de un test de
#: integrare, nu prin citit. Cu „prima treime din caractere", o pagină cu puțin
#: text (o chitanță, o factură cu două poziții) se taie la mijlocul unui rând, iar
#: `nr. 7001` se citea `nr. 700`: un număr de factură greșit, care apoi nu se mai
#: potrivea cu nimic. Un antet ocupă un număr de rânduri, nu o fracțiune de pagină.
HEADER_LINES: Final = 12

#: Cuvintele care încep un document contabil, în forma normalizată (fără
#: diacritice). Sunt tipurile pe care le primește un cabinet, nu o listă completă.
DOCUMENT_HEADERS: Final[dict[str, str]] = {
    "factura": "factură",
    "factura fiscala": "factură",
    "chitanta": "chitanță",
    "bon fiscal": "bon fiscal",
    "aviz de insotire": "aviz de însoțire",
    "aviz de expeditie": "aviz de însoțire",
    "extras de cont": "extras de cont",
    "nota de receptie": "notă de recepție",
    "dispozitie de plata": "dispoziție de plată",
    "dispozitie de incasare": "dispoziție de încasare",
    "proces verbal": "proces-verbal",
    "contract": "contract",
    "deviz": "deviz",
}

#: „pagina 2 din 5", „pag 2/5", „2 / 5". Al doilea număr este totalul.
_PAGINATION = re.compile(r"\b(?:pag(?:ina)?\.?\s*)?(\d{1,3})\s*(?:din|/|din\s+)\s*(\d{1,3})\b")

#: Numărul documentului, în formele în care apare pe facturile românești.
#: „nr. 7001", „numarul 7001", „seria FCT nr 7001", „factura nr FCT-7001".
_NUMBER = re.compile(
    r"\bnr\.?\s*[:.]?\s*([a-z]{0,8}[-/ ]?\d{1,12})\b"
    r"|\bnumarul?\s*[:.]?\s*([a-z]{0,8}[-/ ]?\d{1,12})\b"
)


def normalise(text: str) -> str:
    """Textul paginii, redus la forma pe care o comparăm."""
    folded = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[ \t]+", " ", plain)


@dataclass(frozen=True, slots=True)
class PageSignals:
    """Ce s-a găsit pe o pagină. Numai fapte, nicio hotărâre."""

    number: int
    #: Tipul de document găsit **sus** pe pagină, dacă există.
    header: str | None
    #: Numărul documentului, dacă se poate citi.
    document_number: str | None
    #: `(pagina, din_total)` când documentul își numerotează paginile.
    pagination: tuple[int, int] | None
    #: Pagina are text? Una scanată fără strat de text nu spune nimic — și
    #: absența ei este ea însăși o informație.
    has_text: bool

    @property
    def continues(self) -> bool:
        """Pagina spune despre ea însăși că **nu** este prima a unui document."""
        return self.pagination is not None and self.pagination[0] > 1

    @property
    def starts_own_numbering(self) -> bool:
        return self.pagination is not None and self.pagination[0] == 1


@dataclass(frozen=True, slots=True)
class Segment:
    """Un document detectat în teanc: de la ce pagină până la ce pagină."""

    #: Prima pagină, de la 1.
    page_from: int
    #: Ultima pagină, inclusiv.
    page_to: int
    document_type: str | None
    document_number: str | None
    #: De ce s-a tăiat aici. Gol pentru primul segment: el nu este o tăietură.
    reasons: tuple[str, ...] = ()

    @property
    def pages(self) -> int:
        return self.page_to - self.page_from + 1


def read_page(number: int, text: str) -> PageSignals:
    """Semnalele unei pagini, din textul ei."""
    plain = normalise(text)
    stripped = plain.strip()
    if not stripped:
        return PageSignals(
            number=number, header=None, document_number=None, pagination=None, has_text=False
        )

    top = chr(10).join(plain.splitlines()[:HEADER_LINES])

    header = None
    position = len(top) + 1
    for keyword, label in DOCUMENT_HEADERS.items():
        found = top.find(keyword)
        # Cel mai de sus antet câștigă: pe o factură scrie și „factura" și, mai
        # jos, „aviz de insotire nr...", iar documentul este o factură.
        if found != -1 and found < position:
            header, position = label, found

    pagination: tuple[int, int] | None = None
    match = _PAGINATION.search(plain)
    if match:
        current, total = int(match.group(1)), int(match.group(2))
        # „5 din 3" nu este o paginare, este o coincidență de numere.
        if 1 <= current <= total <= 200:
            pagination = (current, total)

    number_match = _NUMBER.search(top)
    document_number = None
    if number_match:
        raw = number_match.group(1) or number_match.group(2) or ""
        document_number = re.sub(r"[\s\-/]", "", raw).upper() or None

    return PageSignals(
        number=number,
        header=header,
        document_number=document_number,
        pagination=pagination,
        has_text=True,
    )


def _starts_new(previous: PageSignals, page: PageSignals) -> tuple[bool, list[str]]:
    """Începe pagina asta un document nou? Cu motivele, în cuvinte.

    Ordinea verificărilor este ordinea în care semnalele contează, iar prima care
    hotărăște oprește restul: o pagină care spune „pagina 2 din 3" nu are cum să
    înceapă un document, oricâte antete ar avea în ea.
    """
    if page.continues:
        # Documentul își numără singur paginile și spune că nu este la început.
        # Este singurul semnal care **interzice**, iar el bate tot.
        return False, []

    reasons: list[str] = []

    changed_number = (
        page.document_number is not None
        and previous.document_number is not None
        and page.document_number != previous.document_number
    )
    if changed_number:
        reasons.append(f"alt număr de document ({page.document_number})")

    if page.header is not None:
        reasons.append(f"antet nou sus pe pagină ({page.header})")

    if page.starts_own_numbering:
        reasons.append("pagina se declară prima dintr-un document")

    # **Un singur semnal slab nu taie.** Un antet fără număr nou poate fi al doilea
    # exemplar al aceleiași facturi; un număr nou fără antet poate fi un număr de
    # comandă citit greșit. Se cere fie paginarea, care este explicită, fie două
    # semnale care se sprijină reciproc.
    if page.starts_own_numbering:
        return True, reasons
    if changed_number and page.header is not None:
        return True, reasons
    return False, []


def detect(pages: list[str]) -> list[Segment]:
    """Documentele dintr-un teanc, cu motivul fiecărei tăieturi.

    Întoarce **întotdeauna cel puțin un segment**: un fișier de o pagină este un
    document de o pagină, iar unul pe care nu-l putem citi rămâne întreg. Lista cu
    un singur element înseamnă „nu am găsit nimic de tăiat", nu „nu am putut citi".
    """
    if not pages:
        return []

    signals = [read_page(index, text) for index, text in enumerate(pages, start=1)]

    starts: list[tuple[int, list[str], PageSignals]] = [(1, [], signals[0])]
    for previous, page in pairwise(signals):
        new, reasons = _starts_new(previous, page)
        if new:
            starts.append((page.number, reasons, page))

    segments: list[Segment] = []
    for index, (first, reasons, signal) in enumerate(starts):
        last = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(pages)
        # Tipul și numărul se iau de pe **prima pagină** a segmentului: acolo stă
        # antetul. Dacă lipsesc, se caută pe paginile lui, în ordine — o factură
        # își repetă numărul pe fiecare pagină.
        document_type = signal.header
        document_number = signal.document_number
        for page in signals[first - 1 : last]:
            document_type = document_type or page.header
            document_number = document_number or page.document_number

        segments.append(
            Segment(
                page_from=first,
                page_to=last,
                document_type=document_type,
                document_number=document_number,
                reasons=tuple(reasons),
            )
        )
    return segments


__all__ = [
    "DOCUMENT_HEADERS",
    "HEADER_LINES",
    "PageSignals",
    "Segment",
    "detect",
    "normalise",
    "read_page",
]
