"""Scrierea clienților și a contactelor lor.

**De ce există abia acum.** CRM-ul a fost de la început numai de citire: drumul de
scriere al aplicației sunt documentele. Auditul de producție a arătat consecința —
un cabinet nou nu putea adăuga **niciun** client, deci nu putea lega niciun dosar
din OneDrive și niciun email nu putea fi atribuit. Comanda `add-client` a
deblocat prima folosire; aici este ecranul propriu-zis.

**Nu există ștergere.** Un client cu documente este istorie contabilă. Ce se cere
de fapt este „nu mai lucrez cu el", iar asta este o schimbare de stare
(`INACTIVE`), care lasă documentele, perioadele și jurnalul neatinse. O rută de
ștergere ar fi arătat ca soluția evidentă exact în momentul greșit.

**Două verificări care există pentru că altfel ceva se rupe tăcut:**

- **CUI unic pe formă normalizată.** `RO14399840` și `14399840` sunt același cod
  (`client_matching.normalize_tax_id`). Indexul unic din migrare compară textul
  brut, deci le-ar accepta pe amândouă — iar apoi identificarea automată a
  clientului ar găsi doi candidați și n-ar mai atribui niciun document.
- **Email de contact unic între clienți.** Preluarea din email atribuie
  atașamentul după adresa expeditorului, iar `MailSyncService` **scoate din hartă**
  adresele ambigue. Două contacte cu aceeași adresă la clienți diferiți nu produc
  nicio eroare: pur și simplu documentele nu mai ajung la nimeni.

Cifra de control a CUI-ului **nu** este impusă. Există (`is_valid_tax_id`) și
servește la cât de sigur este un cod *citit de pe un document*; la introducerea de
mână ar fi o politică, nu o verificare — un cabinet poate avea legitim un client
cu cod de TVA din altă țară.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode, NotFoundError, ValidationError
from app.domain.enums import ClientStatus
from app.models.client import Client, ClientNote, Contact
from app.models.user import User
from app.schemas.client import MAX_NOTE_LENGTH
from app.services.audit import AuditService
from app.services.client_matching import normalize_tax_id

#: Câmpurile clientului pe care le poate schimba cineva din interfață, în ordinea
#: în care apar în formular. `tags` lipsește deliberat: etichetele au propriul lor
#: ecran și propria semantică (many-to-many), iar amestecul lor aici ar fi făcut
#: din `update` o rută care schimbă două lucruri diferite.
CLIENT_FIELDS = (
    "name",
    "tax_id",
    "registration_number",
    "address",
    "status",
    "assigned_accountant_id",
)

CONTACT_FIELDS = (
    "full_name",
    "role",
    "email",
    "phone",
    "whatsapp_number",
    "is_primary",
    "is_active",
)


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Cine face schimbarea și de unde. Ajunge întreg în jurnalul de audit."""

    user: User
    ip: str | None = None
    user_agent: str | None = None


