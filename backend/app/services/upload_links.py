"""Linkurile de trimitere, și regulile care le țin sigure.

Aceasta este singura parte a aplicației care acceptă o **scriere fără sesiune**.
Tot ce urmează există din cauza asta.

**Tokenul.** 32 de octeți din `secrets`, codificați URL-safe. Se arată o singură
dată, la creare; în bază stă doar SHA-256 al lui — aceeași regulă ca la refresh
tokenuri, din același motiv: o bază citită de altcineva nu trebuie să dea linkuri
funcționale. Nu se folosește Argon2 aici, fiindcă tokenul este generat de noi și
are entropie mare: hash-ul lent apără parolele alese de oameni, nu cheile aleatorii.

**Comparația se face pe hash, nu pe token.** Căutarea în bază după `token_hash`
este o egalitate pe un index — nu există aici un canal de timp care să scurgă
tokenul, fiindcă atacatorul ar trebui să ghicească 256 de biți ca să ajungă la o
comparație.

**Ce nu poate face cine are linkul.** Nu poate citi nimic: nu listează, nu
descarcă, nu află ce s-a trimis deja și nu află numele clientului. Poate doar să
adauge. Un link scurs este, în cel mai rău caz, un drum prin care cineva trimite
documente nedorite — supărător, dar nu o scurgere de date; iar drumul se închide
dintr-un buton.

**Expirarea este obligatorie.** Un link trimis pe email rămâne în inbox-ul acelui
email ani de zile. O coloană care se poate lăsa goală devine, în practică, goală.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.organization import Organization
from app.models.upload_link import ClientUploadLink

#: Cât ține un link, implicit. O lună contabilă plus marja de depunere: destul ca
#: un client să trimită tot ce are pentru luna cerută, prea puțin ca linkul să
#: rămână valabil când relația cu clientul s-a încheiat.
DEFAULT_VALIDITY = timedelta(days=45)

#: Peste atât nu se mai emite. Un „link permanent" este exact ce nu vrem.
MAX_VALIDITY = timedelta(days=180)

#: 32 de octeți: 256 de biți de entropie. Ghicitul nu este o cale de atac.
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedLink:
    """Un link nou. `token` se vede o singură dată — după asta rămâne doar hash-ul."""

    id: uuid.UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class RequestTrace:
    """Urma ultimei cereri pregătite pentru un client, într-o lună.

    **De ce contează.** Un cabinet cere documentele a treizeci de clienți în
    aceeași săptămână. Fără urmă, peste trei zile îi cere de două ori unuia și îl
    uită complet pe altul — iar uitatul nu costă timp, costă o lună.

    `received_through_link` numără **prin linkul acela**, nu în general. Este exact
    întrebarea de urmărire: i-am cerut, a făcut ceva? Documentele venite altfel
    închid golul singure, iar atunci rândul dispare din raport.
    """

    requested_at: datetime
    received_through_link: int


@dataclass(frozen=True)
class LinkTarget:
    """Unde duce un link valid. Fără nimic care ar identifica clientul public."""

    link_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    client_id: uuid.UUID


class UploadLinkService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def issue(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        *,
        created_by_id: uuid.UUID | None,
        validity: timedelta = DEFAULT_VALIDITY,
        reference_month: str | None = None,
    ) -> IssuedLink:
        """Deschide un drum de trimitere pentru un client.

        Un client poate avea mai multe linkuri deodată — de exemplu unul dat
        contabilului intern și altul administratorului. Ce contează este că
        fiecare se poate închide separat.
        """
        token = secrets.token_urlsafe(TOKEN_BYTES)
        expires_at = datetime.now(UTC) + min(validity, MAX_VALIDITY)

        link = ClientUploadLink(
            organization_id=organization_id,
            client_id=client_id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            created_by_id=created_by_id,
            reference_month=reference_month,
        )
        self.session.add(link)
        self.session.flush()
        return IssuedLink(id=link.id, token=token, expires_at=expires_at)

    def resolve(self, token: str) -> LinkTarget | None:
        """Unde duce tokenul, dacă mai duce undeva.

        Un token inexistent, expirat, revocat sau al unui client șters întorc
        toate `None`, fără să spună care dintre ele: cine încearcă linkuri nu are
        de ce să afle că unul a existat cândva.
        """
        if not token:
            return None

        row = self.session.execute(
            select(
                ClientUploadLink.id,
                ClientUploadLink.organization_id,
                ClientUploadLink.client_id,
                ClientUploadLink.expires_at,
                ClientUploadLink.revoked_at,
                # Numele cabinetului, ca pagina publică să spună cui îi trimiți.
                # Numele **clientului** nu iese niciodată: un link ajuns din
                # greșeală la altcineva n-are voie să spună cine este clientul.
                Organization.name,
            )
            .join(Client, Client.id == ClientUploadLink.client_id)
            .join(Organization, Organization.id == ClientUploadLink.organization_id)
            .where(
                ClientUploadLink.token_hash == hash_token(token),
                Client.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            return None

        link_id, organization_id, client_id, expires_at, revoked_at, organization_name = row
        if revoked_at is not None or expires_at <= datetime.now(UTC):
            return None

        return LinkTarget(
            link_id=link_id,
            organization_id=organization_id,
            organization_name=organization_name,
            client_id=client_id,
        )

    def note_use(self, link_id: uuid.UUID) -> None:
        """Un document a intrat pe aici. Contorul spune dacă drumul chiar e folosit."""
        link = self.session.get(ClientUploadLink, link_id)
        if link is None:
            return
        link.upload_count += 1
        link.last_used_at = datetime.now(UTC)

    def requests_for(
        self, organization_id: uuid.UUID, reference_month: str
    ) -> dict[uuid.UUID, RequestTrace]:
        """Cui i s-a cerut pentru luna asta, și dacă a trimis ceva pe acolo.

        **Ora** este a ultimei cereri: dacă i s-a cerut de trei ori, întrebarea
        rămâne „de cât timp aștept răspunsul la ultima". **Documentele** se adună
        peste toate cererile lunii — o a doua cerere nu șterge de pe ecran ce
        trimisese omul după prima.

        Linkurile revocate rămân în calcul. O cerere trimisă s-a trimis; faptul
        că i-am închis între timp drumul nu înseamnă că n-am întrebat.
        """
        rows = self.session.execute(
            select(
                ClientUploadLink.client_id,
                ClientUploadLink.created_at,
                ClientUploadLink.upload_count,
            )
            .where(
                ClientUploadLink.organization_id == organization_id,
                ClientUploadLink.reference_month == reference_month,
            )
            .order_by(ClientUploadLink.created_at.desc())
        ).all()

        traces: dict[uuid.UUID, RequestTrace] = {}
        for client_id, created_at, upload_count in rows:
            previous = traces.get(client_id)
            traces[client_id] = RequestTrace(
                # Prima apariție este cea mai recentă — lista vine deja sortată.
                requested_at=previous.requested_at if previous else created_at,
                # Documentele se **adună** peste toate cererile lunii. Dacă am
                # numărat doar ultimul link, o a doua cerere ar fi șters de pe
                # ecran ce trimisese omul după prima — și l-am fi sunat degeaba.
                received_through_link=(previous.received_through_link if previous else 0)
                + upload_count,
            )
        return traces

    def for_client(
        self, organization_id: uuid.UUID, client_id: uuid.UUID
    ) -> list[ClientUploadLink]:
        return list(
            self.session.scalars(
                select(ClientUploadLink)
                .where(
                    ClientUploadLink.organization_id == organization_id,
                    ClientUploadLink.client_id == client_id,
                )
                .order_by(ClientUploadLink.created_at.desc())
            )
        )

    def revoke(self, organization_id: uuid.UUID, link_id: uuid.UUID) -> ClientUploadLink | None:
        """Închide drumul. Nu șterge rândul: urma că a existat rămâne."""
        link = self.session.scalars(
            select(ClientUploadLink).where(
                ClientUploadLink.organization_id == organization_id,
                ClientUploadLink.id == link_id,
            )
        ).first()
        if link is None:
            return None
        if link.revoked_at is None:
            link.revoked_at = datetime.now(UTC)
        return link
