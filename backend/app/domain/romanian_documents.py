"""Ce se poate citi cu certitudine dintr-un text de document contabil (§20, §21).

Reguli, nu model. Nimic din ce este aici nu ghicește: fiecare valoare este întoarsă
doar dacă textul o marchează explicit — o etichetă („CUI", „Data emiterii", „Total
de plată") lângă valoare. Un număr găsit fără etichetă rămâne un număr.

**De ce atât de conservator.** Un câmp gol trimite documentul la un om, care îl
completează în zece secunde de pe facsimil. Un câmp completat greșit trece pe lângă
el, pentru că ecranul arată o valoare care pare citită de pe document. Prima
greșeală costă zece secunde, a doua costă o înregistrare contabilă falsă. De aceea,
peste tot mai jos, „nu știu" este un răspuns acceptabil și „probabil" nu este.

**Ce nu se încearcă deloc**, cu motiv:

- **direcția facturii** (intrare vs. ieșire) — depinde de care CUI de pe document
  este al cabinetului, iar modulul ăsta nu știe pentru cine lucrează. Un document
  pus în registrul greșit este mai rău decât unul neclasificat;
- **luna contabilă** — se derivă din dată printr-o regulă a sistemului (ADR-008),
  nu se citește de pe hârtie;
- **denumirea furnizorului** — pe o factură reală numele stă într-un bloc de adresă,
  fără etichetă și fără poziție fixă. Orice regulă ar prinde la fel de des antetul
  tipografiei.

Modulul lucrează pe text simplu, fără PDF și fără I/O, tocmai ca regulile să poată
fi verificate direct pe șiruri.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

# ── Încrederi ────────────────────────────────────────────────────────────────
#
# Nu sunt probabilități, ci cât de puțin loc de interpretare a lăsat textul.
# Pragurile din configurare (0.90 auto, 0.70 verificare) le dau înțelesul practic:
# `LABELLED` trece de aprobarea automată, `AMBIGUOUS` nu trece nici de verificare.

# Eticheta este lipită de valoare și este singura de felul ei în document.
LABELLED: Final = 0.95
# Eticheta există, dar mai sunt candidați la fel de plauzibili în text.
COMPETING: Final = 0.80
# Forma se potrivește, eticheta lipsește. Ajunge la om, cu semnalul că e nesigur.
AMBIGUOUS: Final = 0.60

# Sub atâtea caractere vizibile, un PDF nu are strat de text: este o scanare.
MIN_TEXT_LENGTH: Final = 24

# Cheia de control a codului de identificare fiscală.
# TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: algoritmul este folosit
# **doar** ca să crească încrederea într-o potrivire deja etichetată, niciodată ca
# să respingă una. Dacă cheia ar fi greșită, efectul este că valorile corecte apar
# cu încredere mai mică — ajung la verificare umană în loc să treacă automat. Un
# eșec în direcția asta este acceptabil; invers nu ar fi.
_CIF_KEY: Final = (7, 5, 3, 2, 1, 7, 5, 3, 2)


@dataclass(frozen=True, slots=True)
class Found:
    """O valoare citită din text, cu cât de puțin loc de interpretare a rămas."""

    value: str
    confidence: float


def strip_diacritics(text: str) -> str:
    """`ș`, `ț`, `ă`, `î`, `â` → forma fără semne.

    Documentele reale amestecă diacriticele corecte (`ș` cu virgulă) cu cele
    greșite (`ş` cu sedilă) și cu absența lor. Căutarea se face pe forma redusă,
    ca `Total de plată`, `Total de plata` și `Total de platã` să fie același lucru.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    """Forma pe care se caută: fără diacritice, litere mici, spații colapsate."""
    return re.sub(r"\s+", " ", strip_diacritics(text)).lower()


# ── Cod fiscal ───────────────────────────────────────────────────────────────

