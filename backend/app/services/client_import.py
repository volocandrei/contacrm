"""Lista de clienți, dintr-un fișier.

**Golul pe care îl umple.** Un cabinet are între treizeci și trei sute de
clienți, iar lista lor există deja undeva: într-un Excel, în exportul din
programul vechi, în tabelul pe care îl ține contabilul-șef. Până acum, singurul
drum înăuntru era formularul, client cu client. Nimeni nu tastează două sute de
firme ca să încerce o aplicație — deci aplicația nu se încerca.

**Se citește de două ori, se scrie o dată.** Prima trecere nu atinge nimic și
răspunde cu ce **s-ar** întâmpla: câți clienți noi, câți există deja, ce rânduri
sunt stricate și de ce. Un import care creează tăcut două sute de clienți greșiți
este mai rău decât niciunul: nimeni nu-i mai poate deosebi de cei buni, iar
ștergerea lor cere exact munca pe care importul o economisea.

**Nu suprascrie niciodată.** Un client al cărui CUI există deja se sare, chiar
dacă rândul din fișier are altă adresă sau alt nume. Fișierul poate fi vechi de
un an; ce a tastat un om în aplicație este mai proaspăt decât ce a exportat
cineva din alt program. Rândul spune „există deja", nu dispare — altfel
diferența dintre „am importat 40" și „am importat 200" nu s-ar putea explica.

**Un CUI greșit se semnalează, nu se refuză.** Cifra de control prinde tastările
greșite, dar nu orice cod care nu trece este fals: sunt firme străine, sunt
persoane fizice autorizate, sunt coduri vechi. Rândul intră, cu o notă lângă el.
Aplicația nu știe mai bine decât omul cine sunt clienții lui.

**Contactul intră odată cu firma.** Coloanele de email, telefon și WhatsApp fac
diferența dintre o listă de nume și o agendă: fără adresă, clientul nou nu poate
primi nici solicitarea de documente, nici reminderul, iar cabinetul descoperă
asta abia la sfârșitul primei luni.
"""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.domain.enums import ClientStatus, ImportOutcome
from app.domain.romanian_documents import is_valid_tax_id
from app.models.client import Client
from app.services.client_matching import normalize_tax_id
from app.services.client_service import ActorContext, ClientService
from app.services.excel_csv import BOM, DELIMITER

#: Câte rânduri se acceptă într-un fișier. Un cabinet cu peste atât de mulți
#: clienți are alte probleme decât importul, iar limita ține cererea sub timpul
#: maxim al oricărei platforme.
MAX_ROWS: Final = 1000

#: Cât de mare poate fi fișierul. Un CSV de o mie de rânduri are sub 200 KB;
#: peste asta, cineva a urcat altceva.
MAX_BYTES: Final = 2 * 1024 * 1024


#: Antetele acceptate, în forma în care le scrie un om. Cheia este numele intern.
#:
#: **De ce mai multe variante.** Fișierul vine dintr-un export străin sau dintr-un
#: Excel scris de mână acum trei ani. Un import care cere exact „Nr. reg. com."
#: și refuză „Reg com" mută munca înapoi la om, exact munca pe care o economisea.
COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "name": ("denumire", "nume", "client", "firma", "denumire client"),
    "tax_id": ("cui", "cif", "cod fiscal", "cod unic", "cod unic de inregistrare"),
    "registration_number": ("nr reg com", "reg com", "numar registrul comertului", "j"),
    "address": ("adresa", "sediu", "sediu social"),
    "status": ("status", "stare"),
    "contact_name": ("persoana de contact", "contact", "persoana contact"),
    "email": ("email", "e-mail", "adresa email"),
    "phone": ("telefon", "tel", "mobil"),
    "whatsapp_number": ("whatsapp", "numar whatsapp"),
}

#: Cum se scrie statusul în românește, ca fișierul să nu ceară cuvinte englezești.
STATUS_WORDS: Final[dict[str, ClientStatus]] = {
    "activ": ClientStatus.ACTIVE,
    "active": ClientStatus.ACTIVE,
    "inactiv": ClientStatus.INACTIVE,
    "inactive": ClientStatus.INACTIVE,
    "prospect": ClientStatus.PROSPECT,
    "potential": ClientStatus.PROSPECT,
}

#: Rândul de antet al modelului descărcabil, în ordinea în care se completează.
TEMPLATE_HEADER: Final = (
    "Denumire",
    "CUI",
    "Nr. reg. com.",
    "Adresă",
    "Status",
    "Persoană de contact",
    "Email",
    "Telefon",
    "WhatsApp",
)

#: Un rând de exemplu, ca să se vadă forma așteptată — nu un client adevărat (§70).
TEMPLATE_EXAMPLE: Final = (
    "Exemplu Prest SRL",
    "RO12345678",
    "J40/1234/2020",
    "Str. Exemplu nr. 1, București",
    "Activ",
    "Ion Popescu",
    "ion.popescu@exemplu.ro",
    "0722 000 000",
    "0722 000 000",
)


