"""Sistemul învață de la cine vin documentele (§8).

**Ce se apără, în ordinea gravității.**

1. **Nu învață din propriile potriviri.** Dacă ar face-o, prima potrivire greșită
   s-ar transforma într-o regulă, iar sistemul și-ar amplifica erorile în loc să
   le corecteze. Este defectul cel mai scump posibil aici, fiindcă ar fi tăcut.
2. **Ultima decizie a unui om câștigă.** Un alias mutat înseamnă că cineva a
   corectat; vechea legătură nu are voie să supraviețuiască pe lângă cea nouă.
3. **Granița organizației ține**, ca peste tot.
4. **Se poate desface.** Un alias greșit misrutează lunar; trebuie să existe un
   drum înapoi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DocumentSource, DocumentStatus, IntakeStatus
from app.models.alias import AliasKind, ClientAlias
from app.models.client import Client
from app.models.document import Document, DocumentIntake
from app.models.organization import Organization
from app.models.user import User
from app.services.client_aliases import ClientAliasService, normalize_sender
from tests.conftest import requires_db

pytestmark = requires_db

pytest_plugins = ("tests.test_crm_api",)

SENDER = "contabilitate@alfa.test"


def make_document(
    db: Session, org: Organization, *, sender: str | None, client_id: uuid.UUID | None = None
) -> Document:
    """Un document sosit de undeva, cu recepția lui."""
    document = Document(
        organization_id=org.id,
        client_id=client_id,
        original_filename="factura.pdf",
        storage_key=f"organizations/{org.id}/documents/{uuid.uuid4()}/original/source.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256_hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        source=DocumentSource.EMAIL,
        status=DocumentStatus.UNMATCHED,
        received_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentIntake(
            organization_id=org.id,
            document_id=document.id,
            source=DocumentSource.EMAIL,
            status=IntakeStatus.ACCEPTED,
            sender=sender,
            original_filename="factura.pdf",
            received_at=datetime.now(UTC),
        )
    )
    db.flush()
    return document


class TestWhatItLearns:
    def test_a_human_assignment_teaches_the_sender(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        document = make_document(db, org, sender=SENDER)
        service = ClientAliasService(db)

        learned = service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )

        assert learned == SENDER
        match = service.match(org.id, SENDER)
        assert match is not None
        assert match.client_id == clients[0].id

    def test_a_manual_upload_teaches_nothing(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """Un document urcat de un coleg nu are expeditor extern.

        A lega adresa colegului de un client ar trimite acolo tot ce urcă el.
        """
        document = make_document(db, org, sender=None)

        learned = ClientAliasService(db).learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )

        assert learned is None
        assert db.scalar(select(ClientAlias)) is None

    def test_the_same_decision_twice_teaches_once(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        service = ClientAliasService(db)
        first = make_document(db, org, sender=SENDER)
        service.learn_from_assignment(
            org.id, document_id=first.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()

        second = make_document(db, org, sender=SENDER)
        learned = service.learn_from_assignment(
            org.id, document_id=second.id, client_id=clients[0].id, actor_id=admin.id
        )

        assert learned is None
        assert len(db.scalars(select(ClientAlias)).all()) == 1

    def test_a_correction_moves_the_alias(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """Ultima decizie a unui om câștigă — și contorul repornește.

        Potrivirile de până acum au fost pentru alt client; păstrate, ar face un
        alias corectat să pară verificat de zeci de ori.
        """
        service = ClientAliasService(db)
        first = make_document(db, org, sender=SENDER)
        service.learn_from_assignment(
            org.id, document_id=first.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()
        service.count_match(org.id, SENDER)
        db.flush()

        second = make_document(db, org, sender=SENDER)
        service.learn_from_assignment(
            org.id, document_id=second.id, client_id=clients[1].id, actor_id=admin.id
        )
        db.flush()

        rows = db.scalars(select(ClientAlias)).all()
        assert len(rows) == 1
        assert rows[0].client_id == clients[1].id
        assert rows[0].matched_count == 0

    @pytest.mark.parametrize(
        ("written", "asked"),
        [
            ("Contabilitate@Alfa.TEST", "contabilitate@alfa.test"),
            (" contabilitate@alfa.test ", "Contabilitate@Alfa.Test"),
        ],
    )
    def test_the_address_is_the_same_however_it_was_typed(
        self,
        db: Session,
        org: Organization,
        clients: list[Client],
        admin: User,
        written: str,
        asked: str,
    ) -> None:
        document = make_document(db, org, sender=written)
        service = ClientAliasService(db)
        service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()

        assert service.match(org.id, asked) is not None


class TestWhatItRefuses:
    def test_another_office_learns_nothing(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        document = make_document(db, org, sender=SENDER)
        service = ClientAliasService(db)
        service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()

        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()

        assert service.match(other.id, SENDER) is None

    def test_a_deleted_client_stops_matching(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """Un client șters nu mai primește documente prin ce s-a învățat despre el."""
        document = make_document(db, org, sender=SENDER)
        service = ClientAliasService(db)
        service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()
        clients[0].deleted_at = datetime.now(UTC)
        db.flush()

        assert service.match(org.id, SENDER) is None

    def test_an_empty_address_never_matches(self, db: Session, org: Organization) -> None:
        service = ClientAliasService(db)

        assert service.match(org.id, None) is None
        assert service.match(org.id, "   ") is None


class TestForgetting:
    def test_an_alias_can_be_removed(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """Fără drumul înapoi, un alias greșit ar misruta lunar, tăcut."""
        document = make_document(db, org, sender=SENDER)
        service = ClientAliasService(db)
        service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()
        alias = db.scalars(select(ClientAlias)).one()

        removed = service.forget(org.id, alias.id)
        db.flush()

        assert removed is not None
        assert service.match(org.id, SENDER) is None

    def test_an_alias_of_another_office_is_not_removable(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        document = make_document(db, org, sender=SENDER)
        service = ClientAliasService(db)
        service.learn_from_assignment(
            org.id, document_id=document.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()
        alias = db.scalars(select(ClientAlias)).one()

        other = Organization(name="Cabinet Rival SRL")
        db.add(other)
        db.flush()

        assert service.forget(other.id, alias.id) is None


def test_the_kind_vocabulary_is_closed() -> None:
    """Coloana are un `CHECK`: o valoare nouă cere o migrare, nu doar cod."""
    assert [kind.value for kind in AliasKind] == ["SENDER"]


def test_normalisation_is_idempotent() -> None:
    once = normalize_sender("  Contabilitate@Alfa.RO ")
    assert normalize_sender(once) == once


class TestItDoesNotLearnFromItself:
    """Cel mai scump defect posibil aici — și cel mai tăcut.

    Dacă o potrivire automată ar scrie un alias, prima greșeală ar deveni regulă:
    documentul următor ar fi trimis la același client greșit *pentru că* primul a
    fost trimis acolo. Sistemul ar părea din ce în ce mai sigur pe el exact în
    cazurile în care greșește.
    """

    def test_an_automatic_match_writes_no_alias(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        service = ClientAliasService(db)
        # Un alias învățat de la un om, pentru o adresă.
        first = make_document(db, org, sender=SENDER)
        service.learn_from_assignment(
            org.id, document_id=first.id, client_id=clients[0].id, actor_id=admin.id
        )
        db.flush()
        before = len(db.scalars(select(ClientAlias)).all())

        # Un document nou de la aceeași adresă se potrivește singur…
        match = service.match(org.id, SENDER)
        assert match is not None
        service.count_match(org.id, SENDER)
        db.flush()

        # …dar nu naște nimic nou. Doar contorul crește.
        rows = db.scalars(select(ClientAlias)).all()
        assert len(rows) == before
        assert rows[0].matched_count == 1

    def test_only_the_assignment_path_teaches(
        self, db: Session, org: Organization, clients: list[Client], admin: User
    ) -> None:
        """`match` nu are voie să scrie nimic. Este o citire, și trebuie să rămână.

        Verificarea este pe numărul de rânduri: dacă cineva adaugă „învățăm și
        când potrivim", testul cade aici.
        """
        service = ClientAliasService(db)
        document = make_document(db, org, sender="necunoscut@nimeni.test")

        for _ in range(3):
            assert service.match(org.id, "necunoscut@nimeni.test") is None
        db.flush()

        assert db.scalar(select(ClientAlias)) is None
        # Documentul rămâne neatribuit: nu s-a inventat nicio legătură.
        assert document.client_id is None