class ClientService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ── Clienți ─────────────────────────────────────────────────────────────

    def create(
        self, organization_id: uuid.UUID, values: dict[str, Any], actor: ActorContext
    ) -> Client:
        name = _required_text(values.get("name"), "name", "Denumirea")
        tax_id = _optional_text(values.get("tax_id"))
        self._assert_tax_id_is_free(organization_id, tax_id, exclude_id=None)
        accountant_id = self._checked_accountant(
            organization_id, values.get("assigned_accountant_id")
        )

        client = Client(
            organization_id=organization_id,
            name=name,
            tax_id=tax_id,
            registration_number=_optional_text(values.get("registration_number")),
            address=_optional_text(values.get("address")) or "",
            status=values.get("status") or ClientStatus.ACTIVE,
            assigned_accountant_id=accountant_id,
        )
        self.session.add(client)
        self.session.flush()

        self.audit.record(
            organization_id=organization_id,
            action="CLIENT_CREATED",
            entity_type="Client",
            entity_id=str(client.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            detail=client.name,
            new_value=_snapshot(client, CLIENT_FIELDS),
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return client

    def update(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        values: dict[str, Any],
        actor: ActorContext,
    ) -> Client:
        client = self._client(organization_id, client_id)
        before = _snapshot(client, CLIENT_FIELDS)

        if "name" in values:
            client.name = _required_text(values["name"], "name", "Denumirea")
        if "tax_id" in values:
            tax_id = _optional_text(values["tax_id"])
            self._assert_tax_id_is_free(organization_id, tax_id, exclude_id=client.id)
            client.tax_id = tax_id
        if "registration_number" in values:
            client.registration_number = _optional_text(values["registration_number"])
        if "address" in values:
            client.address = _optional_text(values["address"]) or ""
        if "status" in values and values["status"] is not None:
            client.status = values["status"]
        if "assigned_accountant_id" in values:
            client.assigned_accountant_id = self._checked_accountant(
                organization_id, values["assigned_accountant_id"]
            )

        self.session.flush()
        after = _snapshot(client, CLIENT_FIELDS)
        if after != before:
            self.audit.record(
                organization_id=organization_id,
                action="CLIENT_UPDATED",
                entity_type="Client",
                entity_id=str(client.id),
                user_id=actor.user.id,
                user_name=actor.user.full_name,
                detail=client.name,
                old_value=before,
                new_value=after,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        return client

    # ── Contacte ────────────────────────────────────────────────────────────

    def add_contact(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        values: dict[str, Any],
        actor: ActorContext,
    ) -> Contact:
        client = self._client(organization_id, client_id)
        email = _normalized_email(values.get("email"))
        self._assert_email_is_free(organization_id, email, exclude_id=None)

        contact = Contact(
            client_id=client.id,
            full_name=_required_text(values.get("full_name"), "fullName", "Numele"),
            role=_optional_text(values.get("role")) or "",
            email=email,
            phone=_optional_text(values.get("phone")),
            whatsapp_number=_optional_text(values.get("whatsapp_number")),
            is_primary=bool(values.get("is_primary", False)),
            is_active=bool(values.get("is_active", True)),
        )
        self.session.add(contact)
        self.session.flush()
        if contact.is_primary:
            self._demote_other_primaries(client.id, contact.id)

        self.audit.record(
            organization_id=organization_id,
            action="CONTACT_CREATED",
            entity_type="Contact",
            entity_id=str(contact.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            detail=f"{contact.full_name} ({client.name})",
            new_value=_snapshot(contact, CONTACT_FIELDS),
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return contact

    def add_note(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        values: dict[str, Any],
        actor: ActorContext,
    ) -> ClientNote:
        """Scrie o notă internă pe client.

        **Autorul se păstrează ca text**, nu doar ca legătură: cine a scris o
        notă nu trebuie să dispară odată cu contul lui. Modelul avea deja
        `author_name` tocmai pentru asta; până acum nu avea cine să-l scrie.

        Nu există modificare și nu există ștergere, deliberat. O notă este o
        consemnare — „am vorbit cu clientul, aduce actele vineri" —, iar o
        consemnare care se poate rescrie nu mai este o consemnare. Ce se face
        când cineva greșește: se scrie următoarea.
        """
        client = self._client(organization_id, client_id)
        body = _required_text(values.get("body"), "body", "Textul notei")
        if len(body) > MAX_NOTE_LENGTH:
            raise ValidationError(
                f"Nota depășește {MAX_NOTE_LENGTH} de caractere.", {"body": ["Text prea lung."]}
            )

        note = ClientNote(
            client_id=client.id,
            author_id=actor.user.id,
            author_name=actor.user.full_name,
            body=body,
        )
        self.session.add(note)
        self.session.flush()

        self.audit.record(
            organization_id=organization_id,
            action="CLIENT_NOTE_ADDED",
            entity_type="Client",
            entity_id=str(client.id),
            user_id=actor.user.id,
            user_name=actor.user.full_name,
            # Auditul spune **că** s-a scris o notă, nu ce scrie în ea: conținutul
            # trăiește într-un singur loc, iar jurnalul nu este o a doua copie.
            detail=f"Notă pe {client.name}",
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
        return note

    def update_contact(
        self,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        contact_id: uuid.UUID,
        values: dict[str, Any],
        actor: ActorContext,
    ) -> Contact:
        client = self._client(organization_id, client_id)
        contact = self.session.scalars(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.client_id == client.id,
                Contact.deleted_at.is_(None),
            )
        ).first()
        if contact is None:
            raise NotFoundError("Contact", contact_id)

        before = _snapshot(contact, CONTACT_FIELDS)

        if "full_name" in values:
            contact.full_name = _required_text(values["full_name"], "fullName", "Numele")
        if "role" in values:
            contact.role = _optional_text(values["role"]) or ""
        if "email" in values:
            email = _normalized_email(values["email"])
            self._assert_email_is_free(organization_id, email, exclude_id=contact.id)
            contact.email = email
        if "phone" in values:
            contact.phone = _optional_text(values["phone"])
        if "whatsapp_number" in values:
            contact.whatsapp_number = _optional_text(values["whatsapp_number"])
        if "is_active" in values and values["is_active"] is not None:
            contact.is_active = bool(values["is_active"])
        if values.get("is_primary"):
            contact.is_primary = True

        self.session.flush()
        if contact.is_primary:
            self._demote_other_primaries(client.id, contact.id)

        after = _snapshot(contact, CONTACT_FIELDS)
        if after != before:
            self.audit.record(
                organization_id=organization_id,
                action="CONTACT_UPDATED",
                entity_type="Contact",
                entity_id=str(contact.id),
                user_id=actor.user.id,
                user_name=actor.user.full_name,
                detail=f"{contact.full_name} ({client.name})",
                old_value=before,
                new_value=after,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        return contact

    # ── Verificări ──────────────────────────────────────────────────────────

    def _client(self, organization_id: uuid.UUID, client_id: uuid.UUID) -> Client:
        client = self.session.scalars(
            select(Client).where(
                Client.id == client_id,
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
            )
        ).first()
        if client is None:
            # Un client din altă organizație dă tot NOT_FOUND, nu FORBIDDEN:
            # altfel răspunsul confirmă că id-ul există undeva.
            raise NotFoundError("Client", client_id)
        return client

    def _assert_tax_id_is_free(
        self, organization_id: uuid.UUID, tax_id: str | None, *, exclude_id: uuid.UUID | None
    ) -> None:
        if not tax_id:
            return
        wanted = normalize_tax_id(tax_id)
        if not wanted:
            return
        for other in self.session.scalars(
            select(Client).where(
                Client.organization_id == organization_id,
                Client.tax_id.is_not(None),
                Client.deleted_at.is_(None),
            )
        ):
            if other.id == exclude_id:
                continue
            if normalize_tax_id(other.tax_id) == wanted:
                raise AppError(
                    ErrorCode.CONFLICT,
                    f"CUI-ul {tax_id} aparține deja clientului {other.name}.",
                    details={"taxId": ["CUI folosit deja."]},
                )

    def _assert_email_is_free(
        self, organization_id: uuid.UUID, email: str | None, *, exclude_id: uuid.UUID | None
    ) -> None:
        """Aceeași adresă la doi clienți nu dă nicio eroare — doar oprește preluarea.

        `MailSyncService` scoate din hartă adresele care duc la mai mulți clienți,
        pentru că nu are cum să aleagă. Rezultatul ar fi documente care nu mai
        ajung la nimeni, fără ca nimic să semnaleze de ce.
        """
        if not email:
            return
        existing = self.session.scalars(
            select(Contact)
            .join(Client, Contact.client_id == Client.id)
            .where(
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
                Contact.deleted_at.is_(None),
                Contact.email == email,
            )
        ).first()
        if existing is not None and existing.id != exclude_id:
            raise AppError(
                ErrorCode.CONFLICT,
                f"Adresa {email} este deja contactul clientului {existing.client.name}. "
                "Două contacte cu aceeași adresă opresc atribuirea automată a emailurilor.",
                details={"email": ["Adresă folosită deja."]},
            )

    def _checked_accountant(
        self, organization_id: uuid.UUID, accountant_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        """Contabilul atribuit trebuie să fie din același cabinet."""
        if accountant_id is None:
            return None
        user = self.session.scalars(
            select(User).where(
                User.id == accountant_id,
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
            )
        ).first()
        if user is None:
            raise ValidationError(
                "Contabilul atribuit nu există.",
                {"assignedAccountantId": ["Utilizator inexistent."]},
            )
        return user.id

    def _demote_other_primaries(self, client_id: uuid.UUID, keep: uuid.UUID) -> None:
        """Un singur contact principal per client.

        Se face prin coborârea celorlalte, nu prin refuzul celui nou: cine bifează
        „principal" pe altcineva vrea să schimbe, nu să primească o eroare.
        """
        for other in self.session.scalars(
            select(Contact).where(
                Contact.client_id == client_id,
                Contact.id != keep,
                Contact.is_primary.is_(True),
            )
        ):
            other.is_primary = False
        self.session.flush()


# ── Curățarea intrărilor ─────────────────────────────────────────────────────


def _required_text(raw: Any, field: str, label: str) -> str:
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text:
        raise ValidationError(f"{label} este obligatorie.", {field: ["Câmp obligatoriu."]})
    return text


def _optional_text(raw: Any) -> str | None:
    """Un câmp gol înseamnă „nu se știe", deci `NULL`, nu șirul vid.

    Distincția contează la CUI: `''` ar intra în indexul unic parțial și ar face
    ca al doilea client fără CUI să nu poată fi salvat.
    """
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def _normalized_email(raw: Any) -> str | None:
    """Litere mici, ca potrivirea expeditorului să funcționeze.

    `MailSyncService` compară adresa mesajului în litere mici. Un contact salvat
    cu majuscule pur și simplu nu s-ar potrivi niciodată.
    """
    email = _optional_text(raw)
    return email.lower() if email else None


def _snapshot(entity: Client | Contact, fields: tuple[str, ...]) -> dict[str, Any]:
    """Valorile urmărite, în forma în care intră în jurnalul de audit (JSON)."""
    return {name: _jsonable(getattr(entity, name)) for name in fields}


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, ClientStatus):
        return value.value
    return value


__all__ = ["CLIENT_FIELDS", "CONTACT_FIELDS", "ActorContext", "ClientService"]
