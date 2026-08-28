"""Comenzi de administrare.

    uv run python -m app.cli sync-roles     # aduce rolurile/permisiunile la zi
    uv run python -m app.cli seed-dev       # organizație + utilizatori de development

`sync-roles` este idempotentă și trebuie rulată după fiecare schimbare în
`app/domain/permissions.py`: tabelele `roles`/`permissions` sunt administrabile,
dar pornesc de la harta din cod.

`seed-dev` refuză să ruleze în producție. Parolele sunt evident de development.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import session_scope
from app.core.security import hash_password
from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS
from app.domain.permissions import Permission as PermissionCode
from app.models.organization import Organization
from app.models.user import Permission, Role, User

DEV_PASSWORD = "contacrm-dev"

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

        print(f"organizație: {organization.name}")
        print(f"utilizatori creați: {created} (parolă: {DEV_PASSWORD})")


COMMANDS = {"sync-roles": sync_roles, "seed-dev": seed_dev}


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
