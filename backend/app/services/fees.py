"""Onorariile: cine cât plătește, cine a plătit, cine e restant.

**Ce rezolvă.** Cabinetul are deja în aplicație lista de clienți, lunile și cine e
activ. Ce ținea separat, aproape întotdeauna într-un Excel, era coloana cu banii:
cât ia de la fiecare și cine n-a plătit încă. Coloana aceea se pierde, se dublează
și nu se potrivește niciodată cu lista de clienți, pentru că lista trăiește în
altă parte.

**Ce nu face.** Nu emite facturi (vezi `app/models/fee.py`) și nu trimite nimic
nimănui. Marcarea unei încasări este gestul omului care a văzut extrasul.

**Trei reguli, toate din același principiu: aplicația nu inventează.**

1. **Nu generează luni de dinaintea relației.** `starts_on` spune de când se
   facturează un client. Fără regula asta, un cabinet care își configurează
   onorariile azi ar deschide ecranul pe o listă de restanțe inventate pentru
   toate lunile din urmă — exact greșeala făcută o dată la termene.
2. **Nu generează luni viitoare.** Luna în curs se facturează, cele de după nu
   s-au întâmplat încă.
3. **Nu rescrie ce s-a generat.** A doua generare pe aceeași lună nu atinge
   rândurile existente, nici sumele lor: dacă onorariul s-a renegociat între
   timp, luna deja generată rămâne cât a fost.

**Totalurile sunt pe monedă.** Un cabinet cu un client în euro și restul în lei
are două sume, nu una. Adunarea lor ar da un număr care nu înseamnă nimic, dar pe
care cineva l-ar citi ca pe cifra lunii.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.domain.enums import ClientStatus
from app.domain.periods import format_reference_month, split_reference_month
from app.models.client import Client
from app.models.fee import DEFAULT_CURRENCY, ClientFee, FeeEntry
from app.models.user import User


def _month_start(reference_month: str) -> date:
    year, month = split_reference_month(reference_month)
    return date(year, month, 1)


@dataclass(frozen=True, slots=True)
class FeeRow:
    """Un client pe luna cerută: cât are de plătit și dacă a plătit."""

    client_id: uuid.UUID
    client_name: str
    #: Onorariul în vigoare. `None` înseamnă „nu i s-a stabilit unul".
    configured: Decimal | None
    #: Suma lunii, înghețată la generare. `None` = luna nu este generată.
    amount: Decimal | None
    currency: str
    paid_on: date | None
    paid_by_name: str | None
    note: str | None

    @property
    def is_generated(self) -> bool:
        return self.amount is not None

    @property
    def is_paid(self) -> bool:
        return self.paid_on is not None


@dataclass(frozen=True, slots=True)
class FeeTotals:
    """Cifrele lunii, pentru o monedă."""

    currency: str
    billed: Decimal
    collected: Decimal
    outstanding: Decimal


@dataclass(frozen=True, slots=True)
class Arrear:
    """O lună neîncasată, mai veche decât cea de pe ecran."""

    client_id: uuid.UUID
    client_name: str
    period: str
    amount: Decimal
    currency: str


class FeeService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    # ── Onorariul convenit ──────────────────────────────────────────────────

    def fees(self) -> dict[uuid.UUID, ClientFee]:
        rows = self.session.scalars(
            select(ClientFee).where(ClientFee.organization_id == self.organization_id)
        )
        return {row.client_id: row for row in rows}

    def for_client(self, client_id: uuid.UUID) -> ClientFee | None:
        self._client(client_id)
        return self.session.scalars(
            select(ClientFee).where(
                ClientFee.organization_id == self.organization_id,
                ClientFee.client_id == client_id,
            )
        ).one_or_none()

    def set_for_client(
        self,
        client_id: uuid.UUID,
        *,
        amount: Decimal | None,
        currency: str = DEFAULT_CURRENCY,
        starts_on: date | None = None,
        note: str | None = None,
    ) -> ClientFee | None:
        """Stabilește sau șterge onorariul.

        `amount=None` îl șterge: un cabinet care nu mai facturează un client
        trebuie să poată spune asta fără să scrie zero, care înseamnă altceva —
        „îl servesc gratuit".

        Lunile deja generate **nu** se ating: suma lor a fost înghețată atunci,
        iar o renegociere de azi nu rescrie ce s-a facturat în ianuarie.
        """
        existing = self.for_client(client_id)
        if amount is None:
            if existing is not None:
                self.session.delete(existing)
                self.session.flush()
            return None

        if amount < 0:
            raise ValidationError("Onorariul nu poate fi negativ.")
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("Moneda se scrie din trei litere, ca „RON”.")

        if existing is None:
            existing = ClientFee(
                organization_id=self.organization_id,
                client_id=client_id,
                amount=amount,
                currency=currency.upper(),
                # Fără o dată explicită, relația începe luna aceasta: aplicația
                # nu presupune că i se datorează bani pe lunile trecute.
                starts_on=starts_on or date.today().replace(day=1),
                note=note,
            )
            self.session.add(existing)
        else:
            existing.amount = amount
            existing.currency = currency.upper()
            if starts_on is not None:
                existing.starts_on = starts_on
            existing.note = note
        self.session.flush()
        return existing

    # ── Luna ────────────────────────────────────────────────────────────────

    def month(self, reference_month: str) -> list[FeeRow]:
        """Clienții care apar pe luna cerută.

        **Cine apare.** Cine are deja un rând pe luna aceea — rândul este faptul,
        indiferent ce s-a întâmplat de atunci cu clientul. Plus clienții activi a
        căror relație începuse: onorariul de la `starts_on`, iar dacă nu au unul
        stabilit, de la data la care au fost adăugați în cabinet.

        Ultima parte contează: fără ea, un client adăugat luna aceasta ar apărea
        pe lunile de acum doi ani, ca și cum ar fi datorat bani atunci.
        """
        start = _month_start(reference_month)
        fees = self.fees()
        entries = {
            entry.client_id: entry
            for entry in self.session.scalars(
                select(FeeEntry).where(
                    FeeEntry.organization_id == self.organization_id,
                    FeeEntry.period == reference_month,
                )
            )
        }
        names = self._payer_names(entries.values())

        rows: list[FeeRow] = []
        for client in self._clients(with_entries=set(entries)):
            entry = entries.get(client.id)
            fee = fees.get(client.id)
            if entry is None and self._started_on(client, fee) > start:
                continue
            rows.append(
                FeeRow(
                    client_id=client.id,
                    client_name=client.name,
                    configured=fee.amount if fee else None,
                    amount=entry.amount if entry else None,
                    currency=self._currency(entry, fee),
                    paid_on=entry.paid_on if entry else None,
                    paid_by_name=names.get(entry.paid_by) if entry and entry.paid_by else None,
                    note=entry.note if entry else None,
                )
            )
        rows.sort(key=lambda row: row.client_name.casefold())
        return rows

    def row(self, client_id: uuid.UUID, reference_month: str) -> FeeRow:
        """Un singur rând, citit prin aceeași cale ca ecranul.

        Compus separat, ar fi putut arăta altceva decât lista — de exemplu un
        nume de coleg format după altă regulă.
        """
        for row in self.month(reference_month):
            if row.client_id == client_id:
                return row
        raise NotFoundError("Rând de onorariu", f"{client_id}/{reference_month}")

    def totals(self, rows: list[FeeRow]) -> list[FeeTotals]:
        """Cifrele se adună din rândurile de pe ecran, nu dintr-o a doua interogare.

        Două căi de calcul ar fi ajuns, într-o zi, la două numere diferite pentru
        aceeași lună — iar cel de sus, care se citește primul, ar fi fost cel
        crezut.
        """
        by_currency: dict[str, list[FeeRow]] = {}
        for row in rows:
            if row.is_generated:
                by_currency.setdefault(row.currency, []).append(row)

        totals = []
        for currency, group in by_currency.items():
            billed = sum((row.amount or Decimal(0) for row in group), Decimal(0))
            collected = sum((row.amount or Decimal(0) for row in group if row.is_paid), Decimal(0))
            totals.append(
                FeeTotals(
                    currency=currency,
                    billed=billed,
                    collected=collected,
                    outstanding=billed - collected,
                )
            )
        # Leii primii, restul alfabetic: cabinetul citește cifra în lei.
        totals.sort(key=lambda item: (item.currency != DEFAULT_CURRENCY, item.currency))
        return totals

    def unpaid_count(self, rows: list[FeeRow]) -> int:
        """Câți clienți nu au plătit luna. Un număr, peste toate monedele."""
        return sum(1 for row in rows if row.is_generated and not row.is_paid)

    def generate(self, reference_month: str, *, today: date) -> int:
        """Creează rândurile lipsă ale lunii. Întoarce câte au apărut.

        Nu atinge nimic din ce există deja: se poate apăsa de câte ori vrei.
        """
        if reference_month > format_reference_month(today):
            raise ValidationError("Nu se pot factura luni care nu au început.")

        start = _month_start(reference_month)
        fees = self.fees()
        existing = set(
            self.session.scalars(
                select(FeeEntry.client_id).where(
                    FeeEntry.organization_id == self.organization_id,
                    FeeEntry.period == reference_month,
                )
            )
        )

        created = 0
        for client in self._clients(with_entries=set()):
            fee = fees.get(client.id)
            # Fără onorariu stabilit nu există ce factura: aplicația nu
            # inventează o sumă pentru un client căruia nu i s-a pus una.
            if fee is None or client.id in existing or fee.starts_on > start:
                continue
            self.session.add(
                FeeEntry(
                    organization_id=self.organization_id,
                    client_id=client.id,
                    period=reference_month,
                    # Înghețată acum: renegocierea de peste trei luni n-o schimbă.
                    amount=fee.amount,
                    currency=fee.currency,
                )
            )
            created += 1
        self.session.flush()
        return created

    # ── Încasarea ───────────────────────────────────────────────────────────

    def mark_paid(
        self,
        client_id: uuid.UUID,
        reference_month: str,
        *,
        paid_on: date,
        user: User | None,
        note: str | None = None,
    ) -> FeeEntry:
        entry = self._entry(client_id, reference_month)
        if entry is None:
            raise NotFoundError("Lună facturată", f"{client_id}/{reference_month}")
        entry.paid_on = paid_on
        entry.paid_by = user.id if user else None
        if note is not None:
            entry.note = note
        self.session.flush()
        return entry

    def unmark(self, client_id: uuid.UUID, reference_month: str) -> FeeEntry:
        """Anulează încasarea marcată din greșeală.

        Rândul rămâne: luna a fost facturată chiar dacă banii nu au intrat.
        """
        entry = self._entry(client_id, reference_month)
        if entry is None:
            raise NotFoundError("Lună facturată", f"{client_id}/{reference_month}")
        entry.paid_on = None
        entry.paid_by = None
        self.session.flush()
        return entry

    def arrears(self, before: str, *, limit: int = 200) -> list[Arrear]:
        """Lunile neîncasate mai vechi decât cea de pe ecran.

        Restanța veche este singura care nu se mai vede nicăieri: luna trece,
        ecranul se schimbă, iar banii rămân neîncasați fără să afle cineva.
        """
        rows = self.session.execute(
            select(FeeEntry, Client.name)
            .join(Client, Client.id == FeeEntry.client_id)
            .where(
                FeeEntry.organization_id == self.organization_id,
                FeeEntry.period < before,
                FeeEntry.paid_on.is_(None),
            )
            .order_by(FeeEntry.period.desc(), Client.name)
            .limit(limit)
        )
        return [
            Arrear(
                client_id=entry.client_id,
                client_name=name,
                period=entry.period,
                amount=entry.amount,
                currency=entry.currency,
            )
            for entry, name in rows
        ]

    # ── Ajutoare ────────────────────────────────────────────────────────────

    def _clients(self, *, with_entries: set[uuid.UUID]) -> list[Client]:
        """Clienții activi, plus cei care au deja un rând pe luna cerută.

        Un client suspendat nu se mai facturează de luna viitoare, dar lunile lui
        deja facturate nu dispar de pe ecran doar pentru că a plecat — mai ales
        când sunt tocmai cele neîncasate.
        """
        condition = Client.status == ClientStatus.ACTIVE
        if with_entries:
            condition = or_(condition, Client.id.in_(with_entries))
        return list(
            self.session.scalars(
                select(Client).where(
                    Client.organization_id == self.organization_id,
                    Client.deleted_at.is_(None),
                    condition,
                )
            )
        )

    @staticmethod
    def _started_on(client: Client, fee: ClientFee | None) -> date:
        """De când face clientul parte din lunile facturabile."""
        if fee is not None:
            return fee.starts_on
        return client.created_at.date().replace(day=1)

    @staticmethod
    def _currency(entry: FeeEntry | None, fee: ClientFee | None) -> str:
        if entry is not None:
            return entry.currency
        return fee.currency if fee is not None else DEFAULT_CURRENCY

    def _client(self, client_id: uuid.UUID) -> Client:
        client = self.session.scalars(
            select(Client).where(
                Client.id == client_id,
                Client.organization_id == self.organization_id,
                Client.deleted_at.is_(None),
            )
        ).one_or_none()
        if client is None:
            # §72: 404, nu 403 — un 403 ar confirma că id-ul există în altă firmă.
            raise NotFoundError("Client", client_id)
        return client

    def _entry(self, client_id: uuid.UUID, reference_month: str) -> FeeEntry | None:
        self._client(client_id)
        return self.session.scalars(
            select(FeeEntry).where(
                FeeEntry.organization_id == self.organization_id,
                FeeEntry.client_id == client_id,
                FeeEntry.period == reference_month,
            )
        ).one_or_none()

    def _payer_names(self, entries: Iterable[FeeEntry]) -> dict[uuid.UUID, str]:
        ids = {entry.paid_by for entry in entries if entry.paid_by}
        if not ids:
            return {}
        return {
            user.id: user.full_name
            for user in self.session.scalars(select(User).where(User.id.in_(ids)))
        }


__all__ = ["Arrear", "FeeRow", "FeeService", "FeeTotals"]
