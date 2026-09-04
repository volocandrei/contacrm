"""Căutare în conținutul documentelor, nu doar în numele lor

Căutarea din ecranul de documente se uita la patru coloane — numele fișierului,
numele standardizat, furnizorul, numărul — plus numele clientului. Toate sunt
*despre* document. Ce scrie **în** document nu era căutabil, deși textul stă în
`documents.ocr_text` de la M5 și este exact ce caută un contabil: „unde e factura
aia de la Orange din mai".

Indexul este GIN peste `to_tsvector`, nu trigram. Sunt unelte diferite pentru
lucruri diferite: trigramul caută bucăți de cuvânt într-un câmp scurt („distrib"
în „Distribuție SRL"), căutarea de text integral caută **cuvinte** într-un
document de câteva pagini, cu rădăcină comună — „facturi" găsește „factura".

Configurarea este `romanian`, aplicată peste `app_unaccent`: textul OCR și ce
scrie omul în căsuța de căutare diferă aproape întotdeauna prin diacritice.
Expresia trebuie să fie identică, până la ultimul apel, cu cea din interogare —
lecția indexurilor trigram, care au stat moarte fiindcă interogarea împacheta
coloana într-un `coalesce` pe care indexul nu îl avea.

Fără `coalesce` nici aici, din același motiv: `to_tsvector(...)` peste `NULL` dă
`NULL`, iar `NULL @@ interogare` nu este adevărat — adică exact ce trebuie
pentru un document care încă nu are text.

Revision ID: 8f3d61c47a92
Revises: 5c4a1f8e2b73
Create Date: 2026-09-04 16:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f3d61c47a92"
down_revision: str | None = "5c4a1f8e2b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_documents_ocr_text_fts"

#: Expresia indexată. `app/repositories/document.py` o compune identic; dacă cele
#: două se despart, indexul rămâne, dar nu îl mai folosește nimeni.
EXPRESSION = "to_tsvector('romanian', app_unaccent(ocr_text))"


def upgrade() -> None:
    op.create_index(
        INDEX,
        "documents",
        [sa.text(EXPRESSION)],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="documents")
