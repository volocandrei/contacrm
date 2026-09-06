"""Ce s-a întâmplat cu un client, în ordine.

**Întrebarea la care răspunde.** „Ce e cu firma asta?" — pusă înainte de un
telefon, la o predare, sau când cineva reia un client de la un coleg. Până acum
răspunsul se strângea din patru ecrane: documentele lui, linkurile de trimitere,
termenele, perioadele.

**Nimic nu se stochează.** Cronologia se compune la citire, din faptele care sunt
deja înregistrate în altă parte. Un tabel de evenimente ar fi însemnat că fiecare
acțiune trebuie să-și amintească să scrie și acolo — iar ziua în care una uită
este ziua în care cronologia începe să mintă prin omisiune.

**Ce nu conține.** Conținutul documentelor și textul mesajelor. Cronologia spune
*că* a sosit o factură și *că* i s-a cerut ceva, nu ce scria în ele — aceeași
linie ca la jurnalul de audit (§33). Cine vrea documentul îl deschide de pe rând.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, TimelineEventKind
from app.models.document import Document
from app.models.obligation import ObligationFiling, ObligationType
from app.models.period import AccountingPeriod
from app.models.upload_link import ClientUploadLink

#: Câte evenimente se întorc dacă nu se cere altceva.
#:
#: Cronologia se citește de sus în jos, iar cine ajunge la al cincizecilea rând a
#: găsit deja ce căuta. O listă nemărginită ar fi însemnat, la un client vechi,
#: mii de rânduri trimise degeaba.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """Un fapt, cu momentul lui.

    `detail` este text scurt, de context — luna, canalul, numele declarației.
    Eticheta felului o dă interfața; aici este doar `kind`.
    """

    at: datetime
    kind: TimelineEventKind
    title: str
    detail: str | None = None
    document_id: uuid.UUID | None = None


class ClientTimelineService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def for_client(
        self, client_id: uuid.UUID, *, limit: int = DEFAULT_LIMIT
    ) -> list[TimelineEvent]:
        """Faptele clientului, cel mai recent primul.

        Fiecare sursă se interoghează limitat, apoi se îmbină și se retează încă o
        dată: patru interogări nemărginite, îmbinate, ar fi adus în memorie tot
        istoricul unui client vechi ca să arunce apoi 95% din el.
        """
        events = [
            *self._documents(client_id, limit),
            *self._requests(client_id, limit),
            *self._filings(client_id, limit),
            *self._closings(client_id, limit),
        ]
        events.sort(key=lambda event: event.at, reverse=True)
        return events[:limit]

    def _documents(self, client_id: uuid.UUID, limit: int) -> list[TimelineEvent]:
        rows = self.session.scalars(
            select(Document)
            .where(
                Document.organization_id == self.organization_id,
                Document.client_id == client_id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.received_at.desc())
            .limit(limit)
        )
        return [
            TimelineEvent(
                at=document.received_at,
                kind=TimelineEventKind.DOCUMENT_RECEIVED,
                title=document.stored_filename or document.original_filename,
                # Canalul, nu conținutul: „pe email" spune de ce a ajuns aici, iar
                # la un client care trimite prost este chiar informația căutată.
                detail=_source_detail(document.source, document.reference_month),
                document_id=document.id,
            )
            for document in rows
        ]

    def _requests(self, client_id: uuid.UUID, limit: int) -> list[TimelineEvent]:
        """Cererile de documente: când s-a compus și, separat, dacă a plecat.

        Două evenimente din același rând, deliberat. „Pregătit" și „Trimis" sunt
        lucruri diferite — primul spune că textul a fost compus, al doilea că a
        ajuns la cineva —, iar un client care nu răspunde se explică altfel dacă
        mesajul n-a plecat niciodată.
        """
        rows = list(
            self.session.scalars(
                select(ClientUploadLink)
                .where(
                    ClientUploadLink.organization_id == self.organization_id,
                    ClientUploadLink.client_id == client_id,
                    ClientUploadLink.reference_month.is_not(None),
                )
                .order_by(ClientUploadLink.created_at.desc())
                .limit(limit)
            )
        )

        events: list[TimelineEvent] = []
        for link in rows:
            events.append(
                TimelineEvent(
                    at=link.created_at,
                    kind=TimelineEventKind.REQUEST_PREPARED,
                    title="Solicitare de documente",
                    detail=link.reference_month,
                )
            )
            if link.notified_at is not None:
                events.append(
                    TimelineEvent(
                        at=link.notified_at,
                        kind=TimelineEventKind.REQUEST_SENT,
                        title="Solicitare trimisă",
                        # Adresa, fiindcă la un client cu trei contacte contează
                        # către care a plecat.
                        detail=link.notified_to,
                    )
                )
        return events

    def _filings(self, client_id: uuid.UUID, limit: int) -> list[TimelineEvent]:
        rows = self.session.execute(
            select(ObligationFiling, ObligationType.code)
            .join(ObligationType, ObligationFiling.obligation_type_id == ObligationType.id)
            .where(
                ObligationFiling.organization_id == self.organization_id,
                ObligationFiling.client_id == client_id,
            )
            .order_by(ObligationFiling.filed_at.desc())
            .limit(limit)
        )
        return [
            TimelineEvent(
                at=filing.filed_at,
                kind=TimelineEventKind.OBLIGATION_FILED,
                title=code,
                detail=filing.period,
            )
            for filing, code in rows
        ]

    def _closings(self, client_id: uuid.UUID, limit: int) -> list[TimelineEvent]:
        rows = self.session.scalars(
            select(AccountingPeriod)
            .where(
                AccountingPeriod.organization_id == self.organization_id,
                AccountingPeriod.client_id == client_id,
                AccountingPeriod.closed_at.is_not(None),
            )
            .order_by(AccountingPeriod.closed_at.desc())
            .limit(limit)
        )
        return [
            TimelineEvent(
                at=period.closed_at,
                kind=TimelineEventKind.PERIOD_CLOSED,
                title="Lună închisă",
                detail=period.reference_month,
            )
            for period in rows
            if period.closed_at is not None
        ]


def _source_detail(source: DocumentSource, reference_month: str | None) -> str:
    """Canalul și luna, în cuvintele pe care le-ar folosi cineva din cabinet."""
    channel = {
        DocumentSource.EMAIL: "pe email",
        DocumentSource.WHATSAPP: "pe WhatsApp",
        DocumentSource.UPLOAD: "urcat de noi",
        DocumentSource.API: "prin API",
        DocumentSource.ONEDRIVE: "din OneDrive",
        DocumentSource.EFACTURA: "din SPV",
        DocumentSource.PORTAL: "prin linkul de trimitere",
    }.get(source, source.value)
    return f"{channel} · {reference_month}" if reference_month else channel


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "ClientTimelineService", "TimelineEvent"]
