"""Comenzi de administrare.

    uv run python -m app.cli sync-roles     # aduce rolurile/permisiunile la zi
    uv run python -m app.cli seed-dev       # organizație + utilizatori de development
    uv run python -m app.cli create-admin   # primul cont al unei baze de producție
    uv run python -m app.cli add-client     # un client nou, într-o bază de producție
    uv run python -m app.cli check-storage  # baza de date și stocarea se potrivesc?

`sync-roles` este idempotentă și trebuie rulată după fiecare schimbare în
`app/domain/permissions.py`: tabelele `roles`/`permissions` sunt administrabile,
dar pornesc de la harta din cod.

`seed-dev` refuză să ruleze în producție. Parolele sunt evident de development.
"""

from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import session_scope
from app.core.migrations import run_migrations
from app.core.security import hash_password
from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import ClientStatus, TaskPriority, TaskStatus
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS
from app.domain.permissions import Permission as PermissionCode
from app.models.client import Client, ClientNote, Contact, Tag
from app.models.document import DocumentType
from app.models.organization import Organization
from app.models.period import ClientExpectation
from app.models.task import Task
from app.models.user import Permission, Role, User

DEV_PASSWORD = "contacrm-dev"

# Lungimea minima ceruta primului administrator. Nu este o politica de parole —
# doar pragul sub care o instalare noua ar porni deja compromisa.
MIN_ADMIN_PASSWORD_LENGTH = 12

# Sufixul fara de care `reset-e2e` refuza sa stearga ceva.
E2E_SUFFIX = "_e2e"

# Cate neconcordante enumera `check-storage` inainte sa se opreasca din listat.
# Daca sunt mai multe, numarul total spune oricum ce trebuie stiut.
PROBLEMS_SHOWN = 20

# Toate denumirile, CUI-urile și adresele sunt inventate. „Șerbănescu" există
# intenționat: verifică vizual că sortarea și căutarea ignoră diacriticele.
DEV_CLIENTS = [
    ("Alfa Conta SRL", "RO10000101", ClientStatus.ACTIVE, "prioritar"),
    ("Beta Service SRL", "RO10000102", ClientStatus.ACTIVE, None),
    ("Șerbănescu Impex SRL", "RO10000103", ClientStatus.ACTIVE, "prioritar"),
    ("Delta Prod SRL", "RO10000104", ClientStatus.ACTIVE, None),
    ("Gama Distribuție SRL", "RO10000105", ClientStatus.PROSPECT, None),
    ("Epsilon Trans SRL", "RO10000106", ClientStatus.INACTIVE, None),
]

DEV_USERS = [
    ("Ioana Marinescu", "admin@contacrm.test", "ADMIN"),
    ("Andrei Popa", "contabil@contacrm.test", "ACCOUNTANT"),
    ("Elena Dinu", "operator@contacrm.test", "OPERATOR"),
    ("Mihai Rusu", "verificator@contacrm.test", "REVIEWER"),
    ("Carmen Ilie", "vizitator@contacrm.test", "VIEWER"),
]


def sync_roles() -> None:
    """Creează sau actualizează rolurile și permisiunile din harta din cod."""
    with session_scope() as session:
        existing_perms = {p.code: p for p in session.scalars(select(Permission))}
        for code in PermissionCode:
            if code.value not in existing_perms:
                permission = Permission(code=code.value)
                session.add(permission)
                existing_perms[code.value] = permission
        session.flush()

        existing_roles = {str(r.code): r for r in session.scalars(select(Role))}
        for role_code, permissions in ROLE_PERMISSIONS.items():
            role = existing_roles.get(role_code.value)
            if role is None:
                role = Role(code=role_code.value, name=ROLE_LABEL[role_code])
                session.add(role)
                session.flush()
            role.name = ROLE_LABEL[role_code]
            # Reasignare completă: harta din cod este autoritatea.
            role.permissions = [existing_perms[p.value] for p in sorted(permissions)]

        print(f"roluri sincronizate: {len(ROLE_PERMISSIONS)}, permisiuni: {len(PermissionCode)}")


