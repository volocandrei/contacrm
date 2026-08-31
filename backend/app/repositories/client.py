"""Acces la date pentru CRM.

Fiecare interogare filtrează pe `organization_id` și exclude rândurile șterse logic.
Filtrarea trăiește aici, nu în endpoint (R10): un endpoint care uită `WHERE` scurge
date între organizații, iar un repository care o face din construcție nu poate.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.client import Client, ClientNote, Contact
from app.models.user import User
from app.schemas.client import ClientFilters
from app.schemas.common import PageParams

# Coloanele în care caută bara de căutare — aceleași ca în backendul simulat.
_SEARCHABLE = ("name", "tax_id", "registration_number", "address")


def _normalised(column: Any) -> ColumnElement[str]:
    """Forma în care se compară textul: fără diacritice, litere mici.

    `app_unaccent` este wrapper-ul IMMUTABLE definit în migrare — `unaccent` însuși
    nu poate fi indexat pentru că nu e marcat imutabil.
    """
    return func.app_unaccent(func.lower(func.coalesce(column, "")))


def _escape_like(value: str) -> str:
    """Neutralizează metacaracterele LIKE din textul căutat.

    Fără asta, un utilizator care scrie `%` sau `_` primește potriviri surprinzătoare
    — backendul simulat folosește `includes()`, unde ambele sunt caractere obișnuite.
    Nu este o problemă de injecție (interogarea rămâne parametrizată), ci de corectitudine.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ClientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _base(self, organization_id: uuid.UUID) -> Select[tuple[Client]]:
        return select(Client).where(
            Client.organization_id == organization_id,
            Client.deleted_at.is_(None),
        )

    def _apply_filters(
        self, stmt: Select[tuple[Client]], filters: ClientFilters
    ) -> Select[tuple[Client]]:
        if filters.status is not None:
            stmt = stmt.where(Client.status == filters.status)
        if filters.accountant_id is not None:
            stmt = stmt.where(Client.assigned_accountant_id == filters.accountant_id)
        if filters.q:
            needle = func.concat("%", func.app_unaccent(func.lower(_escape_like(filters.q))), "%")
            stmt = stmt.where(
                or_(
                    *(
                        _normalised(getattr(Client, col)).like(needle, escape="\\")
                        for col in _SEARCHABLE
                    )
                )
            )
        return stmt

    def list(
        self, organization_id: uuid.UUID, filters: ClientFilters, page: PageParams
    ) -> tuple[Sequence[Client], int]:
        stmt = self._apply_filters(self._base(organization_id), filters)

        total = self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )

        rows = self.session.scalars(
            stmt.options(selectinload(Client.tags))
            # Sortare pe forma normalizată: „Șerban" stă lângă „Serban", nu la coadă.
            .order_by(_normalised(Client.name))
            .offset(page.offset)
            .limit(page.page_size)
        ).unique()
        return list(rows), total or 0

    def get(self, organization_id: uuid.UUID, client_id: uuid.UUID) -> Client | None:
        stmt = self._base(organization_id).where(Client.id == client_id)
        return self.session.scalars(stmt.options(selectinload(Client.tags))).first()

    def accountant_names(self, clients: Sequence[Client]) -> dict[uuid.UUID, str]:
        """Numele contabililor atribuiți, într-o singură interogare.

        Interfața le afișează în listă; fără asta ar fi un SELECT per rând.
        """
        ids = {c.assigned_accountant_id for c in clients if c.assigned_accountant_id}
        if not ids:
            return {}
        rows = self.session.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all()
        return {row[0]: row[1] for row in rows}

    def contacts(self, organization_id: uuid.UUID, client_id: uuid.UUID) -> Sequence[Contact]:
        stmt = (
            select(Contact)
            .join(Client, Contact.client_id == Client.id)
            .where(
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
                Contact.client_id == client_id,
                Contact.deleted_at.is_(None),
            )
            # Contactul principal primul, restul alfabetic.
            .order_by(Contact.is_primary.desc(), Contact.full_name)
        )
        return list(self.session.scalars(stmt))

    def notes(self, organization_id: uuid.UUID, client_id: uuid.UUID) -> Sequence[ClientNote]:
        stmt = (
            select(ClientNote)
            .join(Client, ClientNote.client_id == Client.id)
            .where(
                Client.organization_id == organization_id,
                Client.deleted_at.is_(None),
                ClientNote.client_id == client_id,
            )
            # Cea mai recentă notă prima.
            .order_by(ClientNote.created_at.desc())
        )
        return list(self.session.scalars(stmt))


def client_alias() -> type[Client]:
    """Alias pentru interogările care au nevoie de client fără să-l filtreze din nou."""
    return aliased(Client)
