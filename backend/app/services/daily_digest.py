"""Rezumatul zilei, trimis cabinetului.

**Golul pe care îl umple.** Aplicația nu face nimic dacă nu o deschide cineva.
Știe că trei clienți n-au răspuns de o săptămână și că un termen e peste două
zile, dar așteaptă să fie întrebată. Un instrument pe care trebuie să-ți amintești
să-l consulți este un instrument consultat neregulat.

**Către cabinet, nu către clienți.** Un mesaj trimis automat în numele
cabinetului, unui client, este o decizie de altă natură — se ia o dată, explicit,
și nu de aplicație. Aici destinatarii sunt colegii, iar conținutul este ce văd
oricum pe panou.

**Nu se trimite când nu e nimic de spus.** Un rezumat care scrie „nimic" în
fiecare dimineață antrenează pe toată lumea să nu-l mai deschidă — inclusiv în
ziua în care are ceva înăuntru. Tăcerea este ea însăși informația.

**Cine îl primește.** Utilizatorii activi cu `documents:write`: cei care fac
munca. Un vizitator nu are ce face cu lista, iar un rezumat trimis cuiva care nu
poate acționa este zgomot cu semnătura cabinetului pe el.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.enums import DocumentStatus
from app.domain.permissions import Permission
from app.models.organization import Organization
from app.models.user import Permission as PermissionRow
from app.models.user import Role, User
from app.repositories.document import DocumentRepository
from app.services.mail import EmailError, EmailMessage, EmailSender
from app.services.obligations import ObligationService
from app.services.period_service import PeriodService
from app.services.upload_links import UploadLinkService

logger = get_logger(__name__)

#: Cât în față se uită rezumatul după termene. O săptămână de lucru.
HORIZON_DAYS = 7

#: De la câte zile fără răspuns un client devine ceva de urmărit. Aceeași valoare
#: ca pe ecranul „Documente lipsă": două numere diferite pentru aceeași noțiune
#: ar face rezumatul să contrazică ecranul.
SILENT_AFTER_DAYS = 3


@dataclass(frozen=True, slots=True)
class Digest:
    """Ce are cabinetul de făcut azi, în cifre."""

    overdue: int
    due_soon: int
    to_review: int
    unmatched: int
    not_asked: int
    silent: int

    @property
    def is_empty(self) -> bool:
        """Nimic de spus. Rezumatul nu pleacă."""
        return not any(
            (
                self.overdue,
                self.due_soon,
                self.to_review,
                self.unmatched,
                self.not_asked,
                self.silent,
            )
        )


#: Ce se scrie pentru fiecare cifră, **în ordinea costului de a lăsa lucrurile
#: nefăcute**. Restanțele primele: sunt singurele care costă bani, iar la client,
#: nu la cabinet. O ordonare după cât de ușor se rezolvă ar fi început cu
#: documentele de verificat, care pot aștepta o zi.
_LINES: tuple[tuple[str, str, str, str], ...] = (
    ("overdue", "declarație nedepusă", "declarații nedepuse", " după termen"),
    ("due_soon", "termen", "termene", f" în următoarele {HORIZON_DAYS} zile"),
    ("unmatched", "document fără client", "documente fără client", ""),
    ("to_review", "document de verificat", "documente de verificat", ""),
    ("not_asked", "client neîntrebat", "clienți neîntrebați", ""),
    (
        "silent",
        "client nu a răspuns",
        "clienți nu au răspuns",
        f" de peste {SILENT_AFTER_DAYS} zile",
    ),
)


def compose(digest: Digest, *, organization_name: str, today: date) -> str:
    """Textul rezumatului.

    Doar cifrele care nu sunt zero: un rând care scrie „0 documente de verificat"
    ocupă un rând și nu spune nimic, iar șase asemenea rânduri fac mesajul de
    necitit exact în ziua în care unul dintre ele contează.
    """
    lines = ["Bună dimineața,", "", f"Pentru {today.strftime('%d.%m.%Y')}:", ""]
    for field_name, one, many, suffix in _LINES:
        count = getattr(digest, field_name)
        if count:
            lines.append(f"• {count} {one if count == 1 else many}{suffix}")
    lines += ["", organization_name]
    return "\n".join(lines)


class DailyDigestService:
    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def build(self, today: date) -> Digest:
        """Cifrele, citite din aceleași servicii ca ecranele.

        Nicio interogare proprie: două căi de calcul ar fi ajuns, într-o zi, la
        două numere diferite pentru aceeași întrebare — iar unul dintre ele ar fi
        plecat pe email, unde nu se mai poate corecta.
        """
        obligations = ObligationService(self.session, self.organization_id).upcoming(
            since=today - timedelta(days=120), until=today + timedelta(days=HORIZON_DAYS)
        )
        overdue = sum(1 for row in obligations if row.is_overdue(today))
        due_soon = sum(1 for row in obligations if not row.is_filed() and not row.is_overdue(today))

        periods = PeriodService(self.session)
        month = periods.latest_active_month(self.organization_id)
        not_asked, silent = self._collection(month, today)

        # Aceeași numărătoare ca insignele din meniu, prin același repository.
        counts = DocumentRepository(self.session).count_by_status(self.organization_id)
        return Digest(
            overdue=overdue,
            due_soon=due_soon,
            to_review=counts.get(DocumentStatus.REVIEW_REQUIRED, 0),
            unmatched=counts.get(DocumentStatus.UNMATCHED, 0),
            not_asked=not_asked,
            silent=silent,
        )

    def _collection(self, month: str | None, today: date) -> tuple[int, int]:
        """Cui nu i s-a cerut și cine nu a răspuns, pe luna în lucru."""
        if month is None:
            return 0, 0
        entries = PeriodService(self.session).missing(self.organization_id, month)
        if not entries:
            return 0, 0

        traces = UploadLinkService(self.session).requests_for(self.organization_id, month)
        not_asked = 0
        silent = 0
        for view, _gaps in entries:
            trace = traces.get(view.client_id)
            if trace is None:
                not_asked += 1
            elif trace.received_through_link == 0 and (
                today - trace.requested_at.date()
            ) >= timedelta(days=SILENT_AFTER_DAYS):
                silent += 1
        return not_asked, silent

    def recipients(self) -> list[User]:
        """Cine face munca, nu cine are voie să se uite."""
        return list(
            self.session.scalars(
                select(User)
                .join(User.roles)
                .join(Role.permissions)
                .where(
                    User.organization_id == self.organization_id,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    PermissionRow.code == Permission.DOCUMENTS_WRITE.value,
                )
                .distinct()
            )
        )

    def send(self, sender: EmailSender, *, today: date) -> int:
        """Compune și trimite. Întoarce câte mesaje au plecat.

        Un destinatar care eșuează nu-i oprește pe ceilalți: un server de mail
        care refuză o adresă nu este un motiv ca restul cabinetului să nu afle ce
        are de făcut.
        """
        digest = self.build(today)
        if digest.is_empty:
            logger.info("digest_skipped", organization_id=str(self.organization_id))
            return 0

        organization = self.session.get(Organization, self.organization_id)
        body = compose(
            digest,
            organization_name=organization.name if organization else "Cabinetul dumneavoastră",
            today=today,
        )
        subject = f"Ce aveți de făcut azi · {today.strftime('%d.%m.%Y')}"

        sent = 0
        for user in self.recipients():
            try:
                sender.send(EmailMessage(to=user.email, subject=subject, body=body))
                sent += 1
            except EmailError:
                # Adresa, nu conținutul (§52). Restul cabinetului primește oricum.
                logger.error("digest_send_failed", to=user.email)
        return sent


__all__ = ["HORIZON_DAYS", "SILENT_AFTER_DAYS", "DailyDigestService", "Digest", "compose"]