def seed_dev() -> None:
    if settings.is_production:
        sys.exit("seed-dev nu rulează în producție.")

    sync_roles()

    with session_scope() as session:
        organization = session.scalars(select(Organization)).first()
        if organization is None:
            organization = Organization(name="Cabinet Contabil Demo SRL", tax_id="RO10000001")
            session.add(organization)
            session.flush()

        roles = {str(r.code): r for r in session.scalars(select(Role))}
        created = 0
        for full_name, email, role_code in DEV_USERS:
            if session.scalars(select(User).where(User.email == email)).first():
                continue
            user = User(
                organization_id=organization.id,
                email=email.strip().lower(),
                full_name=full_name,
                password_hash=hash_password(DEV_PASSWORD),
                # Oglindește setul sintetic din frontend: vizitatorul e dezactivat,
                # ca fluxul „cont dezactivat" să fie testabil.
                is_active=email != "vizitator@contacrm.test",
                roles=[roles[role_code]],
            )
            session.add(user)
            created += 1

        session.flush()
        types_created = sync_document_types(session, organization)
        clients_created = _seed_crm(session, organization)
        # Separat de `_seed_crm`, care iese devreme dacă există deja clienți:
        # așteptările trebuie să ajungă și pe o bază populată înainte de M6.
        expectations = _seed_expectations(session, organization)

        print(f"organizație: {organization.name}")
        print(f"utilizatori creați: {created} (parolă: {DEV_PASSWORD})")
        print(f"tipuri de document: {types_created}")
        print(f"clienți creați: {clients_created}")
        print(f"așteptări lunare adăugate: {expectations}")


def sync_document_types(session: Session, organization: Organization) -> int:
    """Încarcă tipurile implicite pentru o organizație (§6).

    Idempotentă, ca `sync_roles`: tipurile se administrează din interfață, dar
    pornesc de la lista din `app/domain/document_types.py`. Etichetele și câmpurile
    obligatorii se aduc la zi; `is_active` rămâne cum l-a lăsat administratorul.
    """
    existing = {
        row.code: row
        for row in session.scalars(
            select(DocumentType).where(DocumentType.organization_id == organization.id)
        )
    }

    created = 0
    for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = existing.get(seed.code)
        if row is None:
            row = DocumentType(organization_id=organization.id, code=seed.code, label=seed.label)
            session.add(row)
            created += 1
        row.label = seed.label
        row.sort_order = index
        row.required_fields = list(seed.required_fields)

    return created


def _seed_crm(session: Session, organization: Organization) -> int:
    """Clienți, contacte, note și sarcini, ca ecranele să aibă ce afișa.

    Idempotentă: rulată de două ori nu dublează nimic.
    """
    if session.scalars(select(Client).where(Client.organization_id == organization.id)).first():
        return 0

    accountant = session.scalars(select(User).where(User.email == "contabil@contacrm.test")).first()

    tags: dict[str, Tag] = {}
    for _, _, _, tag_name in DEV_CLIENTS:
        if tag_name and tag_name not in tags:
            tag = Tag(organization_id=organization.id, name=tag_name)
            session.add(tag)
            tags[tag_name] = tag
    session.flush()

    created = 0
    for index, (name, tax_id, status, tag_name) in enumerate(DEV_CLIENTS):
        client = Client(
            organization_id=organization.id,
            name=name,
            tax_id=tax_id,
            registration_number=f"J40/{1000 + index}/2020",
            address=f"Str. Sintetică {index + 1}, București",
            status=status,
            assigned_accountant_id=accountant.id if accountant else None,
            tags=[tags[tag_name]] if tag_name else [],
        )
        session.add(client)
        session.flush()
        created += 1

        session.add(
            Contact(
                client_id=client.id,
                full_name=f"Persoană Contact {index + 1}",
                role="Administrator",
                email=f"contact{index + 1}@exemplu.test",
                phone=f"+40700000{index:03d}",
                is_primary=True,
            )
        )
        session.add(
            ClientNote(
                client_id=client.id,
                author_name=accountant.full_name if accountant else "Sistem",
                author_id=accountant.id if accountant else None,
                body=f"Notă inițială pentru {name}. Date sintetice, fără valoare reală.",
            )
        )

    session.add_all(
        [
            Task(
                organization_id=organization.id,
                title="Verifică documentele lipsă pentru august",
                description="Extras de cont și bonuri fiscale.",
                priority=TaskPriority.HIGH,
                status=TaskStatus.TODO,
                due_date=date(2026, 9, 15),
                assigned_to_id=accountant.id if accountant else None,
            ),
            Task(
                organization_id=organization.id,
                title="Actualizează șabloanele de reminder",
                priority=TaskPriority.NORMAL,
                status=TaskStatus.IN_PROGRESS,
            ),
            Task(
                organization_id=organization.id,
                title="Confirmă regula de perioadă de referință",
                description="TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION.",
                priority=TaskPriority.URGENT,
                status=TaskStatus.BLOCKED,
            ),
        ]
    )
    return created


