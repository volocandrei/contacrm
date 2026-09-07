"""Extrasul de cont, dintr-un fișier (§11, §12).

**Ce are un cabinet în mână.** Nu MT940 și nu CAMT.053 — acelea se plătesc
separat la bancă și cer un contract. Ce are este **exportul din internet
banking**: un CSV sau un Excel salvat ca CSV, cu antete scrise în românește,
diferite de la o bancă la alta. Un import care ar cere formatul standard ar fi
un import pe care nimeni nu-l poate folosi.

**De aceea coloanele se recunosc după nume, nu după poziție.** Fiecare bancă își
scrie antetele altfel — „Data operatiunii" la una, „Data tranzactiei" la alta,
„Suma" ori două coloane „Debit"/„Credit". Lista de sinonime de mai jos crește;
poziția fixă nu ar fi funcționat nici pentru a doua bancă.

**Se citește de două ori, se scrie o dată** — aceeași regulă ca la importul de
clienți, din același motiv. Prima trecere nu atinge nimic și spune ce s-ar
întâmpla: câte tranzacții noi, câte există deja, ce rânduri nu s-au putut citi și
de ce. Un extras importat greșit nu se vede: sunt trei sute de rânduri, iar
greșeala apare abia când soldul nu se închide.

**Soldurile nu se calculează, se citesc.** Dacă banca declară un sold final care
nu se potrivește cu suma tranzacțiilor citite, **asta este informația**: fișierul
este incomplet sau a fost citit greșit. Un sold calculat de noi ar fi ascuns exact
lucrul pe care extrasul îl poate dovedi.

**Același extras de două ori nu dublează nimic.** Cheia este contul plus perioada
plus numărul extrasului; iar în interiorul lui, o tranzacție deja existentă se
recunoaște după identificatorul băncii, sau — când acesta lipsește — după data,
suma și descrierea ei.
"""

from __future__ import annotations

import csv
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.errors import ValidationError
from app.domain.enums import BankDirection, BankTransactionStatus, ImportOutcome
from app.models.bank import BankStatement, BankTransaction
from app.models.user import User

#: Câte rânduri se acceptă. Un extras lunar al unui client are sub o mie; peste
#: atât, cineva a lipit un an întreg într-un fișier.
MAX_ROWS: Final = 5000

#: Antetele acceptate, în forma în care le scriu băncile românești.
#:
#: Sunt citite din exporturi reale de internet banking. Lista **va crește** — este
#: exact locul în care se adaugă o bancă nouă, fără să se atingă nimic altceva.
COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "booking_date": (
        "data",
        "data operatiunii",
        "data tranzactiei",
        "data inregistrarii",
        "data procesarii",
        # Exporturile in engleza nu sunt un caz exotic: bancile digitale
        # (Revolut, Wise) si internet bankingul corporate scriu asa.
        "booking date",
        "date",
        "transaction date",
    ),
    "value_date": ("data valutei", "value date", "data valuta"),
    "description": (
        "descriere",
        "detalii",
        "explicatii",
        "detalii tranzactie",
        "descriere plata",
        "description",
        "details",
    ),
    "amount": ("suma", "valoare", "amount"),
    "debit": ("debit", "plati", "iesiri", "suma debit", "paid out"),
    "credit": ("credit", "incasari", "intrari", "suma credit", "paid in"),
    "currency": ("moneda", "valuta", "currency"),
    "counterparty_name": (
        "beneficiar",
        "ordonator",
        "partener",
        "contrapartida",
        "nume beneficiar",
        "denumire partener",
        "beneficiary",
        "counterparty",
        "payee",
    ),
    "counterparty_iban": (
        "iban",
        "cont",
        "iban partener",
        "cont beneficiar",
        "iban beneficiar",
        "account",
    ),
    "reference": (
        "referinta",
        "referinta plata",
        "nr document",
        "numar document",
        "reference",
        "payment reference",
    ),
    "external_id": (
        "id tranzactie",
        "referinta bancara",
        "id",
        "identificator",
        "transaction id",
    ),
}

#: Formatele de dată pe care le scriu băncile românești, în ordinea frecvenței.
DATE_FORMATS: Final = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%y")

