"""Vocabularul de roluri și permisiuni, partajat cu frontend-ul.

Backend-ul este autoritatea (`app/domain/permissions.py`); frontend-ul are o copie
pentru backend-ul simulat și pentru ascunderea butoanelor. Testele astea cad când
cele două se despart — momentul în care un buton ar rămâne vizibil pentru cineva
care nu mai are dreptul, sau invers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.permissions import ROLE_LABEL, ROLE_PERMISSIONS, Permission, RoleCode

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_TS = REPO_ROOT / "frontend" / "src" / "types" / "domain.ts"
STORE_TS = REPO_ROOT / "frontend" / "src" / "api" / "mock" / "store.ts"
LABELS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "labels.ts"


@pytest.fixture(scope="module")
def domain_source() -> str:
    return DOMAIN_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def store_source() -> str:
    return STORE_TS.read_text(encoding="utf-8")


def _block(source: str, pattern: str, what: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    assert match is not None, f"{what} nu a fost găsit — s-a schimbat forma fișierului?"
    return match.group(1)


def _quoted(text: str) -> set[str]:
    return set(re.findall(r'"([a-zA-Z_:]+)"', text))


def test_permission_vocabulary_matches(domain_source: str) -> None:
    frontend = _quoted(_block(domain_source, r"export type Permission =(.*?);", "tipul Permission"))
    backend = {p.value for p in Permission}
    assert frontend == backend, (
        f"doar în frontend: {sorted(frontend - backend)}; "
        f"doar în backend: {sorted(backend - frontend)}"
    )


def test_role_vocabulary_matches(domain_source: str) -> None:
    frontend = _quoted(
        _block(domain_source, r"export const ROLE_CODE = \[(.*?)\] as const;", "ROLE_CODE")
    )
    backend = {r.value for r in RoleCode}
    assert frontend == backend


@pytest.mark.parametrize(
    "role",
    [RoleCode.ACCOUNTANT, RoleCode.OPERATOR, RoleCode.REVIEWER, RoleCode.VIEWER],
)
def test_explicit_role_grants_match(store_source: str, role: RoleCode) -> None:
    """Rolurile cu listă literală în frontend trebuie să aibă exact aceleași drepturi."""
    frontend = _quoted(
        _block(store_source, rf"  {role.value}: \[(.*?)\],\n", f"ROLE_PERMISSIONS.{role.value}")
    )
    backend = {p.value for p in ROLE_PERMISSIONS[role]}
    assert frontend == backend, (
        f"{role.value} — doar în frontend: {sorted(frontend - backend)}; "
        f"doar în backend: {sorted(backend - frontend)}"
    )


def test_super_admin_has_everything() -> None:
    assert ROLE_PERMISSIONS[RoleCode.SUPER_ADMIN] == frozenset(Permission)


def test_only_super_admin_may_delete_documents() -> None:
    """Ștergerea atinge probe contabile (R8) — un singur rol o poate face."""
    holders = {
        role for role, perms in ROLE_PERMISSIONS.items() if Permission.DOCUMENTS_DELETE in perms
    }
    assert holders == {RoleCode.SUPER_ADMIN}


def test_viewer_cannot_write_anything() -> None:
    write_like = {p for p in Permission if p.value.split(":")[1] not in {"read"}}
    assert not (ROLE_PERMISSIONS[RoleCode.VIEWER] & write_like)


def test_approval_is_narrower_than_editing() -> None:
    """Cine poate aproba trebuie să poată și edita — altfel nu poate corecta ce aprobă."""
    for role, perms in ROLE_PERMISSIONS.items():
        if Permission.DOCUMENTS_APPROVE in perms:
            assert Permission.DOCUMENTS_WRITE in perms, role.value


def test_permission_order_is_stable() -> None:
    from app.domain.permissions import sorted_permissions

    assert sorted_permissions(RoleCode.VIEWER) == sorted_permissions(RoleCode.VIEWER)
    assert sorted_permissions(RoleCode.VIEWER) == [
        Permission.CLIENTS_READ,
        Permission.DOCUMENTS_READ,
        Permission.TASKS_READ,
    ]


@pytest.fixture(scope="module")
def labels_source() -> str:
    return LABELS_TS.read_text(encoding="utf-8")


def test_role_names_are_the_same_on_both_sides(labels_source: str) -> None:
    """Rolul se numește la fel în interfață și în răspunsul serverului.

    `/roles` trimite eticheta din backend; ecranele care nu au încă lista de la
    server (formularul de adăugare a unui coleg, de exemplu) o iau din harta din
    frontend. Două nume diferite pentru același rol înseamnă un administrator
    care crede că dă altceva decât dă.
    """
    pattern = r"export const ROLE_LABEL: Record<RoleCode, string> = \{(.*?)\};"
    block = _block(labels_source, pattern, "ROLE_LABEL")
    frontend = dict(re.findall(r'(\w+): "([^"]+)"', block))
    backend = {role.value: ROLE_LABEL[role] for role in RoleCode}
    assert frontend == backend