_TAX_ID = re.compile(
    # Eticheta, apoi eventualul prefix de TVA, apoi cifrele. Separatorii sunt
    # generoși pentru că extragerea din PDF varsă des spații în locuri ciudate.
    r"(?:c\.?u\.?i\.?|c\.?i\.?f\.?|cod\s+(?:unic\s+de\s+inregistrare|fiscal|de\s+identificare\s+fiscala))"
    r"\s*[:\-]?\s*(ro)?\s*(\d[\d\s.]{1,13}\d)",
)

# Cine este furnizorul și cine este cumpărătorul, când documentul o spune.
_SUPPLIER_MARKERS: Final = ("furnizor", "vanzator", "prestator", "emitent")
_CUSTOMER_MARKERS: Final = ("client", "cumparator", "beneficiar", "destinatar")


def is_valid_tax_id(digits: str) -> bool:
    """Cifra de control a unui CUI. Vezi nota de la `_CIF_KEY`."""
    if not digits.isdigit() or not 2 <= len(digits) <= 10:
        return False
    body, control = digits[:-1], int(digits[-1])
    # Cheia se aliniază la dreapta corpului.
    key = _CIF_KEY[-len(body) :] if len(body) <= len(_CIF_KEY) else _CIF_KEY
    padded = body[-len(key) :]
    total = sum(int(digit) * weight for digit, weight in zip(padded, key, strict=True))
    remainder = (total * 10) % 11
    return (0 if remainder == 10 else remainder) == control


def _clean_digits(raw: str) -> str:
    return re.sub(r"[\s.]", "", raw)


def find_tax_ids(text: str) -> tuple[Found | None, Found | None]:
    """Codul fiscal al furnizorului și al cumpărătorului, dacă se pot deosebi.

    O factură poartă de obicei două. Care este al cui se decide după cel mai
    apropiat marcaj dinaintea lui („Furnizor:", „Cumpărător:"). **Dacă nu există
    marcaje, niciunul nu se atribuie** — un CUI pus pe partea greșită schimbă cine
    datorează cui.
    """
    haystack = normalize(text)
    matches = [
        (match.start(), _clean_digits(match.group(2)))
        for match in _TAX_ID.finditer(haystack)
        if len(_clean_digits(match.group(2))) >= 2
    ]
    if not matches:
        return None, None

    supplier: Found | None = None
    customer: Found | None = None
    for position, digits in matches:
        # Ce rol a fost menționat cel mai recent înaintea codului.
        before = haystack[:position]
        role = _closest_role(before)
        confidence = LABELLED if is_valid_tax_id(digits) else COMPETING
        found = Found(value=digits, confidence=confidence)
        if role == "supplier" and supplier is None:
            supplier = found
        elif role == "customer" and customer is None:
            customer = found

    return supplier, customer


def _closest_role(before: str) -> str | None:
    positions: list[tuple[int, str]] = []
    for marker in _SUPPLIER_MARKERS:
        index = before.rfind(marker)
        if index != -1:
            positions.append((index, "supplier"))
    for marker in _CUSTOMER_MARKERS:
        index = before.rfind(marker)
        if index != -1:
            positions.append((index, "customer"))
    if not positions:
        return None
    return max(positions)[1]


# ── Dată ─────────────────────────────────────────────────────────────────────

_DATE_LABEL = re.compile(
    r"(data\s+(?:emiterii|facturii|documentului)?|data)\s*[:\-]?\s*"
    r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"
)
# `Data scadentei` este data la care se plătește, nu data documentului. Confuzia
# dintre ele mută documentul în altă lună contabilă.
_DUE_DATE = re.compile(r"(?:scadent|termen\s+de\s+plata)")


def find_document_date(text: str) -> Found | None:
    """Data documentului, doar când este etichetată ca atare."""
    haystack = normalize(text)
    candidates: list[Found] = []

    for match in _DATE_LABEL.finditer(haystack):
        # Eticheta de scadență apare des chiar înaintea datei; o excludem uitându-ne
        # în fereastra dinaintea potrivirii.
        window = haystack[max(0, match.start() - 30) : match.start() + len(match.group(1))]
        if _DUE_DATE.search(window):
            continue

        day, month, year = (int(match.group(i)) for i in (2, 3, 4))
        try:
            parsed = date(year, month, day)
        except ValueError:
            # `31.02.2026` nu este o dată. Nu o „reparăm".
            continue
        candidates.append(Found(value=parsed.isoformat(), confidence=LABELLED))

    if not candidates:
        return None
    # Mai multe date etichetate identic înseamnă că eticheta nu a fost decisivă.
    if len({found.value for found in candidates}) > 1:
        return Found(value=candidates[0].value, confidence=COMPETING)
    return candidates[0]


