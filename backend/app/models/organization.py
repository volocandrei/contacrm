"""Organizația — rădăcina multi-tenancy-ului (§33).

v1 rulează cu o singură organizație, dar tabelul există de la început pentru ca
`organization_id` din restul schemei să aibă unde referi. Vezi ADR-006.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, uuid_pk


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # CUI-ul firmei de contabilitate. Unic doar când există.
    tax_id: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    def __repr__(self) -> str:
        return f"<Organization {self.name!r}>"