# Ce se așteaptă lunar de la un client de development. În producție lista se
# administrează per client — de la firma X vin extrase de cont, de la firma Y nu —
# iar un checklist identic pentru toți ar raporta lipsuri inexistente.
DEV_EXPECTATIONS: tuple[tuple[str, int], ...] = (
    ("FACTURA_INTRARE", 5),
    ("FACTURA_IESIRE", 2),
    ("EXTRAS_CONT", 1),
    ("BON_FISCAL", 3),
)


def _seed_expectations(session: Session, organization: Organization) -> int:
    """Checklistul lunar al fiecărui client (§19).

    Fără el, perioadele arată „în colectare" la nesfârșit: nu se așteaptă nimic,
    deci nimic nu lipsește și nimic nu se completează niciodată.
    """
    types = {
        row.code: row
        for row in session.scalars(
            select(DocumentType).where(DocumentType.organization_id == organization.id)
        ).all()
    }
    clients = session.scalars(
        select(Client).where(Client.organization_id == organization.id, Client.deleted_at.is_(None))
    ).all()

    existing = {
        row.client_id
        for row in session.scalars(
            select(ClientExpectation).where(ClientExpectation.organization_id == organization.id)
        ).all()
    }

    created = 0
    for client in clients:
        if client.id in existing:
            continue
        for code, minimum in DEV_EXPECTATIONS:
            document_type = types.get(code)
            if document_type is None:
                continue
            session.add(
                ClientExpectation(
                    organization_id=organization.id,
                    client_id=client.id,
                    document_type_id=document_type.id,
                    expected_min_count=minimum,
                )
            )
            created += 1
    session.flush()
    return created


def recover_processing() -> None:
    """Reia cererile de procesare rămase pe drum (§43).

    Outbox-ul garantează că o cerere nu se pierde; comanda asta este partea a doua:
    dacă procesul care trebuia s-o execute a murit, cererea se repune în coadă.

    De rulat după o cădere sau o repornire. Când vine coada persistentă (M6),
    aceeași funcție rulează periodic în worker, fără să mai fie chemată de mână.
    """
    from app.services.processing_recovery import recover
    from app.services.storage.factory import build_storage_provider

    report = recover(build_storage_provider())
    if report.nothing_to_do:
        print("Nicio cerere de procesare abandonată.")
    else:
        print(f"Repuse în coadă: {report.requeued}. Rulate acum: {report.ran}.")


def check_storage() -> None:
    """Verifică dacă baza de date și stocarea mai spun același lucru (§71).

    Documentele trăiesc în două sisteme care nu împart o tranzacție: rândul în
    Postgres și fișierul în stocare. Codul are grijă ca ele să nu se despartă, dar
    un restore le poate reface din două momente diferite — o bază de aseară peste
    o stocare de azi-dimineață arată perfect și îi lipsesc documente.

    De aceea comanda asta există: este **pasul de verificare al oricărei
    restaurări**, nu o curățenie. Nu scrie și nu șterge nimic; spune doar ce nu se
    potrivește, și iese cu cod diferit de zero dacă a găsit ceva.

    Rulare:

        uv run python -m app.cli check-storage
    """
    from app.models.document import Document
    from app.services.storage.base import ObjectNotFoundError
    from app.services.storage.factory import build_storage_provider

    storage = build_storage_provider()
    checked = missing = mismatched = 0
    problems: list[str] = []

    with session_scope() as session:
        documents = session.scalars(
            select(Document).where(Document.deleted_at.is_(None)).order_by(Document.received_at)
        )
        for document in documents:
            # Originalul întotdeauna; copia din arhivă doar dacă documentul a ajuns
            # acolo. Cele două sunt fișiere diferite, iar oricare poate lipsi.
            keys = [("original", document.storage_key)]
            if document.archive_key:
                keys.append(("arhivă", document.archive_key))

            for label, key in keys:
                checked += 1
                try:
                    size = storage.size(key)
                except ObjectNotFoundError:
                    missing += 1
                    if len(problems) < PROBLEMS_SHOWN:
                        problems.append(f"  LIPSĂ    {document.id} ({label})")
                    continue
                # Doar originalul are dimensiunea scrisă în rând; arhiva este o
                # copie a lui, deci aceeași dimensiune.
                if size != document.file_size:
                    mismatched += 1
                    if len(problems) < PROBLEMS_SHOWN:
                        problems.append(
                            f"  MĂRIME   {document.id} ({label}): "
                            f"{size} pe disc, {document.file_size} în baza de date"
                        )

    print(f"fișiere verificate : {checked}")
    print(f"lipsă              : {missing}")
    print(f"dimensiune greșită : {mismatched}")
    for line in problems:
        print(line)
    if missing + mismatched > PROBLEMS_SHOWN:
        print(f"  ... și încă {missing + mismatched - PROBLEMS_SHOWN}")

    if missing or mismatched:
        sys.exit("Baza de date și stocarea nu se potrivesc.")
    print("Baza de date și stocarea se potrivesc.")


