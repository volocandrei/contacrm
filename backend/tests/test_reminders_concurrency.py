"""Doua batai de planificator peste aceleasi remindere (§72).

**De ce merita un fisier separat.** Restul suitei de remindere verifica **ce nu
pleaca**: nu se reaminteste ce nu s-a cerut, nu mai des de patru zile, nu dupa
termen. Toate acele reguli citesc din baza ce s-a trimis pana acum — deci toate
presupun ca cineva a apucat sa scrie inainte ca urmatorul sa citeasca.

Sub doua batai suprapuse presupunerea cade. Cronul cere `/internal/reminders` la
o ora fixa; daca bataia dureaza mai mult decat crede planificatorul, daca cineva
apasa „reincearca", sau daca ruleaza doua procese de API — si documentatia de
livrare chiar recomanda mai multe — a doua bataie intra peste prima. Amandoua
citesc „nu s-a trimis nimic azi", amandoua hotarasc ca este de trimis, si
clientul primeste acelasi mesaj de doua ori.

**De ce conteaza mai mult decat pare.** Un reminder in plus nu produce o eroare
in nicio consola. Produce un client care muta adresa cabinetului in spam — iar
dupa aceea nu mai citeste nici ce scrie omul. Este exact paguba pe care
`test_reminders.py` o descrie in capul lui, ajunsa pe alt drum.

Firele au sesiuni si conexiuni proprii. Pe o singura sesiune, testul n-ar fi
vazut niciodata problema: acolo a doua citire vede randul pe care tot ea l-a
scris.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import ClientStatus, DocumentSource, DocumentStatus
from app.models.audit import AuditLog
from app.models.client import Client, Contact
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.reminder import ClientReminder
from app.models.upload_link import ClientUploadLink
from app.services.mail import EmailMessage
from app.services.reminders import ReminderService
from app.services.upload_links import hash_token
from tests.conftest import requires_db

pytestmark = requires_db

MONTH = "2026-08"
WORKDAY = date(2026, 9, 3)

#: Cate batai pornesc odata. Doua ar fi de ajuns ca sa existe cursa; patru o fac
#: vizibila si cand firele nu pornesc perfect simultan.
SIMULTANEOUS = 4


class Collecting:
    """Providerul de email, inlocuit cu unul care retine ce ar fi plecat."""

    name = "test"

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self._lock = threading.Lock()

    def send(self, message: EmailMessage) -> None:
        with self._lock:
            self.sent.append(message)


def _seed(make_session: sessionmaker, organization_id: uuid.UUID) -> uuid.UUID:
    """Un client caruia i s-a cerut, care n-a raspuns, si caruia i se poate scrie.

    Adica exact starea `DUE`: cererea a plecat acum sase zile (peste tacerea de
    patru), a sosit o singura factura din cele trei asteptate, iar pe fisa exista
    o adresa de email.
    """
    client_id = uuid.uuid4()
    with make_session() as setup:
        setup.add(
            Organization(
                id=organization_id,
                name="Cabinet Remindere SRL",
                tax_id=f"RO{uuid.uuid4().int % 10**8:08d}",
            )
        )
        setup.flush()
        setup.add(
            Client(
                id=client_id,
                organization_id=organization_id,
                name="Alfa Conta SRL",
                tax_id=f"RO{uuid.uuid4().int % 10**8:08d}",
                status=ClientStatus.ACTIVE,
            )
        )
        types: dict[str, DocumentType] = {}
        for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
            row = DocumentType(
                organization_id=organization_id,
                code=seed.code,
                label=seed.label,
                sort_order=index,
                required_fields=list(seed.required_fields),
            )
            setup.add(row)
            types[seed.code] = row
        setup.flush()

        for code, minimum in (("FACTURA_INTRARE", 2), ("EXTRAS_CONT", 1)):
            setup.add(
                ClientExpectation(
                    organization_id=organization_id,
                    client_id=client_id,
                    document_type_id=types[code].id,
                    expected_min_count=minimum,
                )
            )
        # O singura factura sosita: luna exista si este in lucru, dar mai lipseste.
        setup.add(
            Document(
                organization_id=organization_id,
                client_id=client_id,
                document_type_id=types["FACTURA_INTRARE"].id,
                status=DocumentStatus.REVIEW_REQUIRED,
                source=DocumentSource.UPLOAD,
                original_filename="factura.pdf",
                storage_key=f"organizations/{organization_id}/documents/{uuid.uuid4()}/original/source.pdf",
                mime_type="application/pdf",
                file_size=512,
                sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                received_at=datetime.now(UTC),
                reference_month=MONTH,
            )
        )
        setup.add(Contact(client_id=client_id, full_name="Mihai Dobre", email="mihai@alfa.test"))
        setup.add(
            ClientUploadLink(
                organization_id=organization_id,
                client_id=client_id,
                token_hash=hash_token(uuid.uuid4().hex),
                expires_at=datetime.now(UTC) + timedelta(days=45),
                reference_month=MONTH,
                notified_at=datetime.combine(WORKDAY, datetime.min.time(), tzinfo=UTC)
                - timedelta(days=6),
                notified_to="mihai@alfa.test",
            )
        )
        setup.commit()
    return client_id


def _erase(make_session: sessionmaker, organization_id: uuid.UUID) -> None:
    """Randurile comise se sterg dupa test.

    Restul suitei de remindere numara randuri **peste toata baza**, nu pe
    organizatie: este o suita cu un singur cabinet si asa este scrisa. Testul de
    fata este singurul care comite, deci tot el raspunde de curatenie — altfel
    lasa in urma un reminder pe care alt fisier il numara ca fiind al lui.
    """
    with make_session() as cleanup:
        for model in (
            AuditLog,
            ClientReminder,
            ClientUploadLink,
            Document,
            ClientExpectation,
            DocumentType,
        ):
            cleanup.execute(sa.delete(model).where(model.organization_id == organization_id))
        cleanup.execute(
            sa.delete(Contact).where(
                Contact.client_id.in_(
                    sa.select(Client.id).where(Client.organization_id == organization_id)
                )
            )
        )
        cleanup.execute(sa.delete(Client).where(Client.organization_id == organization_id))
        cleanup.execute(sa.delete(Organization).where(Organization.id == organization_id))
        cleanup.commit()


def test_two_simultaneous_scheduler_beats_write_to_the_client_once(
    db_engine: sa.Engine,
) -> None:
    """Patru batai deodata, un singur mesaj catre client."""
    make_session = sessionmaker(bind=db_engine, expire_on_commit=False)
    organization_id = uuid.uuid4()
    client_id = _seed(make_session, organization_id)

    sender = Collecting()
    ready = threading.Barrier(SIMULTANEOUS)
    failures: list[BaseException] = []
    lock = threading.Lock()

    def beat() -> None:
        try:
            with make_session() as session:
                service = ReminderService(session, organization_id)
                ready.wait(timeout=30)
                service.send(sender, today=WORKDAY)
                session.commit()
        except BaseException as error:
            with lock:
                failures.append(error)

    threads = [threading.Thread(target=beat) for _ in range(SIMULTANEOUS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not failures, failures

    # Ce a primit clientul.
    assert len(sender.sent) == 1, [message.to for message in sender.sent]

    # Si ce a ramas scris: un singur rand de urma, altfel contorul lunar ar
    # consuma doua sanse pentru un singur mesaj.
    with make_session() as check:
        rows = check.scalars(
            sa.select(ClientReminder).where(ClientReminder.client_id == client_id)
        ).all()
    written = len(rows)
    _erase(make_session, organization_id)

    assert written == 1
