"""Detecția duplicatelor (§12).

În M5 doar duplicatul exact: același conținut, deci același SHA-256. Numele
fișierului nu participă — același document poate sosi de două ori cu nume diferite,
iar două documente complet diferite pot avea același nume.

Serviciul este scris ca să poată crește: `find_duplicate` întoarce un rezultat
tipizat cu tipul de potrivire, iar detecția semantică (același client, tip, furnizor,
serie, număr, dată, total) se adaugă ca încă o strategie, fără să schimbe apelanții.

**Un duplicat nu se șterge niciodată automat.** Se păstrează, marcat, pentru că
decizia „chiar este același document?" aparține unui om.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories.document import DocumentRepository


class DuplicateMatch(StrEnum):
    """Cât de sigură este potrivirea."""

    # Același conținut, octet cu octet. Nu există dubiu.
    EXACT_CONTENT = "EXACT_CONTENT"
    # Aceleași date de identificare, conținut diferit. Pentru M5.5+.
    SEMANTIC = "SEMANTIC"


@dataclass(frozen=True, slots=True)
class DuplicateResult:
    original: Document
    match: DuplicateMatch

    @property
    def original_id(self) -> uuid.UUID:
        return self.original.id


class DuplicateDetectionService:
    def __init__(self, session: Session) -> None:
        self.documents = DocumentRepository(session)

    def find_duplicate(
        self,
        organization_id: uuid.UUID,
        *,
        sha256_hash: str,
        exclude_id: uuid.UUID | None = None,
    ) -> DuplicateResult | None:
        """Primul document cu același conținut, din aceeași organizație.

        Căutarea nu traversează organizații: două cabinete pot avea, legitim, exact
        același document.
        """
        original = self.documents.find_by_hash(organization_id, sha256_hash, exclude_id=exclude_id)
        if original is None:
            return None
        return DuplicateResult(original=original, match=DuplicateMatch.EXACT_CONTENT)
