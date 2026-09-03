"""Identificarea clientului după codul fiscal (§8, §12).

Pasul ăsta economisește cea mai scumpă apăsare de buton din tot sistemul: până
acum fiecare document ajungea `UNMATCHED` și aștepta un om care să aleagă clientul
dintr-o listă.

Tocmai de aceea testele apără la fel de tare cazul în care sistemul **nu** are
voie să decidă. Un document atribuit greșit ajunge în contabilitatea altei firme,
iar acolo nu-l mai caută nimeni — pe când unul rămas neatribuit se vede pe panou.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.domain.document_types import DEFAULT_DOCUMENT_TYPES
from app.domain.enums import ClientStatus, DocumentSource, DocumentStatus, FieldSource
from app.models.client import Client
from app.models.document import Document, DocumentType
from app.models.organization import Organization
from app.services.client_matching import ClientMatcher, MatchRole, normalize_tax_id
from tests.conftest import requires_db

pytestmark = requires_db

OURS = "14399840"
THEIRS = "12345678"


@pytest.fixture
def org(db: Session) -> Organization:
    row = Organization(name="Cabinet Demo SRL")
    db.add(row)
    db.flush()
    return row


def add_client(
    db: Session,
    org: Organization,
    *,
    name: str,
    tax_id: str | None,
    status: ClientStatus = ClientStatus.ACTIVE,
) -> Client:
    row = Client(organization_id=org.id, name=name, tax_id=tax_id, status=status)
    db.add(row)
    db.flush()
    return row


def match(db: Session, org: Organization, *, supplier: str | None, customer: str | None):  # type: ignore[no-untyped-def]
    return ClientMatcher(db, org.id).by_tax_ids(supplier_tax_id=supplier, customer_tax_id=customer)


class TestNormalisation:
    """Aceeași firmă apare cu `RO` pe o factură și fără pe alta."""

    def test_the_vat_prefix_is_not_part_of_the_code(self) -> None:
        assert normalize_tax_id("RO14399840") == normalize_tax_id("14399840")

    def test_separators_are_ignored(self) -> None:
        assert normalize_tax_id("RO 14.399.840") == "14399840"

    def test_leading_zeros_are_not_part_of_the_code(self) -> None:
        assert normalize_tax_id("0014399840") == "14399840"

    def test_nothing_is_nothing(self) -> None:
        assert normalize_tax_id(None) == ""
        assert normalize_tax_id("  ") == ""


class TestFindingTheClient:
    def test_the_client_as_buyer_means_an_incoming_document(
        self, db: Session, org: Organization
    ) -> None:
        client = add_client(db, org, name="Alfa Conta SRL", tax_id=f"RO{OURS}")

        found = match(db, org, supplier=THEIRS, customer=OURS)

        assert found is not None
        assert found.client_id == client.id
        assert found.role is MatchRole.CUSTOMER

    def test_the_client_as_supplier_means_an_outgoing_document(
        self, db: Session, org: Organization
    ) -> None:
        client = add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)

        found = match(db, org, supplier=OURS, customer=THEIRS)

        assert found is not None
        assert found.client_id == client.id
        assert found.role is MatchRole.SUPPLIER

    def test_the_stored_and_the_read_code_may_be_written_differently(
        self, db: Session, org: Organization
    ) -> None:
        """În bază stă `RO10000101`; de pe document se citește `10000101`."""
        add_client(db, org, name="Alfa Conta SRL", tax_id="RO 10.000.101")

        assert match(db, org, supplier=None, customer="10000101") is not None

    def test_an_inactive_client_still_receives_its_documents(
        self, db: Session, org: Organization
    ) -> None:
        """Un document poate sosi și pentru un client devenit inactiv."""
        add_client(db, org, name="Epsilon SRL", tax_id=OURS, status=ClientStatus.INACTIVE)

        assert match(db, org, supplier=None, customer=OURS) is not None

    def test_only_one_side_needs_to_be_known(self, db: Session, org: Organization) -> None:
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        assert match(db, org, supplier=OURS, customer=None) is not None


class TestWhenItRefusesToDecide:
    """Un document atribuit greșit ajunge în contabilitatea altei firme."""

    def test_an_unknown_code_matches_nobody(self, db: Session, org: Organization) -> None:
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        assert match(db, org, supplier="99999999", customer="88888888") is None

    def test_no_codes_at_all(self, db: Session, org: Organization) -> None:
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        assert match(db, org, supplier=None, customer=None) is None

    def test_an_invoice_between_two_of_our_clients_is_left_to_a_human(
        self, db: Session, org: Organization
    ) -> None:
        """Aparține la fel de mult amândurora; alegerea nu este a noastră."""
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        add_client(db, org, name="Beta Service SRL", tax_id=THEIRS)

        assert match(db, org, supplier=OURS, customer=THEIRS) is None

    def test_clients_of_another_organization_are_invisible(self, db: Session) -> None:
        """§72 — identificarea nu are voie să vadă peste graniță."""
        ours = Organization(name="Cabinet A")
        theirs = Organization(name="Cabinet B")
        db.add_all([ours, theirs])
        db.flush()
        add_client(db, theirs, name="Client strain", tax_id=OURS)

        assert match(db, ours, supplier=None, customer=OURS) is None

    def test_a_client_without_a_tax_id_is_not_a_candidate(
        self, db: Session, org: Organization
    ) -> None:
        """Un prospect care nu a trimis încă datele nu se potrivește cu nimic."""
        add_client(db, org, name="Prospect fără CUI", tax_id=None)
        assert match(db, org, supplier=None, customer="") is None


@requires_db
class TestInThePipeline:
    """Ce se schimbă efectiv pe document."""

    @pytest.fixture
    def types(self, db: Session, org: Organization) -> dict[str, DocumentType]:
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

    def make_document(self, db: Session, org: Organization, **fields: object) -> Document:
        document = Document(
            organization_id=org.id,
            status=DocumentStatus.PROCESSING,
            source=DocumentSource.UPLOAD,
            original_filename="factura.pdf",
            storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
            mime_type="application/pdf",
            file_size=512,
            sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            received_at=datetime.now(UTC),
            **fields,
        )
        db.add(document)
        db.flush()
        return document

    def _resolve(
        self,
        db: Session,
        org: Organization,
        document: Document,
        candidates: tuple[str, ...] = ("FACTURA_INTRARE", "FACTURA_IESIRE"),
    ) -> None:
        from app.services.document_processing import DocumentProcessingService
        from app.services.extraction.base import ExtractionResult
        from app.services.extraction.mock import MockDocumentExtractionProvider
        from app.services.storage import LocalStorageProvider

        service = DocumentProcessingService(
            db,
            LocalStorageProvider("./storage"),
            MockDocumentExtractionProvider(),
        )
        result = ExtractionResult(
            provider="test",
            duration_ms=1,
            document_type_candidates=candidates,
        )
        service._match_client(document, result)

    def test_the_client_is_assigned_and_the_direction_follows(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Extracția nu putea spune direcția; sistemul poate, pentru că știe ai cui
        sunt clienții."""
        client = add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(db, org, supplier_tax_id=THEIRS, customer_tax_id=OURS)

        self._resolve(db, org, document)

        assert document.client_id == client.id
        assert document.document_type_id == types["FACTURA_INTRARE"].id

    def test_the_other_direction(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(db, org, supplier_tax_id=OURS, customer_tax_id=THEIRS)

        self._resolve(db, org, document)

        assert document.document_type_id == types["FACTURA_IESIRE"].id

    def test_the_derived_type_says_so(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Nu a citit-o nimeni de pe document și nu a propus-o un model (§22)."""
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(db, org, supplier_tax_id=THEIRS, customer_tax_id=OURS)

        self._resolve(db, org, document)

        assert document.field_metadata["documentType"]["source"] == FieldSource.DERIVED.value

    def test_an_already_assigned_client_is_never_overwritten(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Cine a pus documentul acolo — om sau sistem — a decis deja."""
        chosen = add_client(db, org, name="Ales de om", tax_id="55555555")
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(
            db, org, client_id=chosen.id, supplier_tax_id=THEIRS, customer_tax_id=OURS
        )

        self._resolve(db, org, document)

        assert document.client_id == chosen.id

    def test_without_a_match_nothing_is_touched(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        document = self.make_document(db, org, supplier_tax_id=THEIRS, customer_tax_id=OURS)

        self._resolve(db, org, document)

        assert document.client_id is None
        assert document.document_type_id is None

    def test_a_type_already_set_is_not_replaced(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(
            db,
            org,
            supplier_tax_id=THEIRS,
            customer_tax_id=OURS,
            document_type_id=types["CHITANTA"].id,
        )

        self._resolve(db, org, document)

        assert document.document_type_id == types["CHITANTA"].id

    def test_without_candidates_no_direction_is_invented(
        self, db: Session, org: Organization, types: dict[str, DocumentType]
    ) -> None:
        """Un extras de cont nu devine factură fiindcă i-am găsit clientul."""
        add_client(db, org, name="Alfa Conta SRL", tax_id=OURS)
        document = self.make_document(db, org, supplier_tax_id=THEIRS, customer_tax_id=OURS)

        self._resolve(db, org, document, candidates=())

        assert document.client_id is not None
        assert document.document_type_id is None
