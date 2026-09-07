"""Bataia peste cutiile IMAP ale tuturor cabinetelor (§22, §55, §72).

**Ce verifica, si de ce nu se vedea pana acum.** `tests/test_imap_sync.py` verifica
temeinic ce se intampla intr-o cutie: ce se ia, ce se sare, ce se intampla cand
UID-urile se reseteaza. Nimic nu verifica insa **turul**: ce se intampla cand
instalarea are mai multe cabinete si unul dintre ele are o problema.

Raspunsul era prost. Cele trei runnere periodice — OneDrive, ANAF, IMAP — arata
la fel, dar cel de IMAP nu avea nici incuietoarea, nici sesiunea pe cabinet, nici
prinderea exceptiei. O parola de aplicatie schimbata la un singur client oprea
preluarea emailului pentru **toata instalarea**: exceptia urca prin `run_imap_sync`
pana in ruta de cron, iar cabinetele de dupa el nu mai erau atinse. Nici in bataia
urmatoare, fiindca ordinea este aceeasi — deci cabinetul de pe pozitia a doua nu
mai primea niciodata nimic pe email, fara ca ceva sa para stricat la el.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.services.imap import runner as imap_runner
from app.services.imap.sync import ImapMailboxResult, ImapSyncResult, ImapSyncService
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

pytest_plugins = ("tests.test_periods_api",)


@pytest.fixture
def two_offices(db: Session) -> list[uuid.UUID]:
    """Doua cabinete pe aceeasi instalare, in ordinea in care le vede turul."""
    created = []
    for name in ("Cabinetul Care Cade SRL", "Cabinetul De Dupa SRL"):
        organization = Organization(name=name, tax_id=f"RO{uuid.uuid4().int % 10**8:08d}")
        db.add(organization)
        db.flush()
        created.append(organization.id)
    db.commit()
    return created


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "storage")


@pytest.fixture
def runner_sees_the_test_data(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Turul isi face propriile sesiuni; aici le legam de cea a testului.

    Fara asta, `session_scope()` ar deschide o conexiune noua, care nu vede nimic
    din ce a scris testul — tranzactia lui nu este comisa si nu trebuie sa fie.
    """
    from sqlalchemy.orm import sessionmaker

    import app.core.db as core_db

    factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(core_db, "SessionFactory", factory)


def test_one_office_with_a_broken_mailbox_does_not_stop_the_others(
    db: Session,
    two_offices: list[uuid.UUID],
    storage: LocalStorageProvider,
    monkeypatch: pytest.MonkeyPatch,
    runner_sees_the_test_data: None,
) -> None:
    """O parola schimbata la un client nu are voie sa taie emailul tuturor."""
    reached: list[uuid.UUID] = []

    def flaky(self: ImapSyncService, organization_id: uuid.UUID) -> ImapSyncResult:
        reached.append(organization_id)
        if organization_id == two_offices[0]:
            raise OSError("autentificare respinsa de server")
        return ImapSyncResult(
            mailboxes=[
                ImapMailboxResult(
                    mailbox_id=uuid.uuid4(), username="contabil@cabinet.test", ingested=1
                )
            ]
        )

    monkeypatch.setattr(ImapSyncService, "sync_organization", flaky)

    result = imap_runner.run_imap_sync(storage, limit=10)

    # Amandoua au fost incercate...
    assert set(two_offices) <= set(reached)
    # ...si munca celui de-al doilea s-a facut, desi primul a cazut.
    assert result.ingested >= 1


def test_the_runner_locks_each_office_like_its_two_siblings(
    db: Session,
    two_offices: list[uuid.UUID],
    storage: LocalStorageProvider,
    monkeypatch: pytest.MonkeyPatch,
    runner_sees_the_test_data: None,
) -> None:
    """Cine este deja sincronizat se sare, nu se sincronizeaza a doua oara.

    Cronul la cinci minute peste o sincronizare care dureaza sase ar deschide
    aceeasi cutie de doua ori si ar scrie `last_uid` din amandoua — cine comite al
    doilea il suprascrie pe primul, deci cursorul poate sari inapoi.
    """
    busy: set[uuid.UUID] = {two_offices[0]}
    synced: list[uuid.UUID] = []

    def only_the_free_one(session: Session, organization_id: uuid.UUID, purpose: str) -> bool:
        assert purpose == imap_runner.SYNC_LOCK
        return organization_id not in busy

    def record(self: ImapSyncService, organization_id: uuid.UUID) -> ImapSyncResult:
        synced.append(organization_id)
        return ImapSyncResult()

    monkeypatch.setattr(imap_runner, "try_lock_organization", only_the_free_one)
    monkeypatch.setattr(ImapSyncService, "sync_organization", record)

    imap_runner.run_imap_sync(storage, limit=10)

    assert two_offices[0] not in synced
    assert two_offices[1] in synced
