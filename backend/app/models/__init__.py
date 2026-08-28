"""Modelele ORM.

`ALL_MODELS` există ca Alembic să aibă un singur import de făcut: orice model nou
se adaugă aici, altfel autogenerarea nu îl vede și migrarea iese goală.
"""

from __future__ import annotations

from app.models.base import Base
from app.models.organization import Organization

ALL_MODELS = (Organization,)

__all__ = ["ALL_MODELS", "Base", "Organization"]
