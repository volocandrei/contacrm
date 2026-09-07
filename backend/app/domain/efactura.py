"""Citirea unei facturi electronice (UBL 2.1 / RO_CIUS, e-Factura ANAF).

**De ce merită un modul separat.** Tot restul extracției lucrează pe text și are
o singură regulă: *nu ghici*. O factură electronică schimbă complet situația —
este un document **structurat**, în care fiecare valoare stă într-un element cu
nume. Nu se citește un total dintr-un text, se citește câmpul „total". Nu există
încredere parțială: fie elementul este acolo, fie nu este.

De la 1 iulie 2024, între firme din România factura electronică este obligatorie.
Pentru un cabinet asta înseamnă că partea covârșitoare a facturilor vine ca XML,
nu ca PDF scanat — și că, pentru ele, verificarea umană poate deveni o citire, nu
o completare.

**Ce nu face acest modul.** Nu vorbește cu ANAF: nu descarcă, nu trimite, nu
verifică semnătura. Sunt trei lucruri diferite, cu credențiale și implicații
proprii (Faza 2). Aici se citește un fișier care a ajuns deja la noi, local, fără
rețea — la fel ca `pdf_text`.

**Securitate.** XML-ul vine din afară. Parsarea se face prin `defusedxml`, care
refuză DTD-urile și entitățile, adică exact vectorii „billion laughs" și XXE. Un
fișier care conține așa ceva este respins, nu curățat: o factură reală nu are
DOCTYPE, deci refuzul nu costă niciun caz legitim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from defusedxml import ElementTree as DefusedET

# Spațiile de nume UBL 2.1. Sunt fixe prin standard, nu ghicite din fișier.
CBC: Final = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
CAC: Final = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"

INVOICE_ROOT: Final = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
CREDIT_NOTE_ROOT: Final = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"

# O valoare citită dintr-un câmp cu nume nu este o presupunere. Nu există „80%
# sigur că scrie 1190,00" într-un document structurat: ori elementul e acolo, ori
# nu e. Ecranul de verificare o arată ca citită de pe document, cu 100%.
CERTAIN: Final = 1.0

# Numărul facturii poate arăta ca „FCT 123", dar UBL nu are câmp separat pentru
# serie. Îl despărțim doar când forma este neîndoielnică: litere, apoi cifre.
_SERIES_AND_NUMBER = re.compile(r"^([A-Z]{1,10})[\s\-/]?(\d{1,20})$", re.IGNORECASE)

# Codurile UBL pentru tipul documentului (UNTDID 1001). Ne interesează doar cele
# care schimbă felul documentului, nu toate cele ~40.
CREDIT_NOTE_CODES: Final = frozenset({"381", "396"})


class EFacturaError(Exception):
    """Fișierul nu este o factură electronică pe care o putem citi."""


@dataclass(frozen=True, slots=True)
class Party:
    """O parte a facturii, așa cum o declară documentul."""

    name: str | None
    tax_id: str | None


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """O linie de factură: ce s-a vândut, cât, cu ce cotă de TVA.

    **De ce nu ajunge TVA-ul de pe factură.** Pe aceeași factură pot sta trei
    cote — 21% pentru un produs, 11% pentru altul, 0% pentru un serviciu scutit —
    iar contabilul are nevoie de fiecare separat, pentru decont. Un singur procent
    la nivel de document este o medie fără sens contabil, iar din el nu se poate
    reconstitui defalcarea.

    **De ce este de încredere.** Într-un XML UBL fiecare valoare stă într-un
    element cu nume: nu se citește un procent dintr-un text, se citește câmpul
    `Percent`. Aici nu există „80% sigur". Din PDF-uri liniile nu se citesc încă
    — și nu se vor ghici: o linie inventată intră direct în decontul de TVA.

    Sumele rămân șiruri, ca în restul modulului: se convertesc o singură dată, la
    scriere, cu regulile de rotunjire ale aplicației.
    """

    #: Numărul liniei de pe document (`cbc:ID`), nu poziția în listă.
    number: str | None
    description: str | None
    quantity: str | None
    #: Codul UN/ECE al unității (`H87` = bucată, `HUR` = oră). Se păstrează așa
    #: cum vine: traducerea lui este o listă de o mie de coduri, iar contabilul
    #: recunoaște codul.
    unit_code: str | None
    unit_price: str | None
    #: `LineExtensionAmount`: valoarea liniei **fără** TVA, după reducere.
    net_amount: str | None
    #: Cota, ca număr: `19`, `21`, `0`. Fără semnul procent.
    vat_rate: str | None
    #: Categoria UBL (`S` = cotă standard, `AE` = taxare inversă, `E` = scutit,
    #: `Z` = cotă zero). Explică un `0` care altfel ar arăta ca o eroare.
    vat_category: str | None


@dataclass(frozen=True, slots=True)
class EInvoice:
    """Ce scrie în factură. Nimic dedus, nimic completat."""

    number: str | None
    series: str | None
    issue_date: str | None
    currency: str | None
    supplier: Party
    customer: Party
    subtotal: str | None
    vat_amount: str | None
    total: str | None
    is_credit_note: bool
    #: Liniile documentului, în ordinea din XML. Goală nu înseamnă „fără linii":
    #: înseamnă că documentul nu le-a declarat, iar noi nu inventăm.
    lines: tuple[InvoiceLine, ...] = ()

    @property
    def summary(self) -> str:
        """Factura în cuvinte, pentru căutare și pentru ecranul de verificare.

        Un XML nu se poate privi: nu are facsimil, iar interfața nu are ce să arate
        lângă câmpuri. Rezumatul ăsta ține locul imaginii — operatorul citește
        aceleași date, în aceeași ordine în care le-ar citi de pe hârtie.

        Este derivat, nu stocat: două exemplare cu aceleași câmpuri nu pot avea
        rezumate diferite.
        """
        return "\n".join(
            [
                "NOTĂ DE CREDIT (STORNO)" if self.is_credit_note else "FACTURĂ ELECTRONICĂ",
                f"Număr: {' '.join(filter(None, (self.series, self.number))) or '—'}",
                f"Data emiterii: {self.issue_date or '—'}",
                f"Furnizor: {self.supplier.name or '—'}",
                f"CUI furnizor: {self.supplier.tax_id or '—'}",
                f"Cumpărător: {self.customer.name or '—'}",
                f"CUI cumpărător: {self.customer.tax_id or '—'}",
                f"Bază impozabilă: {self.subtotal or '—'}",
                f"TVA: {self.vat_amount or '—'}",
                f"Total: {self.total or '—'} {self.currency or ''}".strip(),
                *self._lines_in_words(),
            ]
        )

    def _lines_in_words(self) -> list[str]:
        """Liniile, sub totaluri, în rezumatul pe care îl citește operatorul.

        Un XML nu se poate privi, iar cotele diferite de pe aceeași factură sunt
        exact ce nu se vede din totaluri. Fără rândurile astea, operatorul are
        „TVA: 250,00" și niciun mod de a afla din ce s-a compus.
        """
        if not self.lines:
            return []
        rows = ["", "Linii:"]
        for line in self.lines:
            rate = f"{line.vat_rate}%" if line.vat_rate is not None else "TVA —"
            rows.append(
                f"  {line.number or '·'}. {line.description or '—'} · "
                f"{line.quantity or '—'} x {line.unit_price or '—'} = "
                f"{line.net_amount or '—'} · {rate}"
            )
        return rows


def looks_like_xml(head: bytes) -> bool:
    """Un început de fișier XML, fără să presupunem codarea.

    Se acceptă doar declarația explicită (`<?xml`), nu orice fișier care începe cu
    `<`: altfel un HTML sau un fragment oarecare ar trece drept factură și ar fi
    respins abia mai târziu, cu un mesaj despre altceva.
    """
    for bom, prefix in (
        (b"\xef\xbb\xbf", b"<?xml"),
        (b"\xff\xfe", "<?xml".encode("utf-16-le")),
        (b"\xfe\xff", "<?xml".encode("utf-16-be")),
        (b"", b"<?xml"),
    ):
        if head.startswith(bom) and head[len(bom) :].startswith(prefix):
            return True
    return False


def _text(element: object) -> str | None:
    value = getattr(element, "text", None)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _amount(raw: str | None) -> str | None:
    """Sumele din UBL sunt în format neutru (`1190.00`), nu în cel românesc.

    Se normalizează la două zecimale ca restul sistemului; o valoare pe care nu o
    putem citi se raportează ca lipsă, nu ca zero — zero este o afirmație.
    """
    if raw is None:
        return None
    try:
        return f"{Decimal(raw):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _split_number(raw: str | None) -> tuple[str | None, str | None]:
    """Serie și număr, dacă documentul le-a lipit într-un singur câmp.

    UBL are un singur `cbc:ID`. Când forma este limpede — litere apoi cifre — le
    despărțim, pentru că numele de arhivă (§10) le folosește pe amândouă. Când nu
    este, numărul rămâne întreg: o serie inventată ar ajunge în numele fișierului.
    """
    if raw is None:
        return None, None
    match = _SERIES_AND_NUMBER.match(raw.strip())
    if match:
        return match.group(1).upper(), match.group(2)
    return None, raw.strip()


def _lines(root: object, is_credit_note: bool) -> tuple[InvoiceLine, ...]:
    """Liniile documentului, citite din elementele lor.

    O notă de credit le numește `CreditNoteLine`, iar cantitatea `CreditedQuantity`
    — restul este identic. Diferența de nume este singurul motiv pentru care
    funcția are nevoie să știe ce fel de document citește.

    O linie fără niciun câmp citibil se sare: ar fi un rând gol în registru, care
    arată ca o pierdere de date fără să fie.
    """
    findall = getattr(root, "findall", None)
    if findall is None:  # pragma: no cover — apelat doar cu un element
        return ()

    container = f"{CAC}CreditNoteLine" if is_credit_note else f"{CAC}InvoiceLine"
    quantity_tag = f"{CBC}CreditedQuantity" if is_credit_note else f"{CBC}InvoicedQuantity"

    found: list[InvoiceLine] = []
    for element in findall(container):
        quantity_element = element.find(quantity_tag)
        category = element.find(f"{CAC}Item/{CAC}ClassifiedTaxCategory")

        line = InvoiceLine(
            number=_text(element.find(f"{CBC}ID")),
            description=_text(element.find(f"{CAC}Item/{CBC}Name")),
            quantity=_number(_text(quantity_element)),
            unit_code=(quantity_element.get("unitCode") if quantity_element is not None else None),
            unit_price=_amount(_text(element.find(f"{CAC}Price/{CBC}PriceAmount"))),
            net_amount=_amount(_text(element.find(f"{CBC}LineExtensionAmount"))),
            vat_rate=(
                _number(_text(category.find(f"{CBC}Percent"))) if category is not None else None
            ),
            vat_category=(_text(category.find(f"{CBC}ID")) if category is not None else None),
        )
        if any(
            value is not None
            for value in (line.description, line.net_amount, line.quantity, line.unit_price)
        ):
            found.append(line)
    return tuple(found)


def _number(raw: str | None) -> str | None:
    """Un număr care nu este o sumă: cantitate, cotă de TVA.

    Nu se rotunjește la două zecimale ca `_amount`: o cantitate poate fi `0.001`
    (kilograme), iar o cotă este `19`, nu `19.00`. Zerourile de la coadă se taie,
    ca `21.00` din XML să se citească `21` pe ecran.
    """
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    normalised = value.normalize()
    # `normalize()` scrie numerele mari în notație exponențială (`1E+3`).
    return f"{normalised:f}"


def _party(root: object, container: str) -> Party:
    """Numele și codul fiscal ale unei părți.

    Codul fiscal poate sta în două locuri, ambele legitime: `PartyTaxScheme`
    (înregistrarea în scopuri de TVA) și `PartyLegalEntity` (identificarea firmei).
    O firmă neplătitoare de TVA îl are doar pe al doilea, deci le încercăm pe
    amândouă, în ordinea în care sunt de încredere.
    """
    find = getattr(root, "find", None)
    if find is None:  # pragma: no cover — apelat doar cu un element
        return Party(name=None, tax_id=None)

    party = find(f"{CAC}{container}/{CAC}Party")
    if party is None:
        return Party(name=None, tax_id=None)

    name = _text(party.find(f"{CAC}PartyLegalEntity/{CBC}RegistrationName")) or _text(
        party.find(f"{CAC}PartyName/{CBC}Name")
    )
    tax_id = _text(party.find(f"{CAC}PartyTaxScheme/{CBC}CompanyID")) or _text(
        party.find(f"{CAC}PartyLegalEntity/{CBC}CompanyID")
    )
    return Party(name=name, tax_id=tax_id)


def parse(content: bytes) -> EInvoice:
    """Citește o factură electronică. Aruncă `EFacturaError` dacă nu este una.

    Nu completează nimic din ce lipsește: un câmp absent din XML rămâne absent și
    aici. Un `None` cinstit costă zece secunde de completat; o valoare plauzibilă
    trece pe lângă operator.
    """
    try:
        root = DefusedET.fromstring(content)
    except Exception as exc:  # defusedxml ridică tipuri proprii pentru DTD/entități
        raise EFacturaError(f"XML invalid sau nesigur: {exc}") from exc

    if root.tag not in {INVOICE_ROOT, CREDIT_NOTE_ROOT}:
        raise EFacturaError(
            "Fișierul este XML, dar nu o factură UBL 2.1 (rădăcina este "
            f"{root.tag!r}, nu Invoice sau CreditNote)."
        )

    type_code = _text(root.find(f"{CBC}InvoiceTypeCode")) or _text(
        root.find(f"{CBC}CreditNoteTypeCode")
    )
    is_credit_note = root.tag == CREDIT_NOTE_ROOT or (type_code or "") in CREDIT_NOTE_CODES

    series, number = _split_number(_text(root.find(f"{CBC}ID")))

    # `IssueDate`, nu `DueDate`: confuzia dintre ele mută documentul în altă lună
    # contabilă. Aici distincția este explicită în document, deci nu se poate greși.
    issue_date = _text(root.find(f"{CBC}IssueDate"))

    supplier = _party(root, "AccountingSupplierParty")
    customer = _party(root, "AccountingCustomerParty")

    totals = root.find(f"{CAC}LegalMonetaryTotal")
    subtotal = total = None
    if totals is not None:
        subtotal = _amount(_text(totals.find(f"{CBC}TaxExclusiveAmount")))
        # `PayableAmount` este ce se plătește efectiv, după eventualele avansuri;
        # `TaxInclusiveAmount` este totalul facturii. Pentru contabilitate contează
        # al doilea, iar primul este rezerva când lipsește.
        total = _amount(_text(totals.find(f"{CBC}TaxInclusiveAmount"))) or _amount(
            _text(totals.find(f"{CBC}PayableAmount"))
        )

    tax_total = root.find(f"{CAC}TaxTotal")
    vat_amount = None
    if tax_total is not None:
        vat_amount = _amount(_text(tax_total.find(f"{CBC}TaxAmount")))

    currency = _text(root.find(f"{CBC}DocumentCurrencyCode"))

    return EInvoice(
        lines=_lines(root, is_credit_note),
        number=number,
        series=series,
        issue_date=issue_date,
        currency=currency,
        supplier=supplier,
        customer=customer,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
        is_credit_note=is_credit_note,
    )