_NOT_A_NUMBER = re.compile(r"[^\d,.\-]")


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """Un rând citit din fișier, înainte de a atinge baza de date."""

    line: int
    booking_date: date
    value_date: date | None
    description: str | None
    amount: Decimal
    currency: str | None
    counterparty_name: str | None
    counterparty_iban: str | None
    reference: str | None
    external_id: str | None

    @property
    def direction(self) -> BankDirection:
        return BankDirection.DEBIT if self.amount < 0 else BankDirection.CREDIT

    @property
    def fingerprint(self) -> str:
        """Ce identifică rândul când banca nu dă niciun identificator.

        Data, suma și descrierea. Două operațiuni identice în aceeași zi există
        — două plăți de 50 de lei la aceeași benzinărie — dar atunci sunt și
        două rânduri în fișier, iar poziția le desparte.
        """
        return f"{self.booking_date.isoformat()}|{self.amount}|{(self.description or '').strip()}"


@dataclass(frozen=True, slots=True)
class RowReport:
    """Ce s-a întâmplat cu un rând, în cuvintele omului care se uită."""

    line: int
    outcome: ImportOutcome
    #: Suma, ca text, ca să apară în previzualizare fără altă interogare.
    amount: str | None = None
    description: str | None = None
    note: str | None = None


@dataclass(slots=True)
class ImportPlan:
    """Ce s-ar întâmpla, sau ce s-a întâmplat."""

    rows: list[RowReport] = field(default_factory=list)
    statement_id: uuid.UUID | None = None
    #: Soldurile declarate de fișier, când le-a declarat.
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    #: Diferența dintre soldul final declarat și cel care iese din tranzacții.
    #: `None` când nu se poate calcula. Zero este răspunsul bun.
    balance_gap: Decimal | None = None

    def count(self, outcome: ImportOutcome) -> int:
        return sum(1 for row in self.rows if row.outcome is outcome)

    @property
    def created(self) -> int:
        return self.count(ImportOutcome.NEW)

    @property
    def skipped(self) -> int:
        """Randuri care exista deja in extras. Nu o eroare — o reimportare."""
        return self.count(ImportOutcome.EXISTING)

    @property
    def failed(self) -> int:
        """Randuri care nu s-au putut citi. Fiecare are un motiv scris."""
        return self.count(ImportOutcome.INVALID)


