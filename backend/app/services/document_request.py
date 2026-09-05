"""Solicitarea de documente, ca text gata de trimis.

**De ce stă pe server.** Textul spune numele cabinetului, listează ce lipsește și
dă termenul lunii: este conținut de business, nu formatare de ecran. A stat o
vreme în frontend, unde îl folosea butonul „Copiază solicitarea" de pe ecranul
„Documente lipsă". Din momentul în care îl cere și asistentul, două implementări
ar însemna că doi clienți primesc, în aceeași zi, două mesaje diferite de la
același cabinet.

**Ce nu face.** Nu trimite. Trimiterea cere un provider de email sau WhatsApp și
rămâne în Faza 2. Până atunci, textul iese gata scris și pleacă din clientul de
email al contabilului, cu semnătura lui — ceea ce este, până la Faza 2, chiar mai
onest: niciun mesaj nu pleacă în numele cabinetului fără ca cineva să îl fi citit.

**De ce poartă și linkul de trimitere (M14).** O listă de ce lipsește îi spune
clientului *ce* să caute, dar îl lasă singur cu *cum* trimite: scanează, atașează,
se lovește de limita de mărime a emailului, amână. Cererea și drumul pe care
sosește răspunsul pleacă împreună, într-un singur mesaj — altfel omul primește
sarcina fără unealtă.

Blocul este opțional pentru că nu oricine îl poate compune: linkul se **deschide**,
iar deschiderea cere `documents:write`. Cine doar citește primește tot textul, mai
puțin rândul pe care n-are dreptul să-l creeze.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.domain.periods import ChecklistEntry, filing_deadline
from app.models.client import Client, Contact
from app.models.organization import Organization
from app.models.user import User
from app.repositories.client import ClientRepository
from app.services.audit import AuditService
from app.services.mail import EmailMessage, EmailSender
from app.services.period_service import PeriodService
from app.services.upload_links import UploadLinkService

#: Numele lunilor, la genitiv-dativ cum cere fraza „pentru luna …".
MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)


def month_in_words(reference_month: str) -> str:
    """„2026-08" → „august 2026". Un client nu citește luni numerotate."""
    year, month = reference_month.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def _line(entry: ChecklistEntry) -> str:
    """Câte bucăți mai lipsesc dintr-un tip, nu doar că lipsește.

    „Facturi de achiziție" nu spune nimic unui client care crede că le-a trimis;
    „mai așteptăm 2 (am primit 3 din 5)" spune exact ce are de căutat.
    """
    left = entry.expected_min_count - entry.received_count
    if entry.received_count > 0:
        seen = f"{entry.received_count} din {entry.expected_min_count}"
        detail = f" — mai așteptăm {left} (am primit {seen})"
    else:
        piece = "bucată" if entry.expected_min_count == 1 else "bucăți"
        detail = f" — {entry.expected_min_count} {piece}"
    return f"• {entry.document_type_label}{detail}"


def _upload_block(url: str, expires_on: date | None) -> list[str]:
    """Cum se trimite, imediat după ce s-a spus ce și până când.

    Data expirării se scrie în mesaj pentru că altfel n-o știe nimeni: clientul
    care deschide linkul peste patru luni nu află de ce nu mai merge, iar
    contabilul care i l-a trimis nu-și amintește când l-a deschis.
    """
    lines = [
        "",
        "Cel mai simplu este să le încărcați direct aici, fără cont și fără parolă:",
        url,
    ]
    if expires_on is not None:
        lines.append(f"Linkul este valabil până la {expires_on.strftime('%d.%m.%Y')}.")
    return lines


def build_request_message(
    *,
    client_name: str,
    reference_month: str,
    deadline: date,
    missing: Sequence[ChecklistEntry],
    organization_name: str,
    upload_url: str | None = None,
    upload_expires_on: date | None = None,
) -> str:
    del client_name  # se adresează firmei, nu o numește: mesajul îi este trimis ei
    return "\n".join(
        [
            "Bună ziua,",
            "",
            f"Pentru evidența contabilă a lunii {month_in_words(reference_month)} "
            "mai avem nevoie de următoarele documente:",
            "",
            *[_line(entry) for entry in missing],
            "",
            f"Vă rugăm să ni le transmiteți până la {deadline.strftime('%d.%m.%Y')}, "
            "ca declarațiile să poată fi depuse la timp.",
            *(_upload_block(upload_url, upload_expires_on) if upload_url else []),
            "",
            "Vă mulțumim,",
            organization_name,
        ]
    )


@dataclass(frozen=True, slots=True)
class ComposedRequest:
    """Cererea compusă, plus ce trebuie ca ea să și plece."""

    message: str
    upload_url: str
    upload_expires_at: datetime
    client: Client
    link_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SentRequest:
    sent_to: str
    sent_at: datetime
    upload_url: str
    upload_expires_at: datetime


class DocumentRequestService:
    """Compune și trimite solicitarea de documente.

    **De ce serviciu și nu două rute cu același corp.** Ruta care copiază, ruta
    care trimite unui client și cea care trimite mai multora trebuie să producă
    **exact** același mesaj. Trei implementări ar fi însemnat că trei clienți
    primesc, în aceeași zi, trei scrisori diferite de la același cabinet — iar
    diferența s-ar vedea abia când unul dintre ei o citește cu voce tare la
    telefon.
    """

    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id
        self.audit = AuditService(session)
        self.links = UploadLinkService(session)

    def compose(
        self,
        client_id: uuid.UUID,
        reference_month: str,
        *,
        actor: User,
        ip: str | None = None,
    ) -> ComposedRequest:
        """Deschide un drum de trimitere și scrie mesajul.

        **De ce un link nou de fiecare dată.** Tokenul unui link existent nu se
        mai poate afla: în bază stă doar SHA-256 al lui. Refolosirea și hash-ul
        se exclud, iar hash-ul este proprietatea care contează.
        """
        client = ClientRepository(self.session).get(self.organization_id, client_id)
        if client is None:
            raise NotFoundError("Client", client_id)

        # **Aceeași sursă ca raportul**, nu `list_periods`.
        #
        # `list_periods` nu inventează o lună fără documente și fără rând, deci
        # nu-l vede pe clientul care n-a trimis absolut nimic. Raportul
        # „Documente lipsă" îl vede — este chiar cel căruia îi lipsește tot — și
        # îi arată butonul de cerere. Compunerea citea din cealaltă listă, deci
        # butonul răspundea „clientul nu are documente lipsă" exact pe rândurile
        # unde lipsea totul. Găsit apăsând butonul, nu citind codul.
        gaps = [
            entry
            for view, entry in PeriodService(self.session).missing(
                self.organization_id, reference_month
            )
            if view.client_id == client_id
        ]
        missing = gaps[0] if gaps else []
        if not missing:
            # Înainte de a deschide linkul: un drum public deschis pentru un mesaj
            # care oricum nu pleacă ar rămâne deschis degeaba 45 de zile.
            raise ValidationError(
                "Clientul nu are documente lipsă în luna cerută.",
                {"referenceMonth": ["Nimic de cerut."]},
            )

        issued = self.links.issue(
            self.organization_id,
            client_id,
            created_by_id=actor.id,
            # Luna leagă linkul de cerere. Fără ea, rândul spune doar că s-a
            # deschis un drum; cu ea, spune că **i s-a cerut**, pentru ce lună și
            # când — iar raportul poate arăta cine încă n-a fost întrebat.
            reference_month=reference_month,
        )
        self.audit.record(
            organization_id=self.organization_id,
            action="UPLOAD_LINK_ISSUED",
            entity_type="ClientUploadLink",
            entity_id=str(issued.id),
            user_id=actor.id,
            user_name=actor.full_name,
            # Clientul și luna, nu tokenul: jurnalul nu ține chei (§33).
            detail=f"{client.name} · solicitare {reference_month}",
            ip=ip,
        )

        organization = self.session.get(Organization, self.organization_id)
        url = f"{settings.public_base_url}/incarca/{issued.token}"
        return ComposedRequest(
            message=build_request_message(
                client_name=client.name,
                reference_month=reference_month,
                deadline=filing_deadline(reference_month, day=settings.filing_deadline_day),
                missing=missing,
                organization_name=(
                    organization.name if organization else "Cabinetul dumneavoastră"
                ),
                upload_url=url,
                upload_expires_on=issued.expires_at.date(),
            ),
            upload_url=url,
            upload_expires_at=issued.expires_at,
            client=client,
            link_id=issued.id,
        )

    def recipient(self, client: Client, chosen: str | None = None) -> str:
        """Cui îi scriem, dacă nu s-a spus explicit.

        Primul contact care are o adresă, în ordinea în care sunt scrise pe fișă.
        Nu „cel principal": modelul nu are noțiunea, iar a inventa una aici ar
        însemna că ecranul nu poate arăta dinainte cui va pleca mesajul.
        """
        if chosen:
            return chosen

        address = self.session.scalars(
            select(Contact.email)
            .where(
                Contact.client_id == client.id,
                Contact.email.is_not(None),
                Contact.email != "",
                Contact.deleted_at.is_(None),
            )
            .order_by(Contact.created_at)
        ).first()
        if not address:
            raise ValidationError(
                "Clientul nu are nicio adresă de email.",
                {"to": ["Adaugă un contact cu email sau scrie adresa aici."]},
            )
        return address

    def send(
        self,
        client_id: uuid.UUID,
        reference_month: str,
        *,
        actor: User,
        sender: EmailSender,
        to: str | None = None,
        ip: str | None = None,
    ) -> SentRequest:
        """Compune și trimite.

        **Ordinea contează.** Se trimite întâi, se scrie „trimis" după. Invers, un
        server de mail căzut ar fi lăsat pe ecran „Trimis" pentru un mesaj care
        n-a plecat niciodată — exact minciuna pe care `notified_at` există ca s-o
        evite.

        Dacă trimiterea eșuează, excepția anulează tranzacția, deci **și linkul**.
        Așa trebuie: tokenul se vede o singură dată, în răspunsul care nu mai
        vine, deci un link rămas ar fi un drum pe care nu-l știe nimeni.
        """
        composed = self.compose(client_id, reference_month, actor=actor, ip=ip)
        address = self.recipient(composed.client, to)

        sender.send(
            EmailMessage(
                to=address,
                subject=f"Documente necesare pentru {month_in_words(reference_month)}",
                body=composed.message,
            )
        )

        self.links.mark_notified(composed.link_id, to=address)
        self.audit.record(
            organization_id=self.organization_id,
            action="DOCUMENT_REQUEST_SENT",
            entity_type="ClientUploadLink",
            entity_id=str(composed.link_id),
            user_id=actor.id,
            user_name=actor.full_name,
            # Cui și pentru ce lună. Nu textul: jurnalul spune cine a făcut ce, nu
            # ce scria în mesaj (§33).
            detail=f"{composed.client.name} · {address} · {reference_month}",
            ip=ip,
        )

        return SentRequest(
            sent_to=address,
            sent_at=datetime.now(UTC),
            upload_url=composed.upload_url,
            upload_expires_at=composed.upload_expires_at,
        )