def add_client() -> None:
    """Adaugă un client într-o bază de producție.

    **De ce există.** Aplicația nu are, deliberat, ecrane de creare a clienților:
    CRM-ul este de citire, iar drumul de scriere sunt documentele. Consecința, pe
    care auditul de producție a găsit-o, este că un cabinet nou nu putea adăuga
    **niciun** client: `seed-dev` refuză să ruleze în producție (și bine face —
    datele lui sunt inventate), iar prin interfață nu există niciun drum. Fără
    clienți, nu se poate lega niciun dosar din OneDrive și niciun email nu poate fi
    atribuit.

    Comanda nu înlocuiește ecranul care ar trebui să existe. Deblochează prima
    folosire, atât.

    **Emailul de contact contează mai mult decât pare.** El este cheia după care
    un atașament primit ajunge la clientul potrivit (§8). Un client fără contact
    primește documente doar prin dosarul lui din OneDrive.
    """
    from app.models.client import Client, Contact

    name = input("denumirea clientului: ").strip()
    if not name:
        sys.exit("Denumirea este obligatorie.")

    tax_id = input("CUI (gol dacă nu se știe încă): ").strip() or None
    email = input("email de contact (gol dacă nu se știe): ").strip().lower() or None
    if email and "@" not in email:
        sys.exit("Adresă de email invalidă.")

    with session_scope() as session:
        organizations = list(session.scalars(select(Organization)))
        if not organizations:
            sys.exit("Nu există niciun cabinet. Rulează întâi `create-admin`.")
        if len(organizations) > 1:
            sys.exit("Baza are mai multe cabinete; comanda nu poate alege singură.")
        organization = organizations[0]

        if tax_id is not None:
            # Aceeași regulă ca indexul unic parțial din migrare: unic per cabinet,
            # printre clienții neșterși. O verificăm aici ca să dăm un mesaj, nu o
            # eroare de constrângere.
            existing = session.scalars(
                select(Client).where(
                    Client.organization_id == organization.id,
                    Client.tax_id == tax_id,
                    Client.deleted_at.is_(None),
                )
            ).first()
            if existing is not None:
                sys.exit(f"CUI-ul {tax_id} aparține deja clientului {existing.name!r}.")

        client = Client(
            organization_id=organization.id,
            name=name,
            tax_id=tax_id,
            # ACTIV, nu PROSPECT: cine adaugă un client de la linia de comandă îl
            # adaugă pentru că îi ține contabilitatea.
            status=ClientStatus.ACTIVE,
        )
        session.add(client)
        session.flush()

        if email:
            session.add(
                Contact(
                    client_id=client.id,
                    full_name=name,
                    email=email,
                    is_primary=True,
                    is_active=True,
                )
            )
            session.flush()

        print(f"cabinet : {organization.name}")
        print(f"client  : {client.name} ({client.tax_id or 'fără CUI'})")
        print(f"contact : {email or '— niciunul; documentele vor veni doar din OneDrive'}")