# ── Serie și număr ───────────────────────────────────────────────────────────

_SERIES_NUMBER = re.compile(
    r"seri[ae]\s*[:\-]?\s*([a-z0-9]{1,10})\s*(?:nr\.?|numar(?:ul)?)\s*[:\-]?\s*([a-z0-9\-/]{1,20})"
)
_NUMBER_ONLY = re.compile(r"(?:nr\.?|numar(?:ul)?)\s*[:\-]?\s*([a-z0-9\-/]{1,20})")


def find_series_and_number(text: str) -> tuple[Found | None, Found | None]:
    """Seria și numărul documentului.

    Seria fără număr nu înseamnă nimic, deci se caută întâi împreună. Numărul
    singur este util și se acceptă separat — bonurile fiscale nu au serie.
    """
    haystack = normalize(text)

    if match := _SERIES_NUMBER.search(haystack):
        return (
            Found(value=match.group(1).upper(), confidence=LABELLED),
            Found(value=match.group(2).upper(), confidence=LABELLED),
        )

    numbers = _NUMBER_ONLY.findall(haystack)
    if not numbers:
        return None, None
    # „nr." apare și în „nr. crt." dintr-un tabel de poziții; mai multe potriviri
    # înseamnă că nu putem spune care este numărul documentului.
    confidence = LABELLED if len(numbers) == 1 else AMBIGUOUS
    return None, Found(value=numbers[0].upper(), confidence=confidence)


# ── Sume ─────────────────────────────────────────────────────────────────────

_AMOUNT = r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"

_TOTAL = re.compile(r"total\s*(?:de\s*plata|general|factura)?\s*[:\-]?\s*(?:lei|ron)?\s*" + _AMOUNT)
_VAT = re.compile(
    r"(?:t\.?v\.?a\.?|taxa\s+pe\s+valoarea\s+adaugata)\s*[:\-]?\s*(?:lei|ron)?\s*" + _AMOUNT
)
_SUBTOTAL = re.compile(
    r"(?:valoare|baza\s+impozabila|total\s+fara\s+tva)\s*[:\-]?\s*(?:lei|ron)?\s*" + _AMOUNT
)


def parse_amount(raw: str) -> Decimal | None:
    """`1.234,56` și `1234.56` sunt aceeași sumă scrisă în două convenții.

    Regula: dacă există virgulă, ea este separatorul zecimal și punctul este de mii
    (convenția românească). Dacă nu există virgulă, un punct cu exact două zecimale
    este separator zecimal, altfel este de mii.
    """
    cleaned = re.sub(r"\s", "", raw)
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{3}$", cleaned) or cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    # Banii nu sunt niciodată float, nici măcar o clipă (§13).
    return amount.quantize(Decimal("0.01")) if amount >= 0 else None


def _find_amount(pattern: re.Pattern[str], haystack: str) -> Found | None:
    values = [
        parsed
        for match in pattern.finditer(haystack)
        if (parsed := parse_amount(match.group(1))) is not None
    ]
    if not values:
        return None
    if len(set(values)) > 1:
        # Un total apare de obicei de mai multe ori pe pagină, dar cu aceeași
        # valoare. Valori diferite sub aceeași etichetă înseamnă că eticheta nu
        # distinge — cel mai des un tabel de poziții.
        return Found(value=f"{max(values):.2f}", confidence=AMBIGUOUS)
    return Found(value=f"{values[0]:.2f}", confidence=LABELLED)