def _key(value: str) -> str:
    """Antetul, redus la forma pe care o comparăm: litere mici, fără diacritice."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", value.strip().lower())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _map_columns(header: list[str]) -> dict[str, int]:
    """Ce coloană din fișier este ce câmp al nostru.

    Se potrivește pe numele normalizat, exact. Nu pe „conține": „data" ar fi
    înghițit „data valutei", iar tranzacțiile ar fi ajuns pe altă zi decât cea în
    care s-au făcut — o greșeală de o zi peste tot, invizibilă în total.
    """
    found: dict[str, int] = {}
    for index, raw in enumerate(header):
        name = _key(raw)
        for field_name, aliases in COLUMNS.items():
            if field_name in found:
                continue
            if name in aliases:
                found[field_name] = index
                break
    return found


def _reader(row: list[str], columns: dict[str, int]) -> Callable[[str], str | None]:
    """Citirea unei celule din rândul curent, după numele câmpului.

    Funcție separată, nu o închidere definită în buclă: o închidere care leagă
    variabila de ciclu este corectă numai cât timp se cheamă imediat, iar cine
    mută mai târziu un apel cu un rând mai jos nu are cum să vadă că a stricat-o.
    """

    def read(name: str) -> str | None:
        index = columns.get(name)
        if index is None or index >= len(row):
            return None
        value = row[index].strip()
        return value or None

    return read


def parse_amount(raw: str | None) -> Decimal | None:
    """Suma, din forma în care o scriu băncile românești.

    `1.234,56` și `1,234.56` înseamnă același lucru scris de două programe
    diferite, iar un import care ghicește greșit separatorul face din 1.234 lei
    un leu și douăzeci și trei de bani. Regula: **ultimul separator este cel
    zecimal**, iar dacă nu există decât unul singur și el are trei cifre după el,
    este separator de mii.
    """
    if raw is None:
        return None
    text = _NOT_A_NUMBER.sub("", raw.strip())
    if not text or text in {"-", ",", "."}:
        return None

    negative = text.startswith("-")
    text = text.lstrip("-")

    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma == last_dot == -1:
        cleaned = text
    else:
        separator = "," if last_comma > last_dot else "."
        tail = text[text.rfind(separator) + 1 :]
        if len(tail) == 3 and (last_comma == -1 or last_dot == -1):
            # Un singur separator, trei cifre după el: `1.234` sunt mii, nu bani.
            cleaned = text.replace(separator, "")
        else:
            cleaned = text.replace("," if separator == "." else ".", "").replace(separator, ".")

    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return -value if negative else value


def parse_date(raw: str | None) -> date | None:
    """Data, în oricare dintre formele pe care le scriu băncile."""
    if not raw:
        return None
    text = raw.strip()[:10].strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse(text: str) -> tuple[list[ParsedRow], list[RowReport]]:
    """Rândurile citite și cele care nu s-au putut citi, cu motivul lor.

    Nu aruncă la primul rând stricat: un extras cu două rânduri ilizibile din trei
    sute trebuie să poată intra cu 298, iar cele două să fie numite. Refuzul total
    ar muta munca înapoi la om — exact munca pe care importul o economisește.
    """
    stream = csv.reader(text.splitlines(), delimiter=_delimiter(text))
    try:
        header = next(stream)
    except StopIteration:
        raise ValidationError("Fișierul este gol.", {"file": ["Niciun rând."]}) from None

    columns = _map_columns(header)
    if "booking_date" not in columns:
        raise ValidationError(
            "Nu găsesc coloana cu data operațiunii.",
            {"file": ["Antetul trebuie sa contina „Data” sau „Data operatiunii”."]},
        )
    if not {"amount", "debit", "credit"} & set(columns):
        raise ValidationError(
            "Nu găsesc coloana cu suma.",
            {"file": ["Antetul trebuie sa contina „Suma”, sau „Debit” si „Credit”."]},
        )

    rows: list[ParsedRow] = []
    problems: list[RowReport] = []

    for number, raw in enumerate(stream, start=2):
        if number - 1 > MAX_ROWS:
            raise ValidationError(
                f"Fișierul are peste {MAX_ROWS} de rânduri.",
                {"file": ["Împarte-l pe luni."]},
            )
        if not any(cell.strip() for cell in raw):
            continue

        read = _reader(raw, columns)

        booking = parse_date(read("booking_date"))
        if booking is None:
            problems.append(
                RowReport(
                    line=number,
                    outcome=ImportOutcome.INVALID,
                    note="Data nu se poate citi.",
                    description=read("description"),
                )
            )
            continue

        amount = _amount_of(read)
        if amount is None or amount == 0:
            problems.append(
                RowReport(
                    line=number,
                    outcome=ImportOutcome.INVALID,
                    note="Suma lipsește sau este zero.",
                    description=read("description"),
                )
            )
            continue

        rows.append(
            ParsedRow(
                line=number,
                booking_date=booking,
                value_date=parse_date(read("value_date")),
                description=(read("description") or None),
                amount=amount,
                currency=(read("currency") or None),
                counterparty_name=(read("counterparty_name") or None),
                counterparty_iban=_iban(read("counterparty_iban")),
                reference=(read("reference") or None),
                external_id=(read("external_id") or None),
            )
        )

    return rows, problems


def _amount_of(read: Callable[[str], str | None]) -> Decimal | None:
    """Suma, fie dintr-o coloană cu semn, fie din perechea debit/credit.

    Debitul se scrie de obicei pozitiv într-o coloană separată; noi ținem semnul
    pe sumă, ca direcția să aibă o singură sursă de adevăr.
    """
    single = parse_amount(read("amount"))
    if single is not None:
        return single

    debit = parse_amount(read("debit"))
    if debit is not None and debit != 0:
        return -abs(debit)
    credit = parse_amount(read("credit"))
    if credit is not None and credit != 0:
        return abs(credit)
    return None


def _iban(value: str | None) -> str | None:
    """IBAN-ul, fără spații și cu majuscule — forma în care se compară."""
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned or None


def _delimiter(text: str) -> str:
    """`;` sau `,`, după care apare mai des pe primul rând.

    Excelul românesc scrie `;`; exporturile în engleză scriu `,`. Ghicitul se face
    pe **antet**, unde nu există sume cu virgulă zecimală care să încurce numărătoarea.
    """
    header = text.splitlines()[0] if text.splitlines() else ""
    return ";" if header.count(";") >= header.count(",") else ","


class BankImportService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def plan(
        self,
        text: str,
        *,
        actor: User | None,
        client_id: uuid.UUID | None,
        iban: str | None,
        bank_name: str | None,
        statement_number: str | None,
        opening_balance: Decimal | None,
        closing_balance: Decimal | None,
        apply: bool,
    ) -> ImportPlan:
        """Ce s-ar întâmpla (`apply=False`) sau ce s-a întâmplat (`apply=True`).

        Aceeași funcție pentru amândouă, deliberat: două funcții s-ar fi despărțit
        la prima corectură, iar previzualizarea ar fi arătat altceva decât face
        importul — cel mai prost fel posibil de a pierde încrederea într-un ecran.
        """
        rows, problems = parse(text)
        plan = ImportPlan(rows=list(problems))
        plan.opening_balance = opening_balance
        plan.closing_balance = closing_balance

        if not rows:
            return plan

        period_start = min(row.booking_date for row in rows)
        period_end = max(row.booking_date for row in rows)
        account = _iban(iban)

        statement = self._existing(account, period_start, period_end, statement_number)
        known = self._known_transactions(statement)

        total = sum(row.amount for row in rows)
        if opening_balance is not None and closing_balance is not None:
            plan.balance_gap = closing_balance - (opening_balance + total)

        if apply and statement is None:
            statement = BankStatement(
                organization_id=self.organization_id,
                client_id=client_id,
                bank_name=bank_name,
                iban=account,
                statement_number=statement_number,
                currency=next((row.currency for row in rows if row.currency), None),
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                imported_at=clock_now(),
                imported_by_id=actor.id if actor else None,
            )
            self.session.add(statement)
            self.session.flush()

        if statement is not None:
            plan.statement_id = statement.id

        position = self._next_position(statement)
        for row in rows:
            marker = row.external_id or row.fingerprint
            if marker in known:
                plan.rows.append(
                    RowReport(
                        line=row.line,
                        outcome=ImportOutcome.EXISTING,
                        amount=str(row.amount),
                        description=row.description,
                        note="Există deja în extras.",
                    )
                )
                continue

            known.add(marker)
            plan.rows.append(
                RowReport(
                    line=row.line,
                    outcome=ImportOutcome.NEW,
                    amount=str(row.amount),
                    description=row.description,
                )
            )

            if apply and statement is not None:
                self.session.add(
                    BankTransaction(
                        statement_id=statement.id,
                        organization_id=self.organization_id,
                        client_id=client_id or statement.client_id,
                        position=position,
                        booking_date=row.booking_date,
                        value_date=row.value_date,
                        description=row.description,
                        amount=row.amount,
                        currency=row.currency or statement.currency,
                        direction=row.direction,
                        counterparty_name=row.counterparty_name,
                        counterparty_iban=row.counterparty_iban,
                        reference=row.reference,
                        external_id=row.external_id,
                        status=BankTransactionStatus.UNMATCHED,
                    )
                )
                position += 1

        if apply:
            self.session.flush()
        plan.rows.sort(key=lambda item: item.line)
        return plan

    def _existing(
        self,
        iban: str | None,
        period_start: date,
        period_end: date,
        statement_number: str | None,
    ) -> BankStatement | None:
        """Extrasul deja importat pentru același cont și aceeași perioadă."""
        return self.session.scalars(
            select(BankStatement).where(
                BankStatement.organization_id == self.organization_id,
                BankStatement.iban == iban,
                BankStatement.period_start == period_start,
                BankStatement.period_end == period_end,
                BankStatement.statement_number == statement_number,
            )
        ).first()

    def _known_transactions(self, statement: BankStatement | None) -> set[str]:
        if statement is None:
            return set()
        found: set[str] = set()
        for existing in statement.transactions:
            if existing.external_id:
                found.add(existing.external_id)
            found.add(
                f"{existing.booking_date.isoformat()}|{existing.amount}|"
                f"{(existing.description or '').strip()}"
            )
        return found

    def _next_position(self, statement: BankStatement | None) -> int:
        if statement is None or not statement.transactions:
            return 1
        return max(item.position for item in statement.transactions) + 1


__all__ = [
    "COLUMNS",
    "DATE_FORMATS",
    "MAX_ROWS",
    "BankImportService",
    "ImportPlan",
    "ParsedRow",
    "RowReport",
    "parse",
    "parse_amount",
    "parse_date",
]
