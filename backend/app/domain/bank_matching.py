"""Ce factură a plătit banii aceștia (§13, §14, §17, §D).

**Munca pe care o înlocuiește.** Reconcilierea este una dintre cele mai lungi ore
ale lunii într-un cabinet: contabilul are extrasul într-o parte, facturile în alta,
și le potrivește cu ochiul. Trei sute de rânduri pe lună, per client.

**Ce face fișierul acesta, și ce nu face.** Propune. Nu leagă nimic. Diferența nu
este de prudență, este de contabilitate: o plată legată de factura greșită mută
bani între conturi analitice, iar greșeala se descoperă la închiderea anului, când
nimeni nu-și mai amintește ce a fost în martie. Sistemul spune „cred că astea două
se leagă, iată de ce"; omul apasă.

**De ce fiecare potrivire vine cu motive.** Cine se uită peste o lună la o
propunere trebuie să afle **de ce** a fost făcută: „CUI identic, numărul facturii
în referință, sumă exactă". Fără explicație, contabilul fie verifică tot de la
zero — și atunci automatizarea n-a economisit nimic — fie acceptă fără să
verifice, ceea ce este mai rău decât munca de mână.

**Semnalele, în ordinea în care contează.**

1. **Numărul facturii în referință.** Cel mai tare semnal care există. Cine
   plătește scrie „FCT 7001" în ordinul de plată tocmai ca să se știe ce plătește.
2. **Suma exactă.** Egalitate la bănuț, nu „aproximativ".
3. **CUI-ul contrapartidei.** Neambiguu, dar rar în descrierea unui extras
   românesc — de aceea nu este primul.
4. **Numele contrapartidei.** Se compară pe formă normalizată: fără diacritice,
   fără „SRL", fără punctuație.
5. **Apropierea de dată.** Cel mai slab dintre toate, și niciodată singur: într-o
   lună cu cincizeci de facturi, „aceeași săptămână" nu spune nimic.

**Regula care ține totul.** Un singur semnal slab nu produce niciodată o
propunere. Data apropiată plus suma rotundă este exact tiparul care leagă factura
greșită — două abonamente lunare de aceeași valoare arată identic.

Fișierul este **pur**: fără bază de date, fără sesiune, fără efecte. Primește o
tranzacție și niște facturi candidat, întoarce potriviri cu scor și motive. Se
poate testa cu date scrise de mână, iar regulile se pot citi fără să deschizi un
ORM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

#: Peste cât se propune ceva. Sub prag, tăcerea este răspunsul corect: o listă de
#: propuneri proaste se închide o dată și nu se mai deschide niciodată.
SUGGEST_THRESHOLD: Final = 0.60

#: Peste cât propunerea este „aproape sigură" și se poate confirma din două
#: apăsări în loc de o verificare. Tot nu se leagă singură.
STRONG_THRESHOLD: Final = 0.90

#: Cât de departe poate fi plata de data facturii ca să mai însemne ceva. O lună
#: și jumătate acoperă termenele obișnuite de plată din România.
MAX_DAYS_APART: Final = 45

#: Formele juridice care nu spun nimic despre identitatea firmei. „Alfa SRL" și
#: „ALFA S.R.L." sunt aceeași firmă.
_LEGAL_FORMS: Final = frozenset(
    {"srl", "sa", "srls", "sca", "snc", "pfa", "ii", "if", "ong", "asociatia", "sc"}
)

_WORD = re.compile(r"[a-z0-9]+")

#: Abrevierile scrise cu puncte: `s.r.l.`, `s.a.`. Se lipesc înainte de tăiere în
#: cuvinte, altfel devin trei litere singure pe care lista formelor juridice nu le
#: recunoaște — iar `S.R.L.` este chiar forma pe care o scriu cei mai mulți.
_DOTTED = re.compile(r"\b(?:[a-z]\.){2,}")

#: Un număr de document în text: litere opționale, apoi cifre. Se caută pe
#: cuvinte întregi, altfel „7001" s-ar potrivi în „270015".
_NUMBER_TOKEN = re.compile(r"\b([a-z]{0,6}[-/ ]?\d{1,12})\b")


def normalise(value: str | None) -> str:
    """Forma pe care se compară numele: fără diacritice, fără formă juridică.

    „Șerbănescu Distribuție S.R.L." și „SERBANESCU DISTRIBUTIE SRL" trebuie să se
    recunoască una pe alta — este același furnizor, scris de doi oameni diferiți.
    """
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value.lower())
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    joined = _DOTTED.sub(lambda match: match.group(0).replace(".", ""), stripped)
    words = [word for word in _WORD.findall(joined) if word not in _LEGAL_FORMS]
    return " ".join(words)


def normalise_tax_id(value: str | None) -> str:
    """CUI-ul, ca cifre. `RO 12345678`, `ro12345678` și `12345678` sunt același cod."""
    if not value:
        return ""
    return re.sub(r"\D", "", value)


@dataclass(frozen=True, slots=True)
class Candidate:
    """O factură care ar putea fi plata asta. Numai ce se compară, nimic altceva."""

    document_id: str
    #: Totalul documentului. `None` înseamnă că nu s-a citit — iar atunci suma nu
    #: poate fi un semnal, nici pozitiv, nici negativ.
    total: Decimal | None
    document_date: date | None
    series: str | None
    number: str | None
    partner_name: str | None
    partner_tax_id: str | None
    #: `True` pentru facturile de la furnizori (bani ieșiți), `False` pentru cele
    #: emise (bani intrați). Direcția greșită descalifică din start.
    is_incoming: bool
    #: Cât s-a acoperit deja din ea. O factură plătită integral nu mai este candidat.
    already_matched: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class Movement:
    """Rândul din extras, redus la ce se compară."""

    amount: Decimal
    booking_date: date
    description: str | None
    counterparty_name: str | None
    counterparty_iban: str | None
    reference: str | None

    @property
    def is_payment(self) -> bool:
        """Bani ieșiți: se caută printre facturile de la furnizori."""
        return self.amount < 0

    @property
    def absolute(self) -> Decimal:
        return abs(self.amount)

    @property
    def haystack(self) -> str:
        """Tot textul în care poate sta numărul facturii, într-o singură formă."""
        return normalise(" ".join(filter(None, (self.reference, self.description))))


@dataclass(frozen=True, slots=True)
class Suggestion:
    """O propunere, cu scorul ei și cu motivele în cuvinte."""

    document_id: str
    score: float
    reasons: tuple[str, ...]

    @property
    def is_strong(self) -> bool:
        return self.score >= STRONG_THRESHOLD


def _number_matches(movement: Movement, candidate: Candidate) -> bool:
    """Numărul facturii apare în referința plății?

    Se caută pe **cuvinte întregi**: `7001` nu are voie să se potrivească în
    `270015`, care poate fi un cod de tranzacție. Se încearcă și forma cu serie
    lipită (`FCT7001`), pentru că băncile scapă spațiile.
    """
    if not candidate.number:
        return False
    haystack = movement.haystack
    if not haystack:
        return False

    number = normalise(candidate.number)
    if not number:
        return False

    tokens = {
        token.replace(" ", "").replace("-", "").replace("/", "")
        for token in _NUMBER_TOKEN.findall(haystack)
    }
    if number in tokens:
        return True
    if candidate.series:
        joined = f"{normalise(candidate.series)}{number}"
        if joined in tokens:
            return True
    return False


def _name_matches(movement: Movement, candidate: Candidate) -> bool:
    """Numele contrapartidei se regăsește, pe forma normalizată.

    Se cere ca **toate** cuvintele numelui de pe factură să apară în textul
    plății, nu doar unul: „Distribuție" singur ar lega douăzeci de furnizori.
    """
    partner = normalise(candidate.partner_name)
    if not partner:
        return False
    text = normalise(
        " ".join(
            filter(None, (movement.counterparty_name, movement.reference, movement.description))
        )
    )
    if not text:
        return False
    return all(word in text for word in partner.split())


def _tax_id_matches(movement: Movement, candidate: Candidate) -> bool:
    code = normalise_tax_id(candidate.partner_tax_id)
    # Sub șase cifre nu este un CUI, este un număr oarecare din descriere.
    if len(code) < 6:
        return False
    haystack = re.sub(
        r"\D", " ", " ".join(filter(None, (movement.reference, movement.description)))
    )
    return code in haystack.split()


def _days_apart(movement: Movement, candidate: Candidate) -> int | None:
    if candidate.document_date is None:
        return None
    return abs((movement.booking_date - candidate.document_date).days)


def score(movement: Movement, candidate: Candidate) -> Suggestion | None:
    """Cât de bine se leagă cele două, și de ce. `None` = nu se propune nimic.

    Ponderile nu sunt calibrate pe date reale — nu există încă date reale. Sunt
    alese ca **ordine**, iar ordinea este cea din capul fișierului. Ziua în care
    un cabinet folosește asta o lună, ele se recalibrează pe ce a acceptat și ce a
    respins omul; până atunci, orice cifră mai precisă ar fi o precizie inventată.
    """
    # Direcția greșită nu se discută: o plată nu poate închide o factură emisă.
    if movement.is_payment != candidate.is_incoming:
        return None

    remaining = (candidate.total or Decimal("0")) - candidate.already_matched
    if candidate.total is not None and remaining <= 0:
        # Deja acoperită integral. Nu mai este candidat.
        return None

    days = _days_apart(movement, candidate)
    if days is not None and days > MAX_DAYS_APART:
        return None

    reasons: list[str] = []
    total = 0.0

    if _number_matches(movement, candidate):
        total += 0.55
        reasons.append("numărul facturii apare în plată")

    exact_amount = candidate.total is not None and movement.absolute == candidate.total
    if exact_amount:
        total += 0.30
        reasons.append("sumă exactă")
    elif candidate.total is not None and movement.absolute == remaining:
        total += 0.25
        reasons.append("acoperă exact restul de plată")

    if _tax_id_matches(movement, candidate):
        total += 0.25
        reasons.append("CUI identic")

    if _name_matches(movement, candidate):
        total += 0.20
        reasons.append("numele partenerului se potrivește")

    if days is not None and days <= 7:
        total += 0.10
        reasons.append(f"la {days} zile de factură" if days else "în aceeași zi")
    elif days is not None and days <= MAX_DAYS_APART:
        total += 0.05
        reasons.append(f"la {days} zile de factură")

    # **Un singur semnal slab nu propune nimic.** Data apropiată plus o sumă
    # rotundă este exact tiparul care leagă factura greșită: două abonamente
    # lunare de aceeași valoare arată identic. Se cere fie numărul facturii, fie
    # cel puțin două semnale independente.
    strong = _number_matches(movement, candidate)
    signals = sum(
        (
            strong,
            exact_amount,
            _tax_id_matches(movement, candidate),
            _name_matches(movement, candidate),
        )
    )
    if not strong and signals < 2:
        return None

    final = min(round(total, 2), 1.0)
    if final < SUGGEST_THRESHOLD:
        return None
    return Suggestion(document_id=candidate.document_id, score=final, reasons=tuple(reasons))


def suggest(movement: Movement, candidates: list[Candidate], *, limit: int = 5) -> list[Suggestion]:
    """Propunerile pentru o tranzacție, cea mai bună întâi.

    `limit` există pentru ecran, nu pentru performanță: o listă de douăzeci de
    candidați nu se citește, deci nu ajută pe nimeni. Cinci încap sub rândul din
    extras fără să-l acopere.
    """
    found = [result for candidate in candidates if (result := score(movement, candidate))]
    found.sort(key=lambda item: (-item.score, item.document_id))
    return found[:limit]


__all__ = [
    "MAX_DAYS_APART",
    "STRONG_THRESHOLD",
    "SUGGEST_THRESHOLD",
    "Candidate",
    "Movement",
    "Suggestion",
    "normalise",
    "normalise_tax_id",
    "score",
    "suggest",
]
