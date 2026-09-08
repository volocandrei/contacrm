"""Două cabinete, fiecare cu datele lui, și **fiecare rută parametrizată** probată.

**De ce încă un test de izolare.** Există deja verificări pe module — documente,
perioade, integrări, bancă — și fiecare își face treaba pe zona ei. Ce lipsea era
unul care să pornească de la **tabela de rutare a aplicației**, nu de la memoria
cuiva: o rută nouă intră automat în sweep, iar dacă nimeni nu i-a pus izolarea,
testul cade. Sweep-urile scrise de mână nu observă rutele care nu existau când au
fost scrise.

**Ce se probează.** Fiecare rută care poartă un identificator în cale este
chemată cu identificatorul **celuilalt cabinet**, dintr-o sesiune de administrator
cu toate permisiunile. Un administrator este cazul cel mai sever: dacă cineva
trece, el trece.

**Ce se așteaptă: 404, nu 403.** Un 403 confirmă că resursa există. Pentru cineva
care numără cabinete după CUI, diferența dintre „nu ai voie" și „nu există" este
chiar informația pe care nu are dreptul s-o afle (§72).

**Nu doar metadate.** Descărcarea, previzualizarea și fișierele însoțitoare sunt
în listă: acolo s-ar scurge conținutul, nu un nume de client. Un test care se
oprește la `GET /documents/{id}` verifică jumătatea ieftină.

**Corpul cererii, nu doar calea.** Câteva rute primesc identificatorul străin în
corp — atribuirea unui client, legarea a două documente, potrivirea unei
tranzacții cu o factură. Acolo calea este a mea și corpul este al lui; se
verifică separat, mai jos.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain.enums import (
    BankDirection,
    BankTransactionStatus,
    DocumentSource,
    DocumentStatus,
    ObligationFrequency,
)
from app.domain.permissions import ROLE_PERMISSIONS, RoleCode
from app.models.alias import AliasKind, ClientAlias
from app.models.anaf import AnafConnection, AnafMandate
from app.models.bank import BankStatement, BankTransaction
from app.models.client import Client, Contact
from app.models.document import Document
from app.models.imap import ImapMailbox
from app.models.microsoft import DriveFolder, MailFolder, MicrosoftConnection
from app.models.obligation import ObligationType
from app.models.organization import Organization
from app.models.period import ExpectationTemplate
from app.models.task import Task
from app.models.upload_link import ClientUploadLink
from app.models.user import Permission, Role, User
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "parola-de-test-pentru-izolare-2026"

#: Un PDF sintetic. Doar antetul, plus umplutură — niciun document real (§70).
PDF_BYTES = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"

#: Parametrii din cale care **nu** identifică o resursă a unui cabinet.
#:
#: `reference_month` este o lună, `token` este el însuși credențiala portalului
#: (are testul lui, mai jos). Restul trebuie să aibă un id străin, altfel sweep-ul
#: ar chema rute cu un `uuid4` inventat și ar trece pentru motivul greșit: „nu
#: există nicăieri" nu dovedește izolarea, dovedește doar că am ghicit prost.
NOT_A_RESOURCE = {"reference_month": "2026-08", "token": "token-inexistent-de-test"}


#: Corpul minim valid al fiecărei rute care cere unul.
#:
#: **De ce nu ajunge `{}`.** Validarea corpului se face **înainte** de căutarea
#: resursei: o cerere fără câmpurile obligatorii primește 422 și nu ajunge
#: niciodată la verificarea de organizație. Sweep-ul ar fi „probat" douăzeci de
#: rute fără să atingă vreodată granița pe care le verifică — un verde care
#: măsoară validarea, nu izolarea. S-a văzut la mutație: filtrul din
#: `get_for_update` s-a putut scoate fără ca vreun test să cadă.
#:
#: Câmpurile vin din schema OpenAPI a aplicației, nu din memorie.
REQUIRED_BODIES: dict[tuple[str, str], dict[str, object]] = {
    ("POST", "/api/v1/bank/transactions/{transaction_id}/match"): {"documentId": None},
    ("POST", "/api/v1/clients/{client_id}/contacts"): {"fullName": "Persoană nouă"},
    ("PUT", "/api/v1/clients/{client_id}/expectations"): {"expectations": []},
    ("POST", "/api/v1/clients/{client_id}/notes"): {"body": "notă de test"},
    ("PATCH", "/api/v1/documents/{document_id}"): {"updates": []},
    ("POST", "/api/v1/documents/{document_id}/assign-client"): {"clientId": None},
    ("POST", "/api/v1/documents/{document_id}/pairing"): {"documentId": None},
    ("POST", "/api/v1/documents/{document_id}/reject"): {"reason": "motiv de test"},
    ("POST", "/api/v1/expectation-templates/from-client/{client_id}"): {"name": "Profil nou"},
    ("PUT", "/api/v1/expectation-templates/{template_id}"): {
        "name": "Profil",
        "expectations": [],
    },
    ("POST", "/api/v1/expectation-templates/{template_id}/apply"): {"clientIds": []},
    ("PATCH", "/api/v1/integrations/anaf/mandates/{mandate_id}"): {"isActive": False},
    ("PATCH", "/api/v1/integrations/onedrive/mail-folders/{folder_id}"): {"isActive": False},
    ("PUT", "/api/v1/obligations/clients/{client_id}"): {"obligationTypeIds": []},
    ("PATCH", "/api/v1/tasks/{task_id}"): {"status": "DONE"},
    ("POST", "/api/v1/users/{user_id}/password"): {"password": "parola-noua-lunga-2026"},
}

#: Rutele care primesc **și** un identificator străin în corp.
#:
#: Aici se pune al meu, ca sweep-ul să măsoare granița căii, nu pe cea a corpului.
#: Corpul străin are testele lui în `TestForeignIdentifiersInTheBody`.
BODY_IDENTIFIER = {
    ("POST", "/api/v1/bank/transactions/{transaction_id}/match"): "document_id",
    ("POST", "/api/v1/documents/{document_id}/assign-client"): "client_id",
    ("POST", "/api/v1/documents/{document_id}/pairing"): "document_id",
}


def body_for(
    method: str, template: str, own: dict[str, str], foreign: dict[str, str]
) -> dict[str, object] | None:
    """Corpul cu care se cheamă ruta, cu identificatorii **mei** în el."""
    if method not in {"POST", "PATCH", "PUT"}:
        return None
    payload = dict(REQUIRED_BODIES.get((method, template), {}))
    field = BODY_IDENTIFIER.get((method, template))
    if field is not None:
        key = {"document_id": "documentId", "client_id": "clientId"}[field]
        payload[key] = own[field]
    return payload


@dataclass(frozen=True, slots=True)
class Cabinet:
    """Un cabinet cu tot ce se poate atinge printr-o rută."""

    organization: Organization
    admin: User
    client: Client
    contact: Contact
    document: Document
    alias: ClientAlias
    upload_link: ClientUploadLink
    task: Task
    template: ExpectationTemplate
    obligation_type: ObligationType
    transaction: BankTransaction
    mandate: AnafMandate
    mailbox: ImapMailbox
    drive_folder: DriveFolder
    mail_folder: MailFolder

    def path_values(self, template: str = "") -> dict[str, str]:
        """Ce se pune în locul fiecărui parametru din cale.

        `template` există pentru o coliziune de nume care altfel ar fi trecut
        neobservată: **`folder_id` înseamnă două lucruri**. Pe
        `/onedrive/folders/{folder_id}` este un dosar de fișiere, pe
        `/onedrive/mail-folders/{folder_id}` este unul de email. Cu un singur id
        pentru amândouă, rutele de email primeau id-ul unui dosar de drive și
        răspundeau 404 — dar din „nu există", nu din „nu este al tău". Un verde
        care nu dovedea nimic.
        """
        folder = (
            str(self.mail_folder.id) if "mail-folders" in template else str(self.drive_folder.id)
        )
        return {
            "client_id": str(self.client.id),
            "contact_id": str(self.contact.id),
            "document_id": str(self.document.id),
            "alias_id": str(self.alias.id),
            "link_id": str(self.upload_link.id),
            "task_id": str(self.task.id),
            "template_id": str(self.template.id),
            "obligation_type_id": str(self.obligation_type.id),
            "transaction_id": str(self.transaction.id),
            "mandate_id": str(self.mandate.id),
            "mailbox_id": str(self.mailbox.id),
            "folder_id": folder,
            "user_id": str(self.admin.id),
            # Fișierul însoțitor al documentului străin. Granița care se verifică
            # aici este a **documentului**: ea trebuie să se închidă înainte ca
            # fișierul să conteze, deci un id valid ca formă este de ajuns.
            "file_id": str(uuid.uuid4()),
            **NOT_A_RESOURCE,
        }


def _roles(db: Session) -> dict[RoleCode, Role]:
    """Rolurile, create o singură dată pentru toată baza de test."""
    existing = {RoleCode(row.code): row for row in db.query(Role).all()}
    if existing:
        return existing

    permissions: dict[str, Permission] = {}
    for perms in ROLE_PERMISSIONS.values():
        for permission in perms:
            permissions.setdefault(
                permission.value, Permission(code=permission.value, description=permission.value)
            )
    db.add_all(permissions.values())
    db.flush()

    roles: dict[RoleCode, Role] = {}
    for code, perms in ROLE_PERMISSIONS.items():
        role = Role(code=code.value, name=code.value)
        role.permissions = [permissions[p.value] for p in sorted(perms)]
        db.add(role)
        roles[code] = role
    db.flush()
    return roles


def build_cabinet(db: Session, *, marker: str, tax_id: str) -> Cabinet:
    """Un cabinet complet: client, document, bancă, declarații, integrări."""
    roles = _roles(db)

    org = Organization(name=f"Cabinet {marker} SRL", tax_id=tax_id)
    db.add(org)
    db.flush()

    admin = User(
        organization_id=org.id,
        email=f"admin.{marker.lower()}@contacrm.test",
        full_name=f"Administrator {marker}",
        password_hash=hash_password(PASSWORD),
        is_active=True,
        roles=[roles[RoleCode.ADMIN]],
    )
    client = Client(organization_id=org.id, name=f"Client {marker} SRL", tax_id=f"RO{tax_id[-6:]}1")
    db.add_all([admin, client])
    db.flush()

    # `Contact` nu are organizatie proprie: apartine clientului, iar clientul
    # cabinetului. Granita lui se inchide prin client, si asta verifica sweep-ul.
    contact = Contact(
        client_id=client.id,
        full_name=f"Persoana {marker}",
        email=f"contact.{marker.lower()}@client.test",
        is_primary=True,
    )
    document = Document(
        organization_id=org.id,
        client_id=client.id,
        status=DocumentStatus.REVIEW_REQUIRED,
        source=DocumentSource.UPLOAD,
        original_filename=f"factura-{marker.lower()}.pdf",
        storage_key=f"{org.id}/{uuid.uuid4()}.pdf",
        mime_type="application/pdf",
        file_size=2048,
        sha256_hash=uuid.uuid4().hex.ljust(64, "0"),
        received_at=datetime.now(UTC),
    )
    alias = ClientAlias(
        organization_id=org.id,
        client_id=client.id,
        kind=AliasKind.SENDER,
        value=f"expeditor.{marker.lower()}@client.test",
    )
    upload_link = ClientUploadLink(
        organization_id=org.id,
        client_id=client.id,
        token_hash=uuid.uuid4().hex.ljust(64, "0"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by_id=admin.id,
    )
    task = Task(organization_id=org.id, title=f"Sarcină {marker}", client_id=client.id)
    template = ExpectationTemplate(organization_id=org.id, name=f"Profil {marker}")
    obligation_type = ObligationType(
        organization_id=org.id,
        code="D300",
        label="D300 — decont TVA",
        frequency=ObligationFrequency.MONTHLY,
        months_after=1,
        deadline_day=25,
    )
    db.add_all([contact, document, alias, upload_link, task, template, obligation_type])
    db.flush()

    statement = BankStatement(
        organization_id=org.id,
        client_id=client.id,
        iban=f"RO49AAAA1B31007593840{tax_id[-4:]}",
        bank_name=f"Banca {marker}",
        currency="RON",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        statement_number=f"{marker}-08",
        imported_at=datetime.now(UTC),
    )
    db.add(statement)
    db.flush()
    transaction = BankTransaction(
        statement_id=statement.id,
        organization_id=org.id,
        client_id=client.id,
        position=1,
        booking_date=date(2026, 8, 12),
        amount=Decimal("1190.00"),
        currency="RON",
        direction=BankDirection.DEBIT,
        description=f"Plată furnizor {marker}",
        status=BankTransactionStatus.UNMATCHED,
    )
    # Tokenurile sunt marcaje, nu credentiale: nu se cheama nimic din exterior
    # in testul asta, iar ce se verifica este granita, nu conexiunea.
    connection = AnafConnection(
        organization_id=org.id,
        environment="test",
        refresh_token=f"marcaj-{marker}",
        connected_at=datetime.now(UTC),
        is_active=True,
    )
    ms_connection = MicrosoftConnection(
        organization_id=org.id,
        account_email=f"{marker}@test.ro",
        refresh_token=f"marcaj-{marker}",
        connected_at=datetime.now(UTC),
    )
    mailbox = ImapMailbox(
        organization_id=org.id,
        host="imap.test",
        port=993,
        username=f"cutie.{marker.lower()}@test.ro",
        password=f"marcaj-{marker}",
        folder="INBOX",
    )
    db.add_all([transaction, connection, ms_connection, mailbox])
    db.flush()

    mandate = AnafMandate(
        organization_id=org.id,
        connection_id=connection.id,
        client_id=client.id,
        tax_id=client.tax_id or f"RO{marker}",
        is_active=True,
    )
    drive_folder = DriveFolder(
        organization_id=org.id,
        connection_id=ms_connection.id,
        client_id=client.id,
        drive_id=f"drive-{marker}",
        item_id=f"item-{marker}",
        path=f"/{marker}",
    )
    mail_folder = MailFolder(
        organization_id=org.id,
        connection_id=ms_connection.id,
        folder_id=f"mail-{marker}",
        display_name=f"Inbox {marker}",
    )
    db.add_all([mandate, drive_folder, mail_folder])
    db.flush()

    return Cabinet(
        organization=org,
        admin=admin,
        client=client,
        contact=contact,
        document=document,
        alias=alias,
        upload_link=upload_link,
        task=task,
        template=template,
        obligation_type=obligation_type,
        transaction=transaction,
        mandate=mandate,
        mailbox=mailbox,
        drive_folder=drive_folder,
        mail_folder=mail_folder,
    )


@pytest.fixture
def cabinet_a(db: Session) -> Cabinet:
    return build_cabinet(db, marker="A", tax_id="RO110011")


@pytest.fixture
def cabinet_b(db: Session) -> Cabinet:
    return build_cabinet(db, marker="B", tax_id="RO220022")


@pytest.fixture
def storage_with_both(
    api: TestClient, tmp_path: Path, cabinet_a: Cabinet, cabinet_b: Cabinet
) -> LocalStorageProvider:
    """Fișiere adevărate pentru amândouă documentele.

    **De ce contează.** Fără octeți în stocare, descărcarea răspunde 404 și
    pentru documentul propriu — deci un 404 pe cel străin nu ar fi dovedit
    izolarea, ci doar că nu există fișierul. Testul ar fi trecut cu ruta complet
    ruptă. Cu fișierele puse, singurul motiv rămas pentru 404 este granița.
    """
    from app.api.deps import get_storage

    provider = LocalStorageProvider(tmp_path / "storage")
    for cabinet in (cabinet_a, cabinet_b):
        provider.save(cabinet.document.storage_key, io.BytesIO(PDF_BYTES))

    api.app.dependency_overrides[get_storage] = lambda: provider  # type: ignore[attr-defined]
    return provider


@pytest.fixture
def as_a(api: TestClient, cabinet_a: Cabinet) -> TestClient:
    answer = api.post(
        "/api/v1/auth/login", json={"email": cabinet_a.admin.email, "password": PASSWORD}
    )
    assert answer.status_code == 200, answer.text
    return api


def parameterized_routes(client: TestClient) -> list[tuple[str, str]]:
    """Rutele care poartă un identificator în cale, din arborele real de rutare.

    Aceeași umblare ca în `test_security_routes.py`, și din același motiv: schema
    OpenAPI nu conține rutele scoase din ea, iar un sweep citit de acolo ar trece
    exact peste ele.
    """

    def walk(node: object, prefix: str) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for route in getattr(node, "routes", []):
            if isinstance(route, APIRoute):
                found |= {
                    (method, prefix + route.path)
                    for method in (route.methods or set()) - {"HEAD", "OPTIONS"}
                }
                continue
            inner = getattr(route, "original_router", None)
            if inner is None:
                continue
            context = getattr(route, "include_context", None)
            found |= walk(inner, prefix + (getattr(context, "prefix", "") or ""))
        return found

    app = client.app
    routes = sorted({(m, p) for m, p in walk(app, "") if "{" in p})
    assert len(routes) >= 50, f"descoperire suspect de mică: {len(routes)}"
    return routes


#: Rutele care nu aparțin niciunui cabinet și nu au ce izola.
#:
#: Portalul este public prin construcție: tokenul din link **este** credențiala,
#: iar cine îl are este clientul. Are testul lui, separat, mai jos.
NOT_TENANT_SCOPED = {
    ("GET", "/api/v1/portal/{token}"),
    ("POST", "/api/v1/portal/{token}"),
}


#: Rutele pe care sweep-ul le atinge, dar nu le poate proba **adânc**.
#:
#: „Adânc" înseamnă că aceeași cerere, cu identificatorii mei, reușește — deci un
#: 404 pe cei străini vine din graniță, nu din altceva. Rutele de mai jos
#: răspund 404 sau 422 și cu ale mele, din motive care nu țin de izolare:
#: documentul nu este în starea potrivită, perioada nu există, conexiunea
#: externă nu este configurată în fixtură.
#:
#: **Nu sunt neverificate.** Fiecare are izolarea acoperită în altă parte —
#: `test_security_documents.py` pentru rutele de documente,
#: `test_periods_api.py` pentru perioade, testele de integrări pentru restul.
#: Lista stă aici ca gaura să fie **scrisă**, nu presupusă: dacă mâine o rută
#: nouă nu se poate proba adânc, testul de mai jos cade și cineva trebuie să
#: spună de ce.
SHALLOW_PROBES: frozenset[tuple[str, str]] = frozenset(
    {
        # Documentul de test nu are pereche, nu este un teanc și nu este într-o
        # stare aprobabilă. Stările lui au testele lor.
        ("DELETE", "/api/v1/documents/{document_id}/pairing"),
        ("GET", "/api/v1/documents/{document_id}/split"),
        ("POST", "/api/v1/documents/{document_id}/approve"),
        ("POST", "/api/v1/documents/{document_id}/duplicate"),
        ("POST", "/api/v1/documents/{document_id}/pairing"),
        ("POST", "/api/v1/documents/{document_id}/split"),
        # Descărcarea și previzualizarea se probează adânc separat, cu fișiere
        # adevărate în stocare — vezi `TestTheContentItself`. Aici stocarea nu
        # este montată, deci ar răspunde 404 din lipsa octeților.
        ("GET", "/api/v1/documents/{document_id}/download"),
        ("GET", "/api/v1/documents/{document_id}/preview"),
        ("GET", "/api/v1/documents/{document_id}/files/{file_id}"),
        # Nicio potrivire de șters: tranzacția este `UNMATCHED`.
        ("DELETE", "/api/v1/bank/transactions/{transaction_id}/match/{document_id}"),
        # Clientul nu are un contact cu email confirmat și nici linkuri de trimis.
        ("POST", "/api/v1/clients/{client_id}/document-request"),
        ("POST", "/api/v1/clients/{client_id}/document-request/send"),
        # Perioada august 2026 nu există pentru clientul de test.
        ("POST", "/api/v1/clients/{client_id}/periods/{reference_month}/close"),
        ("POST", "/api/v1/clients/{client_id}/periods/{reference_month}/reopen"),
        # Clientul nu are așteptări din care să iasă un profil, iar profilul nu
        # are ce aplica.
        ("POST", "/api/v1/expectation-templates/from-client/{client_id}"),
        ("POST", "/api/v1/expectation-templates/{template_id}/apply"),
        # Integrările nu sunt configurate: conexiunile din fixtură poartă
        # marcaje, nu credențiale, deliberat — testul de izolare nu are voie să
        # cheme nimic în afară.
        ("PATCH", "/api/v1/integrations/anaf/mandates/{mandate_id}"),
        ("PATCH", "/api/v1/integrations/onedrive/folders/{folder_id}"),
        ("PATCH", "/api/v1/integrations/onedrive/mail-folders/{folder_id}"),
        ("POST", "/api/v1/integrations/imap/{mailbox_id}/sync"),
        # Profilul cere cel puțin o așteptare; unul gol este refuzat de validare
        # înainte să se ajungă la resursă.
        ("PUT", "/api/v1/expectation-templates/{template_id}"),
    }
)


#: Rutele care, probate cu **propriile** id-uri, schimbă starea sesiunii.
#:
#: `POST /users/{id}/password` chiar reușește — deci se probează adânc, ceea ce
#: este bine — dar resetează parola administratorului logat. Este ultima în
#: ordine alfabetică, deci nu deranjează celelalte probe din același test; nota
#: stă aici ca nimeni să nu se mire de ce sesiunea moare dacă ordinea se schimbă.
SELF_DESTRUCTIVE = frozenset({("POST", "/api/v1/users/{user_id}/password")})


def test_the_shallow_list_is_exactly_the_shallow_routes(
    as_a: TestClient, cabinet_a: Cabinet
) -> None:
    """Ce nu se poate proba adânc trebuie să fie scris, nu presupus.

    Testul cade în **amândouă** direcțiile: o rută nouă care nu se poate proba
    adânc obligă pe cineva să scrie de ce, iar una care s-a reparat între timp
    trebuie scoasă din listă — altfel lista ar crește la nesfârșit și ar ascunde
    exact ce ar trebui să arate.
    """
    shallow: set[tuple[str, str]] = set()
    for method, template in parameterized_routes(as_a):
        if (method, template) in NOT_TENANT_SCOPED:
            continue
        mine = cabinet_a.path_values(template)
        path = template
        for name, value in mine.items():
            path = path.replace("{" + name + "}", value)
        response = as_a.request(method, path, json=body_for(method, template, mine, mine))
        if response.status_code in (404, 422):
            shallow.add((method, template))

    assert shallow == set(SHALLOW_PROBES), (
        "lista rutelor probate superficial s-a schimbat.\n"
        f"  noi: {sorted(shallow - set(SHALLOW_PROBES))}\n"
        f"  reparate: {sorted(set(SHALLOW_PROBES) - shallow)}"
    )


def test_the_sweep_knows_every_path_parameter(as_a: TestClient, cabinet_b: Cabinet) -> None:
    """Un parametru nou trebuie să oblige pe cineva să decidă ce id i se dă.

    Fără verificarea asta, sweep-ul ar fi chemat rutele noi cu calea neînlocuită
    și ar fi primit 404 de la rutare — un verde care nu dovedește nimic.
    """
    known = set(cabinet_b.path_values())
    unknown: set[str] = set()
    for _, path in parameterized_routes(as_a):
        unknown |= {part[1:-1] for part in path.split("/") if part.startswith("{")} - known

    assert not unknown, (
        "parametri de cale fără id în `Cabinet.path_values`: "
        + ", ".join(sorted(unknown))
        + ". Adaugă-i, altfel sweep-ul îi trece cu 404 de rutare."
    )


def test_no_route_lets_one_office_reach_another(
    as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet
) -> None:
    """Sweep-ul propriu-zis: fiecare rută, cu identificatorii celuilalt cabinet.

    **Se cere 404, nu „404 sau 422".** Prima versiune accepta și 422, ca să treacă
    peste rutele cărora nu le dădea un corp valid. Mutația a arătat prețul:
    filtrul de organizație s-a putut scoate din interogarea de bază a
    documentelor **fără ca vreun test să cadă** — o scriere scursă răspundea 422
    din validarea de domeniu („documentul nu poate fi respins în starea asta"),
    iar sweep-ul o citea ca izolare. Un 422 venit de dincolo de graniță
    dovedește exact contrariul: cererea a **ajuns** la resursa altcuiva.

    Excepția este `SHALLOW_PROBES`, unde nici cu propriile id-uri nu se trece de
    validare — acolo 422 nu distinge nimic, iar izolarea este acoperită de
    testele dedicate ale modulelor.
    """
    leaks: list[str] = []

    for method, template in parameterized_routes(as_a):
        if (method, template) in NOT_TENANT_SCOPED:
            continue
        path = template
        for name, value in cabinet_b.path_values(template).items():
            path = path.replace("{" + name + "}", value)

        response = as_a.request(
            method,
            path,
            json=body_for(
                method, template, cabinet_a.path_values(template), cabinet_b.path_values(template)
            ),
        )
        accepted = (404, 422) if (method, template) in SHALLOW_PROBES else (404,)
        if response.status_code not in accepted:
            leaks.append(f"{method} {template} → {response.status_code}")

    assert not leaks, "rute care nu izolează cabinetele:\n" + "\n".join(leaks)


def snapshot(db: Session, cabinet: Cabinet) -> dict[str, object]:
    """Starea cabinetului, în valorile pe care o scriere le-ar schimba.

    Se citește **din baza de date**, nu din obiectele deja încărcate: sesiunea
    de test le-ar servi din identity map și ar arăta valorile de dinainte.
    """
    db.expire_all()
    document = db.get(Document, cabinet.document.id)
    client = db.get(Client, cabinet.client.id)
    task = db.get(Task, cabinet.task.id)
    transaction = db.get(BankTransaction, cabinet.transaction.id)
    assert document is not None and client is not None
    assert task is not None and transaction is not None
    return {
        "document.status": document.status,
        "document.client_id": document.client_id,
        "document.updated_at": document.updated_at,
        "document.deleted_at": document.deleted_at,
        "client.name": client.name,
        "client.status": client.status,
        "client.updated_at": client.updated_at,
        "task.status": task.status,
        "transaction.status": transaction.status,
        "contacts": db.query(Contact).filter(Contact.client_id == cabinet.client.id).count(),
    }


def test_the_sweep_leaves_the_other_office_untouched(
    as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet, db: Session
) -> None:
    """Codul de răspuns nu este toată dovada. Starea este.

    **De ce există testul.** O scriere se poate executa și **totuși** răspunde
    404: multe rute modifică întâi și abia apoi recitesc documentul pentru
    răspuns, prin altă interogare, care are propriul filtru de organizație.
    Scoțând filtrul din interogarea de bază, `PATCH /documents/{al lui}` chiar
    modifica documentul celuilalt cabinet — și răspundea 404, iar sweep-ul de mai
    sus îl citea ca izolare. Verificat pe mutație, nu presupus.

    Aici nu se măsoară ce se răspunde, ci ce a rămas scris.
    """
    before = snapshot(db, cabinet_b)

    for method, template in parameterized_routes(as_a):
        if (method, template) in NOT_TENANT_SCOPED:
            continue
        path = template
        for name, value in cabinet_b.path_values(template).items():
            path = path.replace("{" + name + "}", value)
        as_a.request(
            method,
            path,
            json=body_for(
                method, template, cabinet_a.path_values(template), cabinet_b.path_values(template)
            ),
        )

    assert snapshot(db, cabinet_b) == before, (
        "sweep-ul a modificat datele celuilalt cabinet, oricare ar fi fost codul de răspuns"
    )


def test_the_sweep_would_notice_a_leak(as_a: TestClient, cabinet_a: Cabinet) -> None:
    """Contra-proba: cu **propriile** id-uri, aceleași rute răspund.

    Fără ea, sweep-ul de mai sus ar trece și dacă fiecare rută ar fi ruptă: un 404
    din alt motiv arată identic cu unul din izolare.
    """
    reachable = 0

    for method, template in parameterized_routes(as_a):
        if method != "GET" or (method, template) in NOT_TENANT_SCOPED:
            continue
        path = template
        for name, value in cabinet_a.path_values(template).items():
            path = path.replace("{" + name + "}", value)
        if as_a.request(method, path).status_code == 200:
            reachable += 1

    assert reachable >= 10, (
        f"doar {reachable} rute GET răspund cu propriile id-uri: "
        "sweep-ul de izolare ar trece degeaba."
    )


class TestForeignIdentifiersInTheBody:
    """Calea este a mea, identificatorul din corp este al lui.

    Rutele astea nu se prind în sweep: calea lor nu poartă nimic străin. Sunt
    exact locurile unde un document al unui cabinet s-ar putea lega de un client
    al altuia — iar legătura, odată scrisă, nu se mai vede ca greșeală.
    """

    def _payload(self, response: Any) -> str:
        return getattr(response, "text", "")

    def test_a_document_cannot_be_assigned_to_another_offices_client(
        self, as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.post(
            f"/api/v1/documents/{cabinet_a.document.id}/assign-client",
            json={"clientId": str(cabinet_b.client.id)},
        )

        assert answer.status_code == 404, self._payload(answer)

    def test_two_documents_from_different_offices_cannot_be_paired(
        self, as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.post(
            f"/api/v1/documents/{cabinet_a.document.id}/pairing",
            json={"documentId": str(cabinet_b.document.id)},
        )

        assert answer.status_code == 404, self._payload(answer)

    def test_a_transaction_cannot_be_matched_to_another_offices_document(
        self, as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.post(
            f"/api/v1/bank/transactions/{cabinet_a.transaction.id}/match",
            json={"documentId": str(cabinet_b.document.id)},
        )

        assert answer.status_code == 404, self._payload(answer)

    def test_a_filing_cannot_be_recorded_for_another_offices_client(
        self, as_a: TestClient, cabinet_a: Cabinet, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.post(
            "/api/v1/obligations/filings",
            json={
                "clientId": str(cabinet_b.client.id),
                "obligationTypeId": str(cabinet_a.obligation_type.id),
                "period": "2026-08",
            },
        )

        assert answer.status_code == 404, self._payload(answer)

    def test_a_bulk_action_cannot_touch_another_offices_documents(
        self, as_a: TestClient, cabinet_b: Cabinet, db: Session
    ) -> None:
        """Acțiunile în masă primesc o listă de id-uri — cel mai ușor loc de strecurat."""
        before = cabinet_b.document.status

        answer = as_a.post(
            "/api/v1/documents/bulk",
            json={"ids": [str(cabinet_b.document.id)], "payload": {"action": "approve"}},
        )

        assert answer.status_code in (200, 404), self._payload(answer)
        db.refresh(cabinet_b.document)
        assert cabinet_b.document.status is before, "documentul altui cabinet a fost atins"


class TestTheContentItself:
    """Nu doar metadatele: octeții.

    Un test care se oprește la `GET /documents/{id}` verifică jumătatea ieftină.
    Ce contează la un control este dacă cineva a putut **descărca** factura.
    """

    @pytest.mark.usefixtures("storage_with_both")
    def test_my_own_document_really_does_download(
        self, as_a: TestClient, cabinet_a: Cabinet
    ) -> None:
        """Întâi se dovedește că ruta funcționează.

        Altfel cele două teste de mai jos ar fi trecut și cu descărcarea complet
        ruptă: un 404 din „ruta nu merge" arată identic cu unul din izolare.
        """
        answer = as_a.get(f"/api/v1/documents/{cabinet_a.document.id}/download")

        assert answer.status_code == 200, answer.text
        assert answer.content.startswith(b"%PDF")

    @pytest.mark.usefixtures("storage_with_both")
    def test_another_offices_document_cannot_be_downloaded(
        self, as_a: TestClient, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.get(f"/api/v1/documents/{cabinet_b.document.id}/download")

        assert answer.status_code == 404
        assert b"%PDF" not in answer.content

    @pytest.mark.usefixtures("storage_with_both")
    def test_another_offices_document_cannot_be_previewed(
        self, as_a: TestClient, cabinet_b: Cabinet
    ) -> None:
        answer = as_a.get(f"/api/v1/documents/{cabinet_b.document.id}/preview")

        assert answer.status_code == 404
        assert b"%PDF" not in answer.content

    def test_an_export_contains_only_my_office(self, as_a: TestClient, cabinet_b: Cabinet) -> None:
        """Exporturile nu au id în cale, deci nu intră în sweep — dar au tot ce contează."""
        for url in (
            "/api/v1/reports/register.csv",
            "/api/v1/reports/summary.csv",
            "/api/v1/reports/filings.csv",
        ):
            answer = as_a.get(url)
            assert answer.status_code == 200, f"{url}: {answer.text}"
            assert cabinet_b.client.name not in answer.text, url
            assert cabinet_b.document.original_filename not in answer.text, url

    def test_search_does_not_reach_across(self, as_a: TestClient, cabinet_b: Cabinet) -> None:
        """Căutarea liberă este cea mai ușoară cale de a citi altceva decât ai voie."""
        for url, param in (
            ("/api/v1/documents", "q"),
            ("/api/v1/clients", "q"),
        ):
            answer = as_a.get(url, params={param: cabinet_b.client.name})
            assert answer.status_code == 200, answer.text
            assert answer.json()["items"] == [], url

    def test_the_portal_token_of_another_office_is_not_guessable(
        self, as_a: TestClient, cabinet_b: Cabinet
    ) -> None:
        """Portalul este public, dar tokenul **este** credențiala.

        Se verifică ce se întâmplă cu unul care nu corespunde: 404, fără să spună
        dacă a existat vreodată.
        """
        answer = as_a.get(f"/api/v1/portal/{uuid.uuid4().hex}")

        assert answer.status_code == 404
        assert cabinet_b.client.name not in answer.text