def find_amounts(text: str) -> dict[str, Found]:
    """Total, TVA și bază impozabilă, fiecare doar dacă este etichetat.

    Nu se calculează nimic. Dacă lipsește TVA-ul, nu îl deducem din total: cota nu
    este a noastră de presupus, iar o factură poate avea mai multe cote pe același
    document (§13).
    """
    haystack = normalize(text)
    found: dict[str, Found] = {}
    for name, pattern in (
        ("totalAmount", _TOTAL),
        ("vatAmount", _VAT),
        ("subtotal", _SUBTOTAL),
    ):
        if amount := _find_amount(pattern, haystack):
            found[name] = amount
    return found


# ── Monedă ───────────────────────────────────────────────────────────────────

_CURRENCIES: Final = {"ron": "RON", "lei": "RON", "eur": "EUR", "usd": "USD"}
_CURRENCY = re.compile(r"\b(ron|lei|eur|usd)\b")


def find_currency(text: str) -> Found | None:
    """Moneda, dacă documentul folosește una singură.

    Două monede pe același document înseamnă de obicei un curs de schimb afișat
    alături; care este moneda facturii nu se poate spune din simpla prezență.
    """
    codes = {_CURRENCIES[match] for match in _CURRENCY.findall(normalize(text))}
    if len(codes) != 1:
        return None
    return Found(value=codes.pop(), confidence=LABELLED)


# ── Tip de document ──────────────────────────────────────────────────────────

# Doar tipurile care se recunosc dintr-un titlu, fără ambiguitate. `FACTURA` lipsește
# intenționat: direcția (intrare/ieșire) nu se poate deduce fără să știm al cui este
# cabinetul, iar un document pus în registrul greșit este mai rău decât unul
# neclasificat, pe care oricum îl atinge un om.
_TYPE_MARKERS: Final = (
    ("bon fiscal", "BON_FISCAL"),
    ("extras de cont", "EXTRAS_CONT"),
    ("chitanta", "CHITANTA"),
    ("aviz de insotire", "AVIZ_INSOTIRE"),
    ("contract", "CONTRACT"),
)


# O factură se recunoaște din titlu; **direcția** ei nu. „Proforma" este exclusă
# intenționat: nu este un document contabil, ci o ofertă.
_INVOICE = re.compile(r"\bfactur[aeă]\b")
_NOT_AN_INVOICE = re.compile(r"\bproform")


def invoice_candidates(text: str, *, known_codes: frozenset[str]) -> tuple[str, ...]:
    """Codurile între care documentul sigur se află, dar pe care textul nu le separă.

    Textul spune „factură" fără să spună a cui este. Direcția depinde de care CUI
    de pe document aparține cabinetului — o informație pe care sistemul o are și
    documentul nu. Se rezolvă la identificarea clientului
    (`app/services/client_matching.py`), nu aici.

    Perechea se întoarce doar dacă amândouă codurile există la organizație:
    altfel rezolvarea de mai târziu ar putea alege unul pe care scrierea îl refuză.
    """
    haystack = normalize(text)
    if not _INVOICE.search(haystack) or _NOT_AN_INVOICE.search(haystack):
        return ()
    pair = ("FACTURA_INTRARE", "FACTURA_IESIRE")
    return pair if all(code in known_codes for code in pair) else ()


def classify(text: str, *, known_codes: frozenset[str]) -> Found | None:
    """Tipul documentului, doar când titlul îl spune.

    `known_codes` vine din tipurile configurate ale organizației (§6): nu propunem
    un cod pe care cabinetul nu îl are definit.
    """
    haystack = normalize(text)
    hits = [code for marker, code in _TYPE_MARKERS if marker in haystack and code in known_codes]
    if len(hits) != 1:
        return None
    return Found(value=hits[0], confidence=LABELLED)


__all__ = [
    "AMBIGUOUS",
    "COMPETING",
    "LABELLED",
    "MIN_TEXT_LENGTH",
    "Found",
    "classify",
    "find_amounts",
    "find_currency",
    "find_document_date",
    "find_series_and_number",
    "find_tax_ids",
    "invoice_candidates",
    "is_valid_tax_id",
    "normalize",
    "parse_amount",
    "strip_diacritics",
]
