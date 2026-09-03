"""Comenzile de administrare care ating o bază de producție.

`add-client` și `check-storage` sunt singurele două care **scriu sau judecă** date
reale în afara aplicației. Amândouă au apărut la auditul de producție, ca răspuns
la două goluri: un cabinet nou nu putea adăuga niciun client, și nimic nu spunea
dacă o restaurare a refăcut coerent și baza, și fișierele.

Testele rulează pe sesiunea de test, nu pe cea a aplicației: `session_scope` din
`app.cli` este înlocuit, altfel comenzile ar scrie în baza de development a celui
care rulează suita. (S-a și întâmplat o dată, la mână, în timpul auditului.)
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.domain.enums import ClientStatus, DocumentSource, DocumentStatus
from app.models.client import Client, Contact
from app.models.document import Document
from app.models.organization import Organization
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def cli_session(db: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """`session_scope` al CLI-ului, legat de sesiunea testului."""

    @contextmanager
    def scope() -> Iterator[Session]:
        yield db
        db.flush()

    monkeypatch.setattr(cli, "session_scope", scope)
    return db


@pytest.fixture
def organization(cli_session: Session) -> Organization:
    org = Organization(name="Cabinet de Test SRL", tax_id=f"RO{uuid.uuid4().int % 10**8:08d}")
    cli_session.add(org)
    cli_session.flush()
    return org


def answers(monkeypatch: pytest.MonkeyPatch, *values: str) -> None:
    """Răspunsurile la `input()`, în ordinea în care comanda le cere."""
    remaining = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(remaining))


# ── add-client ───────────────────────────────────────────────────────────────


class TestAddClient:
    def test_creates_the_client_and_its_contact(
        self, cli_session: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers(monkeypatch, "Client Nou SRL", "RO12345678", "Contact@Exemplu.TEST")
        cli.add_client()

        client = cli_session.scalars(select(Client).where(Client.name == "Client Nou SRL")).one()
        assert client.organization_id == organization.id
        assert client.tax_id == "RO12345678"
        # ACTIV, nu PROSPECT: cine îl adaugă de la linia de comandă îi ține contabilitatea.
        assert client.status is ClientStatus.ACTIVE

        contact = cli_session.scalars(select(Contact).where(Contact.client_id == client.id)).one()
        # Emailul este cheia după care un atașament ajunge la clientul potrivit, iar
        # potrivirea se face pe adresa în litere mici.
        assert contact.email == "contact@exemplu.test"
        assert contact.is_primary

    def test_a_client_without_contact_is_allowed(
        self, cli_session: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un client care trimite doar prin dosarul lui din OneDrive nu are nevoie de email."""
        answers(monkeypatch, "Fara Email SRL", "", "")
        cli.add_client()

        client = cli_session.scalars(select(Client).where(Client.name == "Fara Email SRL")).one()
        assert client.tax_id is None
        assert (
            cli_session.scalars(select(Contact).where(Contact.client_id == client.id)).all() == []
        )

    def test_refuses_a_tax_id_that_already_belongs_to_someone(
        self, cli_session: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Aceeași regulă ca indexul unic parțial, dar cu un mesaj în loc de o eroare de bază."""
        cli_session.add(
            Client(organization_id=organization.id, name="Primul SRL", tax_id="RO99999999")
        )
        cli_session.flush()

        answers(monkeypatch, "Al Doilea SRL", "RO99999999", "")
        with pytest.raises(SystemExit) as exit_info:
            cli.add_client()
        assert "Primul SRL" in str(exit_info.value)

    def test_refuses_when_the_database_holds_more_than_one_office(
        self, cli_session: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Comanda nu are voie să ghicească pentru care cabinet este clientul."""
        cli_session.add(Organization(name="Al Doilea Cabinet SRL"))
        cli_session.flush()

        answers(monkeypatch, "Client Ambiguu SRL", "", "")
        with pytest.raises(SystemExit) as exit_info:
            cli.add_client()
        assert "mai multe cabinete" in str(exit_info.value)

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (("", "", ""), "Denumirea"),
            (("X SRL", "", "fara-arond"), "email"),
        ],
        ids=["fara-denumire", "email-invalid"],
    )
    def test_refuses_invalid_input(
        self,
        cli_session: Session,
        organization: Organization,
        monkeypatch: pytest.MonkeyPatch,
        values: tuple[str, ...],
        expected: str,
    ) -> None:
        answers(monkeypatch, *values)
        with pytest.raises(SystemExit) as exit_info:
            cli.add_client()
        assert expected in str(exit_info.value)


# ── check-storage ────────────────────────────────────────────────────────────


def _seed_document(
    session: Session, organization: Organization, storage: LocalStorageProvider
) -> Document:
    key = f"organizations/{organization.id}/documents/{uuid.uuid4()}/original/source.pdf"
    stored = storage.save(key, io.BytesIO(b"%PDF-1.7\n" + b"0" * 200))
    document = Document(
        organization_id=organization.id,
        status=DocumentStatus.RECEIVED,
        source=DocumentSource.UPLOAD,
        original_filename="factura.pdf",
        storage_key=stored.key,
        mime_type="application/pdf",
        file_size=stored.size,
        sha256_hash=stored.sha256,
        received_at=datetime.now(UTC),
    )
    session.add(document)
    session.flush()
    return document


class TestCheckStorage:
    """Pasul de verificare al oricărei restaurări (§71).

    Baza de date și stocarea sunt două sisteme care nu împart o tranzacție. O copie
    a bazei de aseară peste o stocare de azi-dimineață arată perfect și îi lipsesc
    documente; comanda este singurul lucru care spune asta.
    """

    @pytest.fixture
    def storage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorageProvider:
        provider = LocalStorageProvider(tmp_path)
        monkeypatch.setattr("app.services.storage.factory.build_storage_provider", lambda: provider)
        return provider

    def test_passes_when_every_file_is_where_the_database_says(
        self,
        cli_session: Session,
        organization: Organization,
        storage: LocalStorageProvider,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_document(cli_session, organization, storage)

        cli.check_storage()
        assert "se potrivesc" in capsys.readouterr().out

    def test_fails_when_a_file_is_missing(
        self,
        cli_session: Session,
        organization: Organization,
        storage: LocalStorageProvider,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        document = _seed_document(cli_session, organization, storage)
        storage.delete(document.storage_key)

        with pytest.raises(SystemExit):
            cli.check_storage()

        out = capsys.readouterr().out
        assert "LIPSA" in out.replace("Ă", "A").replace("ă", "a")
        assert str(document.id) in out
