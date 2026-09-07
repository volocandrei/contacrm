"""Bătaia planificatorului peste cutiile IMAP ale tuturor cabinetelor.

Aceeași formă ca `microsoft/runner.py`, și nu din simetrie: cele trei reguli de
mai jos sunt scrise acolo pentru că fiecare a fost plătită o dată.

**Câte o sesiune pe cabinet, nu una peste tot.** O singură tranzacție peste
toate cabinetele înseamnă că o eroare la ultimul anulează și avansul cursorului
la primele — mesaje deja descărcate, marcate ca necitite, luate din nou la
bătaia următoare.

**Un singur tur pe cabinet.** Cronul la cinci minute peste o sincronizare care
durează șase pornește a doua bătaie peste prima: aceeași cutie deschisă de două
ori, aceleași mesaje descărcate de două ori, iar `last_uid` scris de amândouă —
cine comite al doilea îl suprascrie pe primul, deci cursorul poate sări înapoi.

**Un cabinet care cade nu-i oprește pe ceilalți.** O parolă de aplicație
schimbată la un singur client oprea, până acum, preluarea emailului pentru
**toată instalarea**: excepția urca prin `run_imap_sync` până în ruta de cron, iar
cabinetele de după el nu mai erau atinse în acea bătaie. Și în următoarea, fiindcă
ordinea este aceeași.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import session_scope
from app.core.locks import try_lock_organization
from app.core.logging import get_logger
from app.models.organization import Organization
from app.services.imap.deps import get_imap_client
from app.services.imap.sync import ImapSyncResult, ImapSyncService
from app.services.storage import StorageProvider

logger = get_logger(__name__)

SYNC_LOCK = "imap-sync"


def run_imap_sync(storage: StorageProvider, *, limit: int) -> ImapSyncResult:
    """Un tur peste cel mult `limit` cabinete.

    Lotul este mic din același motiv ca la drive: o bătaie are timp maxim, iar
    munca începută și abandonată este cea mai proastă variantă. Ce nu apucă acum
    se ia la următoarea — fiecare cutie își ține propriul UID, deci nimic nu se
    pierde.
    """
    result = ImapSyncResult()
    client = get_imap_client()

    with session_scope() as listing:
        organizations = listing.scalars(select(Organization.id).limit(limit)).all()

    for organization_id in organizations:
        try:
            with session_scope() as session:
                if not try_lock_organization(session, organization_id, SYNC_LOCK):
                    logger.info("imap_sync_skipped_busy", organization_id=str(organization_id))
                    continue
                service = ImapSyncService(session, storage, client)
                result.mailboxes.extend(service.sync_organization(organization_id).mailboxes)
        except Exception:
            # Ce este vizibil pentru utilizator se scrie pe cutia poștală, de
            # către serviciu, înainte să ajungem aici. Aici rămâne urma din log.
            logger.exception("imap_sync_crashed", organization_id=str(organization_id))

    if result.mailboxes:
        logger.info("imap_sync", mailboxes=len(result.mailboxes), ingested=result.ingested)
    return result


__all__ = ["SYNC_LOCK", "run_imap_sync"]
