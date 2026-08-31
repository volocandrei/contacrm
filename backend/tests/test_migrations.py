"""Migrările și modelele trebuie să descrie aceeași schemă.

Testele rulează pe o bază construită de `alembic upgrade head`, iar aplicația
citește prin modelele ORM. Dacă cele două se despart — o coloană adăugată în model
fără migrare, sau invers — codul merge în teste și cade în producție, sau merge în
producție cu o coloană pe care nimeni n-o mai creează pe o instalare nouă.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import Base
from tests.conftest import requires_db

pytestmark = requires_db

# Obiecte care există doar în migrări, intenționat: SQLAlchemy nu le poate exprima
# în metadata, deci autogenerate le raportează ca „în plus" la fiecare rulare.
_EXPECTED_ONLY_IN_DATABASE = {
    "ix_clients_name_trgm",  # index GIN pe expresie (app_unaccent(lower(name)))
    "uq_clients_organization_id_tax_id",  # unic parțial: WHERE tax_id IS NOT NULL
    "uq_organizations_tax_id",  # idem
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
