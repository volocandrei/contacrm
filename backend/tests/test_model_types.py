"""Tipurile atributelor după un dus-întors prin baza de date.

Testele care construiesc un obiect în Python și îl verifică imediat nu văd ce
întoarce driverul: obiectul e încă în identity map, cu valorile date de noi.
Bug-urile din clasa asta apar abia în serverul real.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.domain.enums import ClientStatus, TaskPriority, TaskStatus
from app.domain.permissions import RoleCode
from app.models.client import Client
from app.models.organization import Organization
from app.models.task import Task
from app.models.user import Role
from tests.conftest import requires_db

pytestmark = requires_db


def _reload(db: Session, instance: Any) -> Any:
    """Forțează citirea din baza de date, nu din identity map.

    Flush-ul vine primul: cheia primară se generează abia atunci, deci citirea ei
    înainte ar da None.
    """
    db.flush()
    model, pk = type(instance), instance.id
    db.expire_all()
    return db.get(model, pk)


def test_task_status_comes_back_as_the_enum_not_a_string(db: Session) -> None:
    """`task.status is TaskStatus.DONE` trebuie să funcționeze pe un obiect încărcat.

    Cu o coloană `String` simplă, atributul revine ca `str`: comparația cu `is` e
    tăcut falsă și `.value` aruncă AttributeError — exact ce a picat în serverul real.
    """
    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    task = Task(
        organization_id=org.id,
        title="Sarcină",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.URGENT,
        due_date=date(2026, 9, 1),
    )
    db.add(task)

    loaded = _reload(db, task)
    assert isinstance(loaded.status, TaskStatus)
    assert loaded.status is TaskStatus.BLOCKED
    assert loaded.status.value == "BLOCKED"
    assert isinstance(loaded.priority, TaskPriority)
    assert loaded.priority is TaskPriority.URGENT


def test_client_status_comes_back_as_the_enum(db: Session) -> None:
    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    client = Client(organization_id=org.id, name="Alfa SRL", status=ClientStatus.SUSPENDED)
    db.add(client)

    loaded = _reload(db, client)
    assert isinstance(loaded.status, ClientStatus)
    assert loaded.status is ClientStatus.SUSPENDED


def test_role_code_comes_back_as_the_enum(db: Session) -> None:
    role = Role(code=RoleCode.ACCOUNTANT, name="Contabil")
    db.add(role)

    loaded = _reload(db, role)
    assert isinstance(loaded.code, RoleCode)
    assert loaded.code is RoleCode.ACCOUNTANT


def test_datetimes_come_back_timezone_aware(db: Session) -> None:
    """Convenția §71: niciun moment naiv, nicăieri."""
    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    task = Task(
        organization_id=org.id,
        title="Gata",
        status=TaskStatus.DONE,
        completed_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    db.add(task)

    loaded = _reload(db, task)
    assert loaded.created_at.tzinfo is not None
    assert loaded.completed_at is not None
    assert loaded.completed_at.tzinfo is not None


def test_enum_columns_are_still_plain_varchar_in_the_database(db: Session) -> None:
    """Nu folosim tipul ENUM nativ: ar cere o migrare pentru fiecare valoare nouă."""
    rows = db.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'tasks' AND column_name IN ('status', 'priority')"
        )
    ).scalars()
    assert set(rows) == {"character varying"}


def test_the_done_invariant_is_enforced_by_the_database(db: Session) -> None:
    """Aplicația ține invariantul, dar baza de date îl garantează."""
    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    # Savepoint: violarea constrângerii invalideaza tranzactia, iar fixture-ul
    # trebuie sa o poata da inapoi curat la final.
    savepoint = db.begin_nested()
    db.add(Task(organization_id=org.id, title="Incoerentă", status=TaskStatus.DONE))
    try:
        db.flush()
    except sa.exc.IntegrityError as exc:
        assert "completed_at" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("DONE fără completed_at ar fi trebuit respins")
    finally:
        savepoint.rollback()


def test_document_enums_come_back_as_enums(db: Session) -> None:
    """Aceeași capcană ca la sarcini: `Mapped[X]` peste String e doar o adnotare."""
    from app.domain.enums import DocumentSource, DocumentStatus
    from app.models.document import Document

    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    document = Document(
        organization_id=org.id,
        status=DocumentStatus.REVIEW_REQUIRED,
        source=DocumentSource.WHATSAPP,
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size=10,
        sha256_hash="a" * 64,
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    db.add(document)

    loaded = _reload(db, document)
    assert isinstance(loaded.status, DocumentStatus)
    assert loaded.status is DocumentStatus.REVIEW_REQUIRED
    assert isinstance(loaded.source, DocumentSource)
    assert loaded.source is DocumentSource.WHATSAPP
    assert loaded.received_at.tzinfo is not None


def test_document_error_code_round_trips(db: Session) -> None:
    from app.domain.enums import DocumentErrorCode, DocumentSource, DocumentStatus
    from app.models.document import Document

    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    document = Document(
        organization_id=org.id,
        status=DocumentStatus.ERROR,
        source=DocumentSource.UPLOAD,
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size=10,
        sha256_hash="b" * 64,
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        error_code=DocumentErrorCode.OCR_FAILED,
    )
    db.add(document)

    loaded = _reload(db, document)
    assert isinstance(loaded.error_code, DocumentErrorCode)
    assert loaded.error_code is DocumentErrorCode.OCR_FAILED


def test_money_columns_come_back_as_decimal_not_float(db: Session) -> None:
    """Sumele nu trec niciodată printr-un float (§72)."""
    from decimal import Decimal

    from app.domain.enums import DocumentSource, DocumentStatus
    from app.models.document import Document

    org = Organization(name="Cabinet Test SRL")
    db.add(org)
    db.flush()

    document = Document(
        organization_id=org.id,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.UPLOAD,
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size=10,
        sha256_hash="c" * 64,
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        total_amount=Decimal("1190.55"),
    )
    db.add(document)

    loaded = _reload(db, document)
    assert isinstance(loaded.total_amount, Decimal)
    assert loaded.total_amount == Decimal("1190.55")
