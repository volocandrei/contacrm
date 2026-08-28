"""Rolurile și permisiunile (§32, ADR-006).

Această hartă este **sursa de adevăr**. Frontend-ul are o copie în
`frontend/src/api/mock/store.ts` (`ROLE_PERMISSIONS`) folosită doar de backend-ul
simulat; `tests/test_contract.py` compară cele două și cade dacă se despart.

Ascunderea unui buton în interfață nu este o măsură de securitate — decizia se ia
aici, la fiecare cerere.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Permission(StrEnum):
    CLIENTS_READ = "clients:read"
    CLIENTS_WRITE = "clients:write"
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_WRITE = "documents:write"
    DOCUMENTS_APPROVE = "documents:approve"
    DOCUMENTS_DELETE = "documents:delete"
    PERIODS_MANAGE = "periods:manage"
    TASKS_READ = "tasks:read"
    TASKS_WRITE = "tasks:write"
    COMMUNICATION_SEND = "communication:send"
    ADMIN_USERS = "admin:users"
    ADMIN_SETTINGS = "admin:settings"
    AUDIT_READ = "audit:read"


class RoleCode(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    ACCOUNTANT = "ACCOUNTANT"
    OPERATOR = "OPERATOR"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"


ROLE_LABEL: Mapping[RoleCode, str] = MappingProxyType(
    {
        RoleCode.SUPER_ADMIN: "Super administrator",
        RoleCode.ADMIN: "Administrator",
        RoleCode.ACCOUNTANT: "Contabil",
        RoleCode.OPERATOR: "Operator",
        RoleCode.REVIEWER: "Verificator",
        RoleCode.VIEWER: "Vizitator",
    }
)

_ALL = tuple(Permission)

# Doar SUPER_ADMIN poate șterge documente: ștergerea atinge probe contabile (R8).
ROLE_PERMISSIONS: Mapping[RoleCode, frozenset[Permission]] = MappingProxyType(
    {
        RoleCode.SUPER_ADMIN: frozenset(_ALL),
        RoleCode.ADMIN: frozenset(p for p in _ALL if p is not Permission.DOCUMENTS_DELETE),
        RoleCode.ACCOUNTANT: frozenset(
            {
                Permission.CLIENTS_READ,
                Permission.DOCUMENTS_READ,
                Permission.DOCUMENTS_WRITE,
                Permission.DOCUMENTS_APPROVE,
                Permission.PERIODS_MANAGE,
                Permission.TASKS_READ,
                Permission.TASKS_WRITE,
                Permission.COMMUNICATION_SEND,
                Permission.AUDIT_READ,
            }
        ),
        RoleCode.OPERATOR: frozenset(
            {
                Permission.CLIENTS_READ,
                Permission.DOCUMENTS_READ,
                Permission.DOCUMENTS_WRITE,
                Permission.TASKS_READ,
                Permission.TASKS_WRITE,
            }
        ),
        RoleCode.REVIEWER: frozenset(
            {
                Permission.CLIENTS_READ,
                Permission.DOCUMENTS_READ,
                Permission.DOCUMENTS_WRITE,
                Permission.DOCUMENTS_APPROVE,
                Permission.TASKS_READ,
            }
        ),
        RoleCode.VIEWER: frozenset(
            {
                Permission.CLIENTS_READ,
                Permission.DOCUMENTS_READ,
                Permission.TASKS_READ,
            }
        ),
    }
)


def permissions_for(role: RoleCode) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def sorted_permissions(role: RoleCode) -> list[Permission]:
    """Ordine stabilă — răspunsurile API nu trebuie să varieze între cereri."""
    return sorted(ROLE_PERMISSIONS[role], key=lambda p: _ALL.index(p))
