"""Stratul de date pentru documente: constrângeri, filtrare, căutare, izolare.

Comportamentul de referință pentru filtre și căutare este backendul simulat din
`frontend/src/api/mock/store.ts`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import DocumentSource, DocumentStatus, IntakeStatus
from app.models.client import Client
from app.models.document import Document, DocumentIntake, DocumentType, DocumentVersion
from app.models.organization import Organization
from app.repositories.document import DocumentRepository, escape_like
from app.schemas.common import PageParams
from app.schemas.document import DocumentFilters
from tests.conftest import requires_db

pytestmark = requires_db


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ── Pregătire ────────────────────────────────────────────────────────────────


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(name="Cabinet Demo SRL")
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def types(db: Session, org: Organization) -> dict[str, DocumentType]:
    created: dict[str, DocumentType] = {}
    for index, seed in enumerate(DEFAULT_DOCUMENT_TYPES):
        row = DocumentType(
            organization_id=org.id,
            code=seed.code,
            label=seed.label,
            sort_order=index,
            required_fields=list(seed.required_fields),
        )
        db.add(row)
        created[seed.code] = row
    db.flush()
    return created


@pytest.fixture
def clients(db: Session, org: Organization) -> dict[str, Client]:
    rows = {
        "alfa": Client(organization_id=org.id, name="Alfa Conta SRL", tax_id="RO1"),
        "serban": Client(organization_id=org.id, name="Șerbănescu Impex SRL", tax_id="RO2"),
    }
    db.add_all(rows.values())
    db.flush()
    return rows


def make_document(
    db: Session,
    org: Organization,
    *,
    filename: str = "factura.pdf",
    content: str | None = None,
    status: DocumentStatus = DocumentStatus.RECEIVED,
    source: DocumentSource = DocumentSource.UPLOAD,
    client: Client | None = None,
    doc_type: DocumentType | None = None,
    supplier: str | None = None,
    number: str | None = None,
    reference_month: str | None = None,
    document_date: date | None = None,
    total: Decimal | None = None,
    confidence: float | None = None,
    review_required: bool = False,
    received_at: datetime | None = None,
    file_size: int = 1024,
    **extra: object,
) -> Document:
    document = Document(
        organization_id=org.id,
        client_id=client.id if client else None,
        document_type_id=doc_type.id if doc_type else None,
        status=status,
        source=source,
        original_filename=filename,
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/file",
        mime_type="application/pdf",
        file_size=file_size,
        sha256_hash=sha(content if content is not None else filename),
        received_at=received_at or datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        supplier_name=supplier,
        document_number=number,
        reference_month=reference_month,
        document_date=document_date,
        total_amount=total,
        ai_extraction_confidence=confidence,
        review_required=review_required,
        **extra,
    )
    db.add(document)
    db.flush()
    return document


# ── Constrângeri de integritate ──────────────────────────────────────────────


class TestDatabaseConstraints:
    """Integritatea nu se bazează pe Pydantic (§61): baza de date o garantează."""

    def _expect_violation(self, db: Session, fragment: str, **kwargs: object) -> None:
        savepoint = db.begin_nested()
        try:
            with pytest.raises(sa.exc.IntegrityError) as caught:
                make_document(db, kwargs.pop("org"), **kwargs)  # type: ignore[arg-type]
            assert fragment in str(caught.value)
        finally:
            savepoint.rollback()

    def test_sha256_must_be_64_characters(self, db: Session, org: Organization) -> None:
        savepoint = db.begin_nested()
        try:
            document = make_document(db, org)
            document.sha256_hash = "prea-scurt"
            with pytest.raises(sa.exc.IntegrityError) as caught:
                db.flush()
            assert "sha256_length" in str(caught.value)
        finally:
            savepoint.rollback()

    def test_file_size_must_be_positive(self, db: Session, org: Organization) -> None:
        self._expect_violation(db, "file_size_positive", org=org, file_size=0)

    def test_reference_month_must_look_like_a_month(self, db: Session, org: Organization) -> None:
        self._expect_violation(db, "reference_month_format", org=org, reference_month="2026-13")

    def test_a_full_date_is_not_a_reference_month(self, db: Session, org: Organization) -> None:
        """Respinsa de lungimea coloanei (7 caractere) inainte chiar de CHECK."""
        savepoint = db.begin_nested()
        try:
            with pytest.raises(sa.exc.DatabaseError):
                make_document(db, org, reference_month="2026-08-14")
        finally:
            savepoint.rollback()

    def test_archived_requires_filename_and_timestamp(self, db: Session, org: Organization) -> None:
        savepoint = db.begin_nested()
        try:
            document = make_document(db, org)
            document.status = DocumentStatus.ARCHIVED
            with pytest.raises(sa.exc.IntegrityError) as caught:
                db.flush()
            assert "archived_has_filename" in str(caught.value)
        finally:
            savepoint.rollback()

    def test_a_duplicate_must_name_its_original(self, db: Session, org: Organization) -> None:
        savepoint = db.begin_nested()
        try:
            document = make_document(db, org)
            document.is_duplicate = True
            with pytest.raises(sa.exc.IntegrityError) as caught:
                db.flush()
            assert "duplicate_has_origin" in str(caught.value)
        finally:
            savepoint.rollback()

    def test_a_document_cannot_be_its_own_duplicate(self, db: Session, org: Organization) -> None:
        savepoint = db.begin_nested()
        try:
            document = make_document(db, org)
            document.is_duplicate = True
            document.duplicate_of_id = document.id
            with pytest.raises(sa.exc.IntegrityError) as caught:
                db.flush()
            assert "duplicate_not_self" in str(caught.value)
        finally:
            savepoint.rollback()

    def test_version_numbers_are_unique_per_document(self, db: Session, org: Organization) -> None:
        document = make_document(db, org)
        common = {
            "document_id": document.id,
            "storage_key": "k",
            "sha256_hash": sha("v"),
            "file_size": 10,
            "mime_type": "application/pdf",
        }
        db.add(DocumentVersion(version_number=1, **common))
        db.flush()

        savepoint = db.begin_nested()
        try:
            db.add(DocumentVersion(version_number=1, **common))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()
        finally:
            savepoint.rollback()


class TestIntakeIdempotency:
    """Același mesaj livrat de două ori nu trebuie să producă două intrări (§6)."""

    def _intake(
        self,
        org: Organization,
        source: DocumentSource = DocumentSource.EMAIL,
        **kwargs: object,
    ) -> DocumentIntake:
        return DocumentIntake(
            organization_id=org.id,
            source=source,
            original_filename="atasament.pdf",
            received_at=datetime.now(UTC),
            **kwargs,
        )

    def test_same_external_reference_is_rejected(self, db: Session, org: Organization) -> None:
        db.add(self._intake(org, external_message_id="msg-1", external_attachment_id="att-1"))
        db.flush()

        savepoint = db.begin_nested()
        try:
            db.add(self._intake(org, external_message_id="msg-1", external_attachment_id="att-1"))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()
        finally:
            savepoint.rollback()

    def test_different_attachments_of_the_same_message_are_allowed(
        self, db: Session, org: Organization
    ) -> None:
        db.add(self._intake(org, external_message_id="msg-2", external_attachment_id="att-1"))
        db.add(self._intake(org, external_message_id="msg-2", external_attachment_id="att-2"))
        db.flush()

    def test_manual_uploads_without_external_ids_are_not_constrained(
        self, db: Session, org: Organization
    ) -> None:
        """Upload-ul manual nu are id-uri externe — acolo idempotența e pe SHA-256."""
        db.add(self._intake(org, source=DocumentSource.UPLOAD))
        db.add(self._intake(org, source=DocumentSource.UPLOAD))
        db.flush()

    def test_an_intake_exists_even_without_a_document(self, db: Session, org: Organization) -> None:
        """«Am primit un fișier» este independent de «avem un document valid» (§5)."""
        intake = self._intake(
            org, status=IntakeStatus.REJECTED, rejection_reason="Format nesuportat"
        )
        db.add(intake)
        db.flush()
        assert intake.document_id is None
        assert intake.status is IntakeStatus.REJECTED


# ── Repository ───────────────────────────────────────────────────────────────


@pytest.fixture
def corpus(
    db: Session, org: Organization, clients: dict[str, Client], types: dict[str, DocumentType]
) -> dict[str, Document]:
    return {
        "alfa_factura": make_document(
            db,
            org,
            filename="factura-alfa.pdf",
            content="a",
            client=clients["alfa"],
            doc_type=types["FACTURA_INTRARE"],
            supplier="Distribuție Rapidă SRL",
            number="F1023",
            reference_month="2026-08",
            document_date=date(2026, 8, 14),
            total=Decimal("1190.00"),
            confidence=0.95,
            status=DocumentStatus.APPROVED,
            received_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        ),
        "serban_bon": make_document(
            db,
            org,
            filename="bon-serban.jpg",
            content="b",
            client=clients["serban"],
            doc_type=types["BON_FISCAL"],
            supplier="Șerban Market SRL",
            number="B77",
            reference_month="2026-07",
            document_date=date(2026, 7, 2),
            total=Decimal("55.50"),
            confidence=0.62,
            review_required=True,
            status=DocumentStatus.REVIEW_REQUIRED,
            source=DocumentSource.WHATSAPP,
            received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        ),
        "orphan": make_document(
            db,
            org,
            filename="scan-necunoscut.pdf",
            content="c",
            status=DocumentStatus.UNMATCHED,
            source=DocumentSource.EMAIL,
            received_at=datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
        ),
        "deleted": make_document(
            db,
            org,
            filename="sters.pdf",
            content="d",
            deleted_at=datetime.now(UTC),
        ),
    }


def repo(db: Session) -> DocumentRepository:
    return DocumentRepository(db)


class TestListing:
    def test_excludes_soft_deleted(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        rows, total = repo(db).list(org.id, DocumentFilters(), PageParams())
        assert total == 3
        assert all(row.document.original_filename != "sters.pdf" for row in rows)

    def test_resolves_client_name_without_extra_queries(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        rows, _ = repo(db).list(org.id, DocumentFilters(), PageParams())
        by_file = {r.document.original_filename: r for r in rows}
        assert by_file["factura-alfa.pdf"].client_name == "Alfa Conta SRL"
        assert by_file["scan-necunoscut.pdf"].client_name is None

    def test_default_sort_is_newest_received_first(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        rows, _ = repo(db).list(org.id, DocumentFilters(), PageParams())
        assert [r.document.original_filename for r in rows] == [
            "scan-necunoscut.pdf",
            "bon-serban.jpg",
            "factura-alfa.pdf",
        ]

    def test_sort_by_total_amount_is_numeric_not_lexicographic(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        """„55.50" < „1190.00" numeric, dar invers ca text."""
        rows, _ = repo(db).list(
            org.id, DocumentFilters(sort="totalAmount", order="asc"), PageParams()
        )
        amounts = [r.document.total_amount for r in rows if r.document.total_amount is not None]
        assert amounts == [Decimal("55.50"), Decimal("1190.00")]

    def test_paginates(self, db: Session, org: Organization, corpus: dict[str, Document]) -> None:
        page_two, total = repo(db).list(org.id, DocumentFilters(), PageParams(page=2, page_size=2))
        assert total == 3
        assert len(page_two) == 1

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            (DocumentFilters(status=[DocumentStatus.UNMATCHED]), {"scan-necunoscut.pdf"}),
            (DocumentFilters(source=DocumentSource.WHATSAPP), {"bon-serban.jpg"}),
            (DocumentFilters(document_type="BON_FISCAL"), {"bon-serban.jpg"}),
            (DocumentFilters(reference_month="2026-08"), {"factura-alfa.pdf"}),
            (DocumentFilters(year=2026), {"factura-alfa.pdf", "bon-serban.jpg"}),
            (DocumentFilters(review_required=True), {"bon-serban.jpg"}),
            (DocumentFilters(date_from=date(2026, 8, 1)), {"factura-alfa.pdf"}),
            (DocumentFilters(date_to=date(2026, 7, 31)), {"bon-serban.jpg"}),
            (DocumentFilters(min_confidence=0.9), {"factura-alfa.pdf"}),
            (DocumentFilters(max_confidence=0.7), {"bon-serban.jpg"}),
        ],
    )
    def test_filters(
        self,
        db: Session,
        org: Organization,
        corpus: dict[str, Document],
        filters: DocumentFilters,
        expected: set[str],
    ) -> None:
        rows, _ = repo(db).list(org.id, filters, PageParams())
        assert {r.document.original_filename for r in rows} == expected

    def test_several_statuses_at_once(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        """Inbox-ul cere «tot ce nu e arhivat»."""
        filters = DocumentFilters(status=[DocumentStatus.UNMATCHED, DocumentStatus.REVIEW_REQUIRED])
        rows, total = repo(db).list(org.id, filters, PageParams())
        assert total == 2
        assert {r.document.status for r in rows} == {
            DocumentStatus.UNMATCHED,
            DocumentStatus.REVIEW_REQUIRED,
        }


class TestSearch:
    @pytest.mark.parametrize(
        "needle",
        ["distributie", "Distribuție", "DISTRIBUTIE", "distribu"],
        ids=["fără-diacritice", "cu-diacritice", "majuscule", "parțial"],
    )
    def test_supplier_search_ignores_diacritics(
        self, db: Session, org: Organization, corpus: dict[str, Document], needle: str
    ) -> None:
        rows, _ = repo(db).list(org.id, DocumentFilters(q=needle), PageParams())
        assert {r.document.original_filename for r in rows} == {"factura-alfa.pdf"}

    def test_searches_client_name_across_the_join(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        """«serban» trebuie să găsească documentul clientului «Șerbănescu»."""
        rows, _ = repo(db).list(org.id, DocumentFilters(q="serban"), PageParams())
        assert {r.document.original_filename for r in rows} == {"bon-serban.jpg"}

    def test_searches_document_number_and_filename(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        assert repo(db).list(org.id, DocumentFilters(q="F1023"), PageParams())[1] == 1
        assert repo(db).list(org.id, DocumentFilters(q="necunoscut"), PageParams())[1] == 1

    @pytest.mark.parametrize("needle", ["%", "_", "%%", "a_a"])
    def test_like_metacharacters_are_literal_text(
        self, db: Session, org: Organization, corpus: dict[str, Document], needle: str
    ) -> None:
        """Cine scrie `%` nu trebuie să primească toate documentele (§63)."""
        _, total = repo(db).list(org.id, DocumentFilters(q=needle), PageParams())
        assert total == 0

    def test_escape_like_is_reversible_for_plain_text(self) -> None:
        assert escape_like("Alfa SRL") == "Alfa SRL"
        assert escape_like("100%") == "100\\%"
        assert escape_like("a_b") == "a\\_b"


class TestSortWhitelist:
    def test_only_whitelisted_fields_are_accepted(self) -> None:
        """Numele de sortare ajunge într-un ORDER BY: nu poate veni liber (§67)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DocumentFilters(sort="total_amount; DROP TABLE documents")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            DocumentFilters(sort="ocr_text")  # type: ignore[arg-type]

    def test_every_whitelisted_field_actually_sorts(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        from app.schemas.document import SORTABLE_FIELDS

        for field in SORTABLE_FIELDS:
            listed, _ = repo(db).list(
                org.id,
                DocumentFilters(sort=field),  # type: ignore[arg-type]
                PageParams(),
            )
            assert len(listed) == 3, field


class TestIsolation:
    def test_documents_of_another_organization_are_invisible(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        make_document(db, other, filename="strain.pdf", content="x")

        rows, total = repo(db).list(org.id, DocumentFilters(), PageParams())
        assert total == 3
        assert all(r.document.original_filename != "strain.pdf" for r in rows)

    def test_get_by_id_from_another_organization_returns_nothing(
        self, db: Session, org: Organization
    ) -> None:
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        foreign = make_document(db, other, filename="strain.pdf", content="y")

        assert repo(db).get(org.id, foreign.id) is None

    def test_duplicate_search_does_not_cross_organizations(
        self, db: Session, org: Organization
    ) -> None:
        """Două cabinete pot avea, legitim, același document."""
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        make_document(db, org, filename="a.pdf", content="acelasi")
        make_document(db, other, filename="b.pdf", content="acelasi")

        found = repo(db).find_by_hash(other.id, sha("acelasi"))
        assert found is not None
        assert found.organization_id == other.id


class TestDuplicatesAndVersions:
    def test_finds_an_earlier_document_with_the_same_content(
        self, db: Session, org: Organization
    ) -> None:
        first = make_document(
            db,
            org,
            filename="a.pdf",
            content="identic",
            received_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        second = make_document(
            db,
            org,
            filename="b.pdf",
            content="identic",
            received_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
        found = repo(db).find_by_hash(org.id, second.sha256_hash, exclude_id=second.id)
        assert found is not None and found.id == first.id

    def test_a_different_filename_is_not_a_different_document(
        self, db: Session, org: Organization
    ) -> None:
        """Numele fișierului nu este identificator (§6)."""
        a = make_document(db, org, filename="factura.pdf", content="acelasi-continut")
        b = make_document(db, org, filename="cu-totul-alt-nume.pdf", content="acelasi-continut")
        assert a.sha256_hash == b.sha256_hash

    def test_version_numbers_increment(self, db: Session, org: Organization) -> None:
        document = make_document(db, org)
        repository = repo(db)
        assert repository.next_version_number(document.id) == 1

        db.add(
            DocumentVersion(
                document_id=document.id,
                version_number=1,
                kind="original",
                storage_key="k1",
                sha256_hash=sha("v1"),
                file_size=10,
                mime_type="application/pdf",
            )
        )
        db.flush()
        assert repository.next_version_number(document.id) == 2

    def test_soft_delete_hides_but_keeps_the_row(self, db: Session, org: Organization) -> None:
        document = make_document(db, org)
        repo(db).soft_delete(document, datetime.now(UTC))
        db.flush()

        assert repo(db).get(org.id, document.id) is None
        assert db.get(Document, document.id) is not None


class TestDocumentTypes:
    def test_lists_active_types_in_order(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        rows = repo(db).list_types(org.id)
        assert [t.code for t in rows][:2] == ["FACTURA_INTRARE", "FACTURA_IESIRE"]
        assert len(rows) == len(DEFAULT_DOCUMENT_TYPES)

    def test_inactive_types_are_hidden_by_default(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        types["CONTRACT"].is_active = False
        db.flush()
        assert "CONTRACT" not in {t.code for t in repo(db).list_types(org.id)}
        assert "CONTRACT" in {t.code for t in repo(db).list_types(org.id, active_only=False)}

    def test_codes_are_unique_per_organization(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        savepoint = db.begin_nested()
        try:
            db.add(DocumentType(organization_id=org.id, code="CONTRACT", label="Duplicat"))
            with pytest.raises(sa.exc.IntegrityError):
                db.flush()
        finally:
            savepoint.rollback()

    def test_two_organizations_may_use_the_same_code(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        other = Organization(name="Alt Cabinet SRL")
        db.add(other)
        db.flush()
        db.add(DocumentType(organization_id=other.id, code="CONTRACT", label="Contract"))
        db.flush()


class TestCounts:
    def test_counts_group_by_status(
        self, db: Session, org: Organization, corpus: dict[str, Document]
    ) -> None:
        counts = repo(db).count_by_status(org.id)
        assert counts[DocumentStatus.UNMATCHED] == 1
        assert counts[DocumentStatus.REVIEW_REQUIRED] == 1
        assert counts[DocumentStatus.APPROVED] == 1
