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
            ]
        )


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
