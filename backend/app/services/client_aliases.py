"""Sistemul învață de la cine vin documentele (§8).

**Ce rezolvă.** Un extras de cont nu are CUI. O poză de bon nu are text. OCR-ul
citește uneori greșit. Documentele astea ajung `UNMATCHED`, un om alege clientul,
și luna viitoare se repetă exact la fel — pentru că nimic nu reține decizia.

**Cum învață.** La fiecare atribuire făcută de un om, adresa de la care a sosit
documentul este legată de clientul ales. Data viitoare, un document venit de la
aceeași adresă se atribuie singur.

**Ce nu învață, deliberat:**

- **Nu învață din propriile potriviri.** Doar o decizie umană scrie un alias.
  Altfel prima potrivire greșită s-ar transforma într-o regulă, iar sistemul și-ar
  amplifica erorile în loc să le corecteze.
- **Nu învață din codurile fiscale de pe document.** Pe o factură de intrare apar
  două: al furnizorului și al clientului nostru. Cel al furnizorului aparține unui
  terț care vinde la zeci de firme — legat de un client, ar trimite toate facturile
  acelui furnizor la clientul greșit. Iar care dintre cele două este al clientului
  nu se știe cât timp tipul documentului nu este stabilit, ceea ce la `UNMATCHED`
  este exact cazul.
- **Nu învață de la o adresă a cabinetului.** Documentele urcate manual de un
  coleg nu au expeditor extern; a lega adresa colegului de un client ar trimite
  acolo tot ce urcă el.

**Se poate desface.** Un alias greșit ar misruta tăcut, lună de lună. Se vede pe
fișa clientului, se șterge de acolo, iar o atribuire nouă de la aceeași adresă îl
mută: ultima decizie a unui om câștigă.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.alias import AliasKind, ClientAlias
from app.models.client import Client
from app.models.document import DocumentIntake


def normalize_sender(raw: str | None) -> str:
    """Adresele se compară fără majuscule și fără spații la capete.

    `Contabilitate@Alfa.RO` și `contabilitate@alfa.ro ` sunt aceeași adresă;
    tratate diferit, ar produce două aliasuri pentru același expeditor, iar
    potrivirea ar depinde de cum a scris cineva adresa într-un client de email.
    """
    return (raw or "").strip().lower()


@dataclass(frozen=True, slots=True)
class AliasMatch:
    client_id: uuid.UUID
    client_name: str
    #: Adresa care a produs potrivirea. Ajunge în audit, ca operatorul să vadă
    #: **de ce** a fost atribuit documentul, nu doar că a fost.
    sender: str


class ClientAliasService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Învățarea ───────────────────────────────────────────────────────────

    def learn_from_assignment(
        self,
        organization_id: uuid.UUID,
        *,
        document_id: uuid.UUID,
        client_id: uuid.UUID,
        actor_id: uuid.UUID | None,
    ) -> str | None:
        """Reține de la ce adresă a venit documentul pe care tocmai l-a atribuit un om.

        Întoarce adresa învățată, sau `None` dacă nu era nimic de învățat —
        documentul a fost urcat manual, sau expeditorul e deja legat de același
        client. Apelantul o pune în audit: învățarea schimbă comportamentul
        viitor, deci nu are voie să fie tăcută.
        """
        sender = self._sender_of(organization_id, document_id)
        if not sender:
            return None

        existing = self.session.scalars(
            select(ClientAlias).where(
                ClientAlias.organization_id == organization_id,
                ClientAlias.kind == AliasKind.SENDER,
                ClientAlias.value == sender,
            )
        ).first()

        if existing is not None:
            if existing.client_id == client_id:
                return None
            # Ultima decizie a unui om câștigă. Contorul repornește: potrivirile
            # de până acum au fost pentru alt client și nu spun nimic despre asta.
            existing.client_id = client_id
            existing.created_by_id = actor_id
            existing.matched_count = 0
            return sender

        self.session.add(
            ClientAlias(
                organization_id=organization_id,
                client_id=client_id,
                kind=AliasKind.SENDER,
                value=sender,
                created_by_id=actor_id,
            )
        )
        return sender

    def _sender_of(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> str:
        """Adresa de la care a sosit documentul, dacă a sosit de undeva.

        Un document urcat manual nu are recepție cu expeditor: acolo nu e nimic de
        învățat, iar a lega adresa colegului care l-a urcat de un client ar trimite
        acolo tot ce urcă el.
        """
        intake = self.session.scalars(
            select(DocumentIntake).where(
                DocumentIntake.organization_id == organization_id,
                DocumentIntake.document_id == document_id,
            )
        ).first()
        return normalize_sender(intake.sender if intake else None)

    # ── Potrivirea ──────────────────────────────────────────────────────────

    def match(self, organization_id: uuid.UUID, sender: str | None) -> AliasMatch | None:
        """Clientul învățat pentru adresa asta, dacă există unul."""
        value = normalize_sender(sender)
        if not value:
            return None

        row = self.session.execute(
            select(ClientAlias.client_id, Client.name)
            .join(Client, Client.id == ClientAlias.client_id)
            .where(
                ClientAlias.organization_id == organization_id,
                ClientAlias.kind == AliasKind.SENDER,
                ClientAlias.value == value,
                Client.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            return None
        return AliasMatch(client_id=row[0], client_name=row[1], sender=value)

    def count_match(self, organization_id: uuid.UUID, sender: str) -> None:
        """Un alias care potrivește des este o decizie care s-a dovedit bună.

        Contorul nu schimbă nicio hotărâre; există ca omul care se uită la lista
        de pe fișa clientului să distingă un alias care lucrează de unul rămas de
        la o atribuire întâmplătoare.
        """
        self.session.execute(
            update(ClientAlias)
            .where(
                ClientAlias.organization_id == organization_id,
                ClientAlias.kind == AliasKind.SENDER,
                ClientAlias.value == normalize_sender(sender),
            )
            .values(matched_count=ClientAlias.matched_count + 1)
        )

    # ── Ce vede omul ────────────────────────────────────────────────────────

    def for_client(self, organization_id: uuid.UUID, client_id: uuid.UUID) -> list[ClientAlias]:
        return list(
            self.session.scalars(
                select(ClientAlias)
                .where(
                    ClientAlias.organization_id == organization_id,
                    ClientAlias.client_id == client_id,
                )
                .order_by(ClientAlias.matched_count.desc(), ClientAlias.value)
            )
        )

    def forget(self, organization_id: uuid.UUID, alias_id: uuid.UUID) -> ClientAlias | None:
        alias = self.session.scalars(
            select(ClientAlias).where(
                ClientAlias.organization_id == organization_id, ClientAlias.id == alias_id
            )
        ).first()
        if alias is not None:
            self.session.delete(alias)
        return alias