@dataclass(frozen=True, slots=True)
class ImportRow:
    """Un rând din fișier, așa cum îl vede omul înainte să apese."""

    #: Numărul rândului din fișier, antetul inclus. Ca să-l poată găsi în Excel.
    line: int
    name: str
    tax_id: str | None
    outcome: ImportOutcome
    #: De ce, când rezultatul nu se explică singur.
    note: str | None = None
    #: Rândul intră, dar ceva merită o privire — un CUI care nu trece verificarea.
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Ce s-ar întâmpla, sau ce s-a întâmplat."""

    rows: list[ImportRow]
    #: Dacă fișierul a fost doar citit. Fals înseamnă că s-a și scris.
    dry_run: bool = True

    @property
    def created(self) -> int:
        return sum(1 for row in self.rows if row.outcome is ImportOutcome.NEW)

    @property
    def existing(self) -> int:
        return sum(1 for row in self.rows if row.outcome is ImportOutcome.EXISTING)

    @property
    def duplicates(self) -> int:
        return sum(1 for row in self.rows if row.outcome is ImportOutcome.DUPLICATE)

    @property
    def invalid(self) -> int:
        return sum(1 for row in self.rows if row.outcome is ImportOutcome.INVALID)


@dataclass(slots=True)
class _Parsed:
    """Valorile curate ale unui rând, înainte să se decidă ce se face cu ele."""

    line: int
    name: str
    tax_id: str | None
    values: dict[str, str] = field(default_factory=dict)


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
    if len(raw) > MAX_BYTES:
        raise ValidationError(
            "Fișierul este prea mare.",
            {"file": [f"Maximum {MAX_BYTES // (1024 * 1024)} MB."]},
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


def _delimiter(first_line: str) -> str:
    """`;` sau `,`, după care apare mai des în antet.

    Excel românesc scrie `;`; un export făcut de un programator scrie `,`. A
    cere unul singur ar fi însemnat că jumătate dintre fișiere sosesc cu tot
    rândul într-o coloană, iar mesajul „lipsește coloana Denumire" ar fi trimis
    omul să caute exact în partea greșită.
    """
    return DELIMITER if first_line.count(DELIMITER) >= first_line.count(",") else ","


def _key(header: str) -> str:
    """Antetul, redus la ce se poate compara: fără diacritice, punctuație, caz."""
    lowered = header.strip().lower().replace(BOM, "")
    for source, target in (("ă", "a"), ("â", "a"), ("î", "i"), ("ș", "s"), ("ț", "t")):
        lowered = lowered.replace(source, target)
    cleaned = "".join(character for character in lowered if character.isalnum() or character == " ")
    # Spațiile rămase se strâng: „Nr.  reg. com." și „Nr reg com" sunt același antet.
    return " ".join(cleaned.split())


def _map_columns(header: list[str]) -> dict[str, int]:
    """Ce coloană din fișier corespunde cărui câmp."""
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = _key(cell)
        for field_name, aliases in COLUMNS.items():
            if field_name not in mapping and key in aliases:
                mapping[field_name] = index
    if "name" not in mapping:
        raise ValidationError(
            "Fișierul nu are o coloană de denumire.",
            {"file": [f"Prima coloană trebuie să fie una dintre: {', '.join(COLUMNS['name'])}."]},
        )
    return mapping


def parse(text: str) -> list[_Parsed]:
    """Rândurile fișierului, curățate. Nu atinge baza de date."""
    lines = text.splitlines()
    if not lines:
        raise ValidationError("Fișierul este gol.", {"file": ["Nu are niciun rând."]})

    reader = csv.reader(lines, delimiter=_delimiter(lines[0]))
    rows = list(reader)
    mapping = _map_columns(rows[0])

    parsed: list[_Parsed] = []
    for offset, cells in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in cells):
            continue  # rânduri goale la sfârșit, cum lasă Excel
        if len(parsed) >= MAX_ROWS:
            raise ValidationError(
                "Fișierul are prea multe rânduri.",
                {"file": [f"Maximum {MAX_ROWS} de clienți odată."]},
            )
        values = {
            name: cells[index].strip()
            for name, index in mapping.items()
            if index < len(cells) and cells[index].strip()
        }
        parsed.append(
            _Parsed(
                line=offset,
                name=values.get("name", ""),
                tax_id=normalize_tax_id(values.get("tax_id")) or None,
                values=values,
            )
        )
    return parsed


class ClientImportService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id
        self.clients = ClientService(session)

    def plan(self, text: str, *, actor: ActorContext, apply: bool = False) -> ImportPlan:
        """Ce s-ar întâmpla — sau, cu `apply`, ce s-a întâmplat.

        **Aceeași funcție pentru amândouă**, deliberat. Două implementări ar fi
        însemnat că previzualizarea promite una și importul face alta, iar
        diferența s-ar fi văzut abia după ce baza avea deja clienții greșiți
        înăuntru.
        """
        parsed = parse(text)
        known = self._existing_tax_ids()
        seen: set[str] = set()
        rows: list[ImportRow] = []

        for entry in parsed:
            row = self._decide(entry, known=known, seen=seen)
            if row.outcome is ImportOutcome.NEW:
                seen.add(entry.tax_id or f"line:{entry.line}")
                if apply:
                    self._create(entry, actor=actor)
            rows.append(row)

        return ImportPlan(rows=rows, dry_run=not apply)

    def _decide(self, entry: _Parsed, *, known: set[str], seen: set[str]) -> ImportRow:
        if not entry.name:
            return ImportRow(
                line=entry.line,
                name="",
                tax_id=entry.tax_id,
                outcome=ImportOutcome.INVALID,
                note="Rândul nu are denumire.",
            )
        if entry.tax_id and entry.tax_id in seen:
            return ImportRow(
                line=entry.line,
                name=entry.name,
                tax_id=entry.tax_id,
                outcome=ImportOutcome.DUPLICATE,
                note="Același CUI apare mai sus în fișier.",
            )
        if entry.tax_id and entry.tax_id in known:
            return ImportRow(
                line=entry.line,
                name=entry.name,
                tax_id=entry.tax_id,
                outcome=ImportOutcome.EXISTING,
                note="Există deja un client cu acest CUI. Rândul nu îl modifică.",
            )

        warning = None
        if entry.tax_id and not is_valid_tax_id(entry.tax_id):
            # Se semnalează, nu se refuză: firmele străine și unele coduri vechi
            # nu trec verificarea, iar aplicația nu știe mai bine decât omul cine
            # sunt clienții lui.
            warning = "CUI-ul nu trece verificarea cifrei de control."
        elif not entry.tax_id:
            warning = "Fără CUI: documentele din e-Factura nu se vor lega singure."
        elif not entry.values.get("email"):
            warning = "Fără email: clientul nu poate primi solicitări sau remindere."

        return ImportRow(
            line=entry.line,
            name=entry.name,
            tax_id=entry.tax_id,
            outcome=ImportOutcome.NEW,
            warning=warning,
        )

    def _create(self, entry: _Parsed, *, actor: ActorContext) -> None:
        client = self.clients.create(
            self.organization_id,
            {
                "name": entry.name,
                # Codul se scrie normalizat, ca peste tot: `RO 14.399.840` și
                # `14399840` sunt același client, iar potrivirea documentelor se
                # face pe forma curată.
                "tax_id": entry.tax_id,
                "registration_number": entry.values.get("registration_number"),
                "address": entry.values.get("address"),
                "status": _status(entry.values.get("status")),
            },
            actor,
        )
        if not any(entry.values.get(key) for key in ("contact_name", "email", "phone")):
            return
        self.clients.add_contact(
            self.organization_id,
            client.id,
            {
                # Fără nume, contactul poartă numele firmei: adresa este ce
                # contează, iar un contact refuzat pentru lipsa numelui ar fi
                # lăsat clientul fără nicio cale de a fi anunțat.
                "full_name": entry.values.get("contact_name") or entry.name,
                "email": entry.values.get("email"),
                "phone": entry.values.get("phone"),
                "whatsapp_number": entry.values.get("whatsapp_number"),
                "is_primary": True,
            },
            actor,
        )

    def _existing_tax_ids(self) -> set[str]:
        rows = self.session.scalars(
            select(Client.tax_id).where(
                Client.organization_id == self.organization_id,
                Client.tax_id.is_not(None),
                Client.deleted_at.is_(None),
            )
        )
        return {normalize_tax_id(value) for value in rows if value}


def _status(raw: str | None) -> ClientStatus:
    """Statusul scris în fișier, sau „activ".

    **Implicit activ, nu prospect.** Cine importă o listă importă clienții pe
    care îi are, nu firme la care speră. Un import care ar face două sute de
    prospecți ar lăsa cabinetul fără nicio lună de urmărit și fără niciun termen
    — adică exact fără aplicație.
    """
    if not raw:
        return ClientStatus.ACTIVE
    return STATUS_WORDS.get(_key(raw), ClientStatus.ACTIVE)


def template() -> str:
    """Modelul de fișier, cu un rând de exemplu.

    Există pentru că altfel prima încercare eșuează pe antet, iar a doua nu mai
    are loc: omul închide ecranul și scrie clienții de mână.
    """
    from app.services.excel_csv import render

    return render([list(TEMPLATE_HEADER), list(TEMPLATE_EXAMPLE)])


__all__ = [
    "MAX_ROWS",
    "TEMPLATE_HEADER",
    "ClientImportService",
    "ImportOutcome",
    "ImportPlan",
    "ImportRow",
    "decode",
    "parse",
    "template",
]
