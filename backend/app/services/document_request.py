"""Solicitarea de documente, ca text gata de trimis.

**De ce stă pe server.** Textul spune numele cabinetului, listează ce lipsește și
dă termenul lunii: este conținut de business, nu formatare de ecran. A stat o
vreme în frontend, unde îl folosea butonul „Copiază solicitarea" de pe ecranul
„Documente lipsă". Din momentul în care îl cere și asistentul, două implementări
ar însemna că doi clienți primesc, în aceeași zi, două mesaje diferite de la
același cabinet.

**Ce face și ce nu.** `compose` scrie textul; `send` îl și trimite, prin
providerul de email. Cele două sunt separate fiindcă a compune se face și când
omul vrea doar să copieze, iar a trimite este o acțiune cu efect în afara
aplicației — efectele acelea nu se produc ca efect secundar al unei citiri.

Copierea a rămas și după ce trimiterea a devenit posibilă: un cabinet fără SMTP
configurat trebuie să poată lucra exact ca înainte, iar unul cu SMTP are zile în
care vrea să scrie altceva în mesaj.

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

#: Cine apare în jurnal când mesajul pleacă singur. Un nume, nu un gol: rândul
#: trebuie să spună că a scris aplicația, nu să lase impresia că nu se știe cine.
AUTOMATIC_ACTOR = "Aplicația"

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


def _opening(reference_month: str, previous_sent_on: date | None) -> str:
    """Prima frază. Spune de a câta oară scriem, fiindcă asta schimbă tot.

    **De ce reminderul poartă data mesajului anterior.** „Vă reamintim" este o
    formulare pe care o poate scrie oricine, oricând, despre orice: pe cine chiar
    a trimis documentele îl enervează, iar pe cine a uitat nu-l ajută cu nimic să
    își amintească. Data spune verificabil de când așteptăm, iar clientul care
    crede că a trimis deja se poate duce să caute în ziua aceea.
    """
    month = month_in_words(reference_month)
    if previous_sent_on is None:
        return (
            f"Pentru evidența contabilă a lunii {month} mai avem nevoie de următoarele documente:"
        )
    return (
        f"V-am scris pe {previous_sent_on.strftime('%d.%m.%Y')} despre documentele "
        f"pentru luna {month}. Deocamdată nu ne-au ajuns toate, așa că vă "
        "reamintim ce mai așteptăm:"
    )


def build_request_message(
    *,
    client_name: str,
    reference_month: str,
    deadline: date,
    missing: Sequence[ChecklistEntry],
    organization_name: str,
    upload_url: str | None = None,
    upload_expires_on: date | None = None,
    previous_sent_on: date | None = None,
) -> str:
    del client_name  # se adresează firmei, nu o numește: mesajul îi este trimis ei
    return "\n".join(
        [
            "Bună ziua,",
            "",
            _opening(reference_month, previous_sent_on),
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
        actor: User | None,
        ip: str | None = None,
        previous_sent_on: date | None = None,
        missing: Sequence[ChecklistEntry] | None = None,
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
        # **Calculate o dată, când sunt cerute pentru mai mulți clienți deodată.**
        # `missing()` se uită la toți clienții cabinetului; chemat o dată per
        # destinatar, o rulare de remindere l-ar fi rulat de douăzeci de ori peste
        # aceleași două sute de clienți. Cronul are un timp maxim, iar munca
        # începută și abandonată este cea mai proastă variantă.
        if missing is None:
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
            # Nul când scrie planificatorul: „cine a deschis drumul" nu are voie
            # să numească un om care dormea la ora aceea.
            created_by_id=actor.id if actor else None,
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
            user_id=actor.id if actor else None,
            user_name=actor.full_name if actor else AUTOMATIC_ACTOR,
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
                previous_sent_on=previous_sent_on,
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

    def whatsapp_number(self, client: Client) -> str | None:
        """Primul număr de WhatsApp de pe fișă, dacă există vreunul.

        **De ce îl întoarce ruta care compune.** Textul și drumul pleacă
        împreună; numărul este al treilea lucru de care are nevoie ecranul ca să
        poată oferi „trimite pe WhatsApp" fără încă o cerere. Fără el, butonul ar
        fi apărut abia după ce se încarcă și contactele — adică uneori după ce
        omul a apăsat deja altceva.

        Se întoarce **așa cum este scris pe fișă**. Transformarea în forma pe care
        o cere `wa.me` este o chestiune de link, nu de date, și se face acolo unde
        se construiește linkul.
        """
        return self.session.scalars(
            select(Contact.whatsapp_number)
            .where(
                Contact.client_id == client.id,
                Contact.whatsapp_number.is_not(None),
                Contact.whatsapp_number != "",
                Contact.deleted_at.is_(None),
            )
            .order_by(Contact.created_at)
        ).first()

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
