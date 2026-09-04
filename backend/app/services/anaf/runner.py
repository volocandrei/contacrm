"""Turul automat peste toate organizațiile care au SPV-ul conectat.

`AnafSyncService` sincronizează **o** organizație, într-o sesiune primită. Aici
se adaugă ce lipsea ca să meargă nesupravegheat: cine pornește turul, cu ce
sesiune, și ce se întâmplă când o organizație eșuează.

Aceleași două reguli ca la Microsoft, din aceleași motive: **fiecare organizație
are tranzacția ei** — un cabinet căruia i-a expirat certificatul nu are voie să
dea înapoi facturile intrate deja pentru altul — și **nu propagă excepții**,
pentru că apelantul este un worker, iar o excepție ar pica bătaia întreagă fără
ca cineva să afle de ce.

Încuietoarea este separată de cea a Microsoft, deliberat: cele două sincronizări
nu au nimic în comun și nu au de ce să se aștepte una pe alta.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import session_scope
from app.core.locks import try_lock_organization
from app.core.logging import get_logger
from app.models.anaf import AnafConnection
from app.services.anaf.deps import get_anaf_client
from app.services.anaf.sync import AnafSyncService
from app.services.storage import StorageProvider

logger = get_logger(__name__)

#: Numele încuietorii per organizație. Vezi `app.core.locks`.
SYNC_LOCK = "anaf-sync"


@dataclass(frozen=True, slots=True)
class AnafRunReport:
    organizations: int = 0
    ingested: int = 0
    failed: int = 0
    #: Organizații pe care le sincroniza deja altcineva în momentul bătăii.
    skipped: int = 0


def connected_organizations() -> list[uuid.UUID]:
    """Organizațiile cu SPV-ul conectat. Sesiune proprie, scurtă."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(AnafConnection.organization_id).where(AnafConnection.is_active.is_(True))
            )
        )


def run_anaf_sync(storage: StorageProvider, *, limit: int | None = None) -> AnafRunReport:
    """Un tur peste toate organizațiile conectate la SPV.

    `limit` mărginește câte organizații se ating într-o bătaie. Contează mai mult
    decât la drive: ANAF numără cererile pe zi, iar o împuternicire nouă poate
    avea o lună de facturi în urmă.
    """
    organizations = connected_organizations()
    if limit is not None:
        organizations = organizations[:limit]

    client = get_anaf_client()
    ingested = failed = skipped = 0

    for organization_id in organizations:
        try:
            with session_scope() as session:
                # Un singur tur pe organizație, oricâți apelanți ar bate deodată:
                # două bătăi suprapuse ar cere de două ori aceleași facturi de la
                # ANAF, care le numără. Ce nu apucă acum se ia la bătaia
                # următoare — fereastra fiecărei împuterniciri spune de unde.
                if not try_lock_organization(session, organization_id, SYNC_LOCK):
                    logger.info("anaf_sync_skipped_busy", organization_id=str(organization_id))
                    skipped += 1
                    continue
                report = AnafSyncService(session, storage, client).sync_organization(
                    organization_id
                )
            ingested += report.ingested
            failed += report.failed
        except Exception:
            # O organizație care cade nu oprește restul. Urma rămâne în log; ce
            # este vizibil pentru utilizator se scrie pe conexiune sau pe
            # împuternicire, de către serviciu, înainte să ajungem aici.
            logger.exception("anaf_sync_crashed", organization_id=str(organization_id))
            failed += 1

    if organizations:
        logger.info(
            "anaf_sync_run",
            organizations=len(organizations),
            ingested=ingested,
            failed=failed,
            skipped=skipped,
        )
    return AnafRunReport(
        organizations=len(organizations), ingested=ingested, failed=failed, skipped=skipped
    )


__all__ = ["AnafRunReport", "connected_organizations", "run_anaf_sync"]
