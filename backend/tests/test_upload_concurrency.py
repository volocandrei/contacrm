"""Două încărcări simultane ale aceluiași fișier (§21, §55).

**De ce există.** Detecția duplicatelor era o căutare urmată de o inserare, fără
nimic între ele. Sub concurență asta nu decide nimic: două tranzacții se caută una
pe alta înainte ca vreuna să fi comis, nu găsesc nimic, și intră amândouă ca
documente noi. Măsurat pe un server pornit, cu patru încărcări simultane ale
acelorași octeți: în două rulări din trei, **niciunul** dintre cele trei duplicate
nu a fost marcat.

Nu este un caz teoretic. Aceeași factură ajunge la cabinet pe mai multe drumuri
deodată — dosarul din OneDrive, atașamentul de pe email, și omul care o încarcă de
mână — iar sincronizarea și uploadul rulează în procese diferite.

Testul pornește încărcările din fire separate, cu sesiuni și conexiuni proprii.
Un test pe o singură sesiune n-ar fi văzut niciodată problema: acolo a doua
căutare vede rândul pe care tot ea l-a scris.
"""

from __future__ import annotations

import io
import secrets
import threading
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.models.document import Document, DocumentVersion
from app.models.organization import Organization
from app.services.document_upload import DocumentUploadService
from app.services.storage import LocalStorageProvider
from tests.conftest import requires_db

pytestmark = requires_db

PDF = b"%PDF-1.7\n" + b"0" * 512 + b"\n%%EOF"

# Câte încărcări pornesc odată. Trei ar fi de ajuns ca să existe cursa; patru o
# fac vizibilă și când firele nu pornesc perfect simultan.
SIMULTANEOUS = 4


def test_only_one_of_several_simultaneous_identical_uploads_is_the_original(
    db_engine: sa.Engine, tmp_path: Path
) -> None:
    make_session = sessionmaker(bind=db_engine, expire_on_commit=False)
    organization_id = uuid.uuid4()

    with make_session() as setup:
        setup.add(
            Organization(
                id=organization_id,
                name="Cabinet Concurență SRL",
                tax_id=f"RO{uuid.uuid4().int % 10**8:08d}",
            )
        )
        setup.commit()

    storage = LocalStorageProvider(tmp_path)
    # Conținut unic pentru rularea asta: două rulări ale suitei nu trebuie să se
    # vadă una pe alta prin hash.
    content = PDF + secrets.token_bytes(32)

    ready = threading.Barrier(SIMULTANEOUS)
    outcomes: list[bool] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def upload(index: int) -> None:
        try:
            with make_session() as session:
                service = DocumentUploadService(session, storage)
                # Toate firele pleacă din același punct.
                ready.wait(timeout=30)
                result = service.upload(
                    organization_id=organization_id,
                    stream=io.BytesIO(content),
                    original_filename=f"aceeasi-factura-{index}.pdf",
                )
                session.commit()
                with lock:
                    outcomes.append(result.is_duplicate)
        except BaseException as exc:  # se raportează în firul principal
            with lock:
                failures.append(exc)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(SIMULTANEOUS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    try:
        assert not failures, f"o încărcare a eșuat: {failures[0]!r}"
        assert len(outcomes) == SIMULTANEOUS
        assert outcomes.count(False) == 1, (
            "exact una dintre încărcările simultane este originalul; "
            f"restul sunt duplicate. Rezultat: {outcomes}"
        )
    finally:
        _cleanup(make_session, organization_id)


def _cleanup(make_session: sessionmaker[Session], organization_id: uuid.UUID) -> None:
    """Testul își comite datele, deci și le strânge singur."""
    with make_session() as session:
        ids = list(
            session.scalars(
                sa.select(Document.id).where(Document.organization_id == organization_id)
            )
        )
        if ids:
            session.execute(sa.delete(DocumentVersion).where(DocumentVersion.document_id.in_(ids)))
            # Întâi legăturile de duplicat: un document nu poate fi șters cât timp
            # altul îl arată ca original.
            session.execute(
                sa.update(Document)
                .where(Document.id.in_(ids))
                .values(duplicate_of_id=None, is_duplicate=False)
            )
            session.execute(sa.delete(Document).where(Document.id.in_(ids)))
        session.execute(sa.delete(Organization).where(Organization.id == organization_id))
        session.commit()
