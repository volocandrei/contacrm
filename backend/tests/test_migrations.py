"""Migrările și modelele trebuie să descrie aceeași schemă.

Testele rulează pe o bază construită de `alembic upgrade head`, iar aplicația
citește prin modelele ORM. Dacă cele două se despart — o coloană adăugată în model
fără migrare, sau invers — codul merge în teste și cade în producție, sau merge în
producție cu o coloană pe care nimeni n-o mai creează pe o instalare nouă.
"""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.domain.enums import (
    ClientStatus,
    DocumentSource,
    DocumentStatus,
    IntakeStatus,
    ProcessingJobStatus,
    TaskPriority,
    TaskStatus,
)
from app.models import Base
from app.models.base import enum_check
from tests.conftest import requires_db

pytestmark = requires_db

# Obiecte care există doar în migrări, intenționat: SQLAlchemy nu le poate exprima
# în metadata, deci autogenerate le raportează ca „în plus" la fiecare rulare.
_EXPECTED_ONLY_IN_DATABASE = {
    # Indexuri GIN pe expresie: app_unaccent(lower(...)) gin_trgm_ops
    "ix_clients_name_trgm",
    "ix_documents_supplier_name_trgm",
    "ix_documents_original_filename_trgm",
    "ix_documents_document_number_trgm",
    # Indexuri unice parțiale (au clauză WHERE)
    "uq_clients_organization_id_tax_id",
    "uq_organizations_tax_id",
    "uq_document_intakes_external_ref",
}


def _significant(diff: list) -> list:  # type: ignore[type-arg]
    """Elimină diferențele așteptate, ca testul să nu devină zgomot ignorat."""
    remaining = []
    for entry in diff:
        if isinstance(entry, tuple) and entry[0] in {"remove_index", "remove_constraint"}:
            name = getattr(entry[1], "name", None)
            if name in _EXPECTED_ONLY_IN_DATABASE:
                continue
        remaining.append(entry)
    return remaining


def test_models_and_migrations_describe_the_same_schema(db_engine: sa.Engine) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": False},
        )
        diff = compare_metadata(context, Base.metadata)

    significant = _significant(diff)
    assert significant == [], (
        "Modelele și migrările s-au despărțit. Generează o migrare cu "
        f"`alembic revision --autogenerate`:\n{significant}"
    )


def test_search_helper_normalises_romanian_diacritics(db_engine: sa.Engine) -> None:
    """`app_unaccent` este ce face «Serban» să găsească «Șerban».

    Verificat prin driver, nu prin consola psql — pe Windows consola strică textul
    înainte să ajungă la server și rezultatul pare greșit fără să fie.
    """
    with db_engine.connect() as connection:
        normalised = connection.scalar(
            sa.text("SELECT app_unaccent(lower(:value))"),
            {"value": "Șerbănescu Țară ÎnȘiruit"},
        )
    assert normalised == "serbanescu tara insiruit"


def test_search_helper_is_immutable_so_it_can_be_indexed(db_engine: sa.Engine) -> None:
    with db_engine.connect() as connection:
        volatility = connection.scalar(
            sa.text("SELECT provolatile FROM pg_proc WHERE proname = 'app_unaccent'")
        )
    # 'i' = IMMUTABLE. Fără asta, indexul GIN pe expresie nu poate exista.
    assert volatility == "i"


# ── Constrângerile CHECK care enumeră valori ─────────────────────────────────
#
# `compare_metadata` **nu** compară corpul constrângerilor CHECK. Timp de două
# migrări asta a lăsat modelele să spună altceva decât baza: `documents.source` și
# `document_intakes.source` nu știau de `ONEDRIVE`, iar
# `document_processing_jobs.status` nu știa de `SKIPPED`. Nimic nu s-a plâns.
#
# Testul de aici compară **mulțimea de valori** din constrângerea reală cu enumul
# din cod. Nu compară textul SQL: Postgres rescrie `x IN ('A','B')` ca
# `(x)::text = ANY (ARRAY['A'::character varying, ...])`, deci o comparație de
# șiruri ar cădea pe formatare, nu pe conținut.

_ENUM_BACKED_COLUMNS: list[tuple[str, str, type[StrEnum]]] = [
    ("clients", "status", ClientStatus),
    ("documents", "status", DocumentStatus),
    ("documents", "source", DocumentSource),
    ("document_intakes", "status", IntakeStatus),
    ("document_intakes", "source", DocumentSource),
    ("document_processing_jobs", "status", ProcessingJobStatus),
    ("tasks", "status", TaskStatus),
    ("tasks", "priority", TaskPriority),
]

_QUOTED = re.compile(r"'([^']*)'")


@pytest.mark.parametrize(("table", "column", "enum"), _ENUM_BACKED_COLUMNS)
def test_check_constraints_list_exactly_the_enum_values(
    db_engine: sa.Engine, table: str, column: str, enum: type[StrEnum]
) -> None:
    with db_engine.connect() as connection:
        definition = connection.scalar(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND conname = :name"
            ),
            {"table": table, "name": f"ck_{table}_{column}"},
        )

    assert definition is not None, f"lipsește ck_{table}_{column} din baza migrată"
    assert set(_QUOTED.findall(definition)) == {member.value for member in enum}, (
        f"{table}.{column}: constrângerea din baza de date și {enum.__name__} "
        f"nu enumeră aceleași valori.\n{definition}"
    )

    # Și modelul trebuie să spună tot enumul. Cele două verificări închid lanțul:
    # model == enum (aici) și bază == enum (mai sus), deci model == bază. Fără a
    # doua, o constrângere scrisă de mână în model ar putea rămâne din nou în urmă
    # fără ca nimic să observe.
    declared = [
        c
        for c in Base.metadata.tables[table].constraints
        # Convenția de denumire a fost deja aplicată: numele scurt din model
        # („status") a devenit `ck_<tabel>_<nume>`.
        if isinstance(c, sa.CheckConstraint) and c.name == f"ck_{table}_{column}"
    ]
    assert len(declared) == 1, f"{table}.{column}: aștept exact un CHECK ck_{table}_{column}"
    assert str(declared[0].sqltext) == enum_check(column, enum), (
        f"{table}.{column}: modelul nu derivă constrângerea din {enum.__name__}. "
        "Folosește `enum_check(...)` — o listă scrisă de mână se desparte tăcut."
    )