def create_admin() -> None:
    """Primul cont al unei baze de producție.

    Fără ea, o bază proaspăt migrată are roluri și n-are pe nimeni care să se
    autentifice — nu există niciun drum prin interfață care să creeze primul
    utilizator, pentru că orice creare de utilizator cere deja un utilizator.

    `seed-dev` nu ajută: refuză să ruleze în producție, și pe bună dreptate —
    parolele lui sunt publice, iar datele sunt inventate.

    Parola se citește de la tastatură (`getpass`), niciodată dintr-un argument:
    argumentele ajung în istoricul shell-ului și în lista de procese, unde le vede
    oricine este pe aceeași mașină.

    Idempotentă în sensul care contează: dacă adresa există deja, comanda se
    oprește fără să atingă contul. Nu resetează parole — asta ar face din ea o
    portiță, nu o comandă de instalare.
    """
    import getpass

    email = input("email: ").strip().lower()
    if not email or "@" not in email:
        sys.exit("Adresă de email invalidă.")
    full_name = input("nume complet: ").strip()
    if not full_name:
        sys.exit("Numele este obligatoriu.")

    password = getpass.getpass("parolă: ")
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        sys.exit(f"Parola are minimum {MIN_ADMIN_PASSWORD_LENGTH} caractere.")
    if password != getpass.getpass("repetă parola: "):
        sys.exit("Parolele nu coincid.")

    with session_scope() as session:
        if session.scalars(select(User).where(User.email == email)).first():
            sys.exit(f"Există deja un cont cu adresa {email}.")

        role = session.scalars(select(Role).where(Role.code == "ADMIN")).first()
        if role is None:
            sys.exit("Rolurile nu sunt încărcate. Rulează întâi `sync-roles`.")

        organization = session.scalars(select(Organization)).first()
        if organization is None:
            name = input("numele cabinetului: ").strip()
            if not name:
                sys.exit("Numele cabinetului este obligatoriu.")
            organization = Organization(name=name)
            session.add(organization)
            session.flush()

        session.add(
            User(
                organization_id=organization.id,
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                is_active=True,
                roles=[role],
            )
        )
        session.flush()
        # Un cabinet fără tipuri de document nu poate primi niciun fișier.
        types_created = sync_document_types(session, organization)

        print(f"organizație: {organization.name}")
        print(f"administrator: {email}")
        print(f"tipuri de document: {types_created}")


def reset_e2e() -> None:
    """Reconstruiește de la zero baza pe care rulează testele end-to-end.

    Testele E2E pornesc un server adevărat și îl conduc dintr-un browser
    adevărat, deci au nevoie de o bază pe care o pot lăsa murdară. Comanda o
    aruncă și o face din nou: migrări, apoi `seed-dev`.

    **Garda contează mai mult decât comanda.** Un `DROP DATABASE` într-un CLI de
    producție este exact felul de unealtă care distruge o bază reală la o
    variabilă de mediu pusă greșit, așa că numele bazei trebuie să se termine în
    `_e2e`. Fără sufixul acela nu se șterge nimic.
    """
    if settings.is_production:
        sys.exit("reset-e2e nu rulează în producție.")

    target = make_url(settings.database_url)
    name = target.database or ""
    if not name.endswith(E2E_SUFFIX):
        sys.exit(
            f"reset-e2e refuză baza {name!r}: numele trebuie să se termine în "
            f"{E2E_SUFFIX!r}. Pune DATABASE_URL pe baza de E2E."
        )

    admin = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    # Schema se construiește rulând migrările, ca peste tot (§59).
    run_migrations(target)
    seed_dev()
    print(f"baza {name} este gata")


COMMANDS = {
    "sync-roles": sync_roles,
    "seed-dev": seed_dev,
    "create-admin": create_admin,
    "add-client": add_client,
    "recover-processing": recover_processing,
    "check-storage": check_storage,
    "reset-e2e": reset_e2e,
}


def main() -> None:
    # Consola Windows este cp1252 implicit; textul aplicatiei este in romana, cu
    # diacritice. Fara reconfigurare, un simplu print() arunca UnicodeEncodeError
    # si — daca se intampla in interiorul unei tranzactii — o da inapoi.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"utilizare: python -m app.cli [{' | '.join(COMMANDS)}]")
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
