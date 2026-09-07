"""Ce are cabinetul de depus, pentru cine, și până când.

**Nimic nu se stochează calculat.** Termenele nu stau într-un tabel de „termene
viitoare" pe care cineva ar trebui să-l regenereze. Se calculează la citire, din
trei lucruri care se schimbă rar: ce declarații are clientul, cât de des se depun
și în ce zi. Un tabel de termene generate în avans se desincronizează în tăcere de
configurare — exact motivul pentru care nici starea perioadelor nu se stochează.

Se stochează **doar faptul uman**: cineva a marcat o perioadă ca depusă.

**Ce înseamnă „întârziat".** Termenul a trecut și nu există rând de depunere.
Nu există o a treia stare: o declarație ori a plecat, ori nu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.domain.enums import ObligationFrequency
from app.domain.obligations import due_between
from app.models.client import Client
from app.models.obligation import ClientObligation, ObligationFiling, ObligationType
from app.models.user import User

#: Cât în viitor se uită ecranul dacă nu i se cere altceva.
#:
#: Șase săptămâni acoperă întotdeauna termenul lunii curente și pe cel al lunii
#: următoare, oricând ai deschide ecranul. O fereastră de o lună îl ascunde pe
#: al doilea exact în zilele în care ar trebui început.
DEFAULT_HORIZON_DAYS = 45

#: Cât în urmă se uită, ca întârziatele să nu dispară.
#:
#: Un termen ratat nu se rezolvă trecând timpul. Rămâne pe ecran până este
#: marcat, fiindcă altfel singurul lucru pe care aplicația ar putea să-l facă cu
#: el ar fi să-l uite.
OVERDUE_LOOKBACK_DAYS = 120


@dataclass(frozen=True, slots=True)
class DueObligation:
    """O declarație a unui client, pentru o perioadă, cu termenul ei."""

    client_id: uuid.UUID
    client_name: str
    obligation_type_id: uuid.UUID
    code: str
    label: str
    frequency: ObligationFrequency
    period: str
    deadline: date
    filed_at: datetime | None
    filed_by_name: str | None
    note: str | None

    def is_filed(self) -> bool:
        return self.filed_at is not None

    def is_overdue(self, today: date) -> bool:
        return not self.is_filed() and self.deadline < today


class ObligationService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    # ── Catalog ─────────────────────────────────────────────────────────────

    def types(self, *, only_active: bool = False) -> list[ObligationType]:
        statement = select(ObligationType).where(
            ObligationType.organization_id == self.organization_id
        )
        if only_active:
            statement = statement.where(ObligationType.is_active.is_(True))
        return list(
            self.session.scalars(statement.order_by(ObligationType.sort_order, ObligationType.code))
        )

    def get_type(self, obligation_type_id: uuid.UUID) -> ObligationType:
        row = self.session.scalars(
            select(ObligationType).where(
                ObligationType.organization_id == self.organization_id,
                ObligationType.id == obligation_type_id,
            )
        ).first()
        if row is None:
            # 404, nu 403: existența unei declarații a altui cabinet nu se
            # confirmă nici măcar printr-un refuz (§72).
            raise NotFoundError("Obligație", obligation_type_id)
        return row

    # ── Ce depune fiecare client ────────────────────────────────────────────

    def for_client(self, client_id: uuid.UUID) -> list[ObligationType]:
        self._client(client_id)
        return list(
            self.session.scalars(
                select(ObligationType)
                .join(ClientObligation, ClientObligation.obligation_type_id == ObligationType.id)
                .where(
                    ClientObligation.organization_id == self.organization_id,
                    ClientObligation.client_id == client_id,
                )
                .order_by(ObligationType.sort_order, ObligationType.code)
            )
        )

    def set_for_client(
        self, client_id: uuid.UUID, obligation_type_ids: list[uuid.UUID]
    ) -> list[ObligationType]:
        """Înlocuiește setul clientului cu cel primit.

        Înlocuire, nu adăugare: ecranul arată bifele tuturor declarațiilor, iar
        ce se trimite înapoi **este** starea de pe ecran. Un `PATCH` care doar
        adaugă ar face imposibilă scoaterea unei declarații.
        """
        client = self._client(client_id)
        wanted = {self.get_type(type_id).id for type_id in obligation_type_ids}

        self.session.execute(
            delete(ClientObligation).where(
                ClientObligation.organization_id == self.organization_id,
                ClientObligation.client_id == client.id,
            )
        )
        for type_id in wanted:
            self.session.add(
                ClientObligation(
                    organization_id=self.organization_id,
                    client_id=client.id,
                    obligation_type_id=type_id,
                )
            )
        self.session.flush()
        return self.for_client(client.id)

    # ── Termenele ───────────────────────────────────────────────────────────

    def upcoming(
        self,
        *,
        since: date,
        until: date,
        client_id: uuid.UUID | None = None,
    ) -> list[DueObligation]:
        """Tot ce are termen în fereastră, depus sau nu, în ordinea termenelor.

        Depusele rămân în listă. Un ecran care le-ar ascunde ar arăta identic
        când munca este gata și când clientul nu are configurată nicio
        declarație — două situații care cer lucruri opuse.
        """
        if since > until:
            raise ValidationError(
                "Intervalul este întors.",
                details={"since": ["Trebuie să fie anterioară datei de sfârșit."]},
            )

        pairs = self._pairs(client_id)
        if not pairs:
            return []

        due: list[tuple[Client, ObligationType, str, date]] = []
        for client, obligation, configured_on in pairs:
            for entry in due_between(
                obligation.frequency,
                months_after=obligation.months_after,
                deadline_day=obligation.deadline_day,
                since=since,
                until=until,
            ):
                if entry.deadline < configured_on:
                    # **Aplicația nu inventează restanțe.**
                    #
                    # Un cabinet care instalează azi a depus, evident, și luna
                    # trecută — dar aplicația nu are de unde ști, fiindcă nu
                    # exista. Prima variantă arăta 52 de rânduri roșii pe o
                    # instalare proaspătă: nu informație, ci o afirmație despre
                    # ceva ce nu a văzut. După a treia zi nimeni nu s-ar mai fi
                    # uitat la culoarea aia, nici când ar fi însemnat ceva.
                    #
                    # Momentul de referință este ziua în care i s-a spus că acest
                    # client depune această declarație. Se compară cu **termenul**,
                    # nu cu perioada: configurat azi, decontul lunii trecute are
                    # termen peste trei săptămâni și este al cabinetului.
                    continue
                due.append((client, obligation, entry.period, entry.deadline))

        filings = self._filings({(client.id, o.id, period) for client, o, period, _ in due})

        rows: list[DueObligation] = []
        for client, obligation, period, deadline in due:
            filing = filings.get((client.id, obligation.id, period))
            rows.append(
                DueObligation(
                    client_id=client.id,
                    client_name=client.name,
                    obligation_type_id=obligation.id,
                    code=obligation.code,
                    label=obligation.label,
                    frequency=obligation.frequency,
                    period=period,
                    deadline=deadline,
                    filed_at=filing[0] if filing else None,
                    filed_by_name=filing[1] if filing else None,
                    note=filing[2] if filing else None,
                )
            )
        # Pe termen, apoi pe client: două declarații cu același termen se citesc
        # mai ușor grupate pe cine le depune.
        rows.sort(key=lambda row: (row.deadline, row.client_name, row.code))
        return rows

    # ── Faptul uman ─────────────────────────────────────────────────────────

    def mark_filed(
        self,
        *,
        client_id: uuid.UUID,
        obligation_type_id: uuid.UUID,
        period: str,
        user: User,
        note: str | None = None,
    ) -> ObligationFiling:
        """Marchează perioada ca depusă. A doua oară nu creează un al doilea rând."""
        client = self._client(client_id)
        obligation = self.get_type(obligation_type_id)

        existing = self._filing(client.id, obligation.id, period)
        if existing is not None:
            # Idempotent: două apăsări pe același buton nu sunt două depuneri, iar
            # a doua nu are voie să rescrie cine a depus prima oară.
            return existing

        filing = ObligationFiling(
            organization_id=self.organization_id,
            client_id=client.id,
            obligation_type_id=obligation.id,
            period=period,
            filed_at=datetime.now(UTC),
            filed_by=user.id,
            note=note,
        )
        self.session.add(filing)
        self.session.flush()
        return filing

    def filings_for_client(
        self, client_id: uuid.UUID
    ) -> list[tuple[ObligationFiling, ObligationType]]:
        """Ce s-a înregistrat pentru clientul acesta, cea mai recentă întâi.

        **De ce există ruta.** Depunerile obișnuite se văd pe ecranul de termene,
        fiindcă acolo există un rând calculat pe care să se așeze bifa. O
        obligație fără calendar nu produce niciun rând — vezi
        `ObligationFrequency.ON_DEMAND`. Fără lista asta, cineva ar înregistra
        situațiile financiare interimare și ele ar dispărea din interfață în
        aceeași clipă: scrise în evidență, invizibile pe ecran. Un lucru
        înregistrat pe care nimeni nu-l mai poate vedea se înregistrează a doua
        oară.
        """
        self._client(client_id)
        rows = self.session.execute(
            select(ObligationFiling, ObligationType)
            .join(ObligationType, ObligationType.id == ObligationFiling.obligation_type_id)
            .where(
                ObligationFiling.organization_id == self.organization_id,
                ObligationFiling.client_id == client_id,
            )
            .order_by(ObligationFiling.period.desc(), ObligationFiling.filed_at.desc())
        ).all()
        return [(filing, obligation_type) for filing, obligation_type in rows]

    def unmark(self, *, client_id: uuid.UUID, obligation_type_id: uuid.UUID, period: str) -> None:
        """Șterge marcajul. Cineva a apăsat pe rândul greșit."""
        filing = self._filing(client_id, obligation_type_id, period)
        if filing is None:
            raise NotFoundError("Depunere", f"{client_id}/{obligation_type_id}/{period}")
        self.session.delete(filing)
        self.session.flush()

    # ── Interne ─────────────────────────────────────────────────────────────

    def _client(self, client_id: uuid.UUID) -> Client:
        row = self.session.scalars(
            select(Client).where(
                Client.organization_id == self.organization_id,
                Client.id == client_id,
                Client.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise NotFoundError("Client", client_id)
        return row

    def _pairs(self, client_id: uuid.UUID | None) -> list[tuple[Client, ObligationType, date]]:
        """Perechile client-declarație, cu ziua în care au fost legate.

        Ziua aceea este linia de la care aplicația are dreptul să spună ceva
        despre ce s-a depus și ce nu.
        """
        statement = (
            select(Client, ObligationType, ClientObligation.created_at)
            .join(ClientObligation, ClientObligation.client_id == Client.id)
            .join(ObligationType, ClientObligation.obligation_type_id == ObligationType.id)
            .where(
                ClientObligation.organization_id == self.organization_id,
                Client.deleted_at.is_(None),
                # O declarație scoasă din catalog nu mai produce termene, dar
                # depunerile ei rămân: istoricul nu se rescrie.
                ObligationType.is_active.is_(True),
            )
        )
        if client_id is not None:
            statement = statement.where(Client.id == client_id)
        return [
            (client, obligation, configured_at.date())
            for client, obligation, configured_at in self.session.execute(statement)
        ]

    def _filings(
        self, keys: set[tuple[uuid.UUID, uuid.UUID, str]]
    ) -> dict[tuple[uuid.UUID, uuid.UUID, str], tuple[datetime, str | None, str | None]]:
        """Depunerile existente, într-o singură interogare.

        Cheia este tripletul (client, declarație, perioadă) — același pe care îl
        apără constrângerea de unicitate.
        """
        if not keys:
            return {}
        periods = {period for _, _, period in keys}
        rows = self.session.execute(
            select(ObligationFiling, User.full_name)
            .outerjoin(User, ObligationFiling.filed_by == User.id)
            .where(
                ObligationFiling.organization_id == self.organization_id,
                ObligationFiling.period.in_(periods),
            )
        )
        found: dict[tuple[uuid.UUID, uuid.UUID, str], tuple[datetime, str | None, str | None]] = {}
        for filing, filed_by_name in rows:
            found[(filing.client_id, filing.obligation_type_id, filing.period)] = (
                filing.filed_at,
                filed_by_name,
                filing.note,
            )
        return found

    def _filing(
        self, client_id: uuid.UUID, obligation_type_id: uuid.UUID, period: str
    ) -> ObligationFiling | None:
        return self.session.scalars(
            select(ObligationFiling).where(
                ObligationFiling.organization_id == self.organization_id,
                ObligationFiling.client_id == client_id,
                ObligationFiling.obligation_type_id == obligation_type_id,
                ObligationFiling.period == period,
            )
        ).first()


__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "OVERDUE_LOOKBACK_DAYS",
    "DueObligation",
    "ObligationService",
]
