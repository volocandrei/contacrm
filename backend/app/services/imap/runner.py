"""Bătaia planificatorului peste cutiile IMAP ale tuturor cabinetelor.

Aceeași formă ca `microsoft/runner.py`: o funcție care își deschide sesiunea, ca
ruta de cron să nu știe nimic despre cutii poștale.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.organization import Organization
from app.services.imap.deps import get_imap_client
from app.services.imap.sync import ImapSyncResult, ImapSyncService
from app.services.storage import StorageProvider

logger = get_logger(__name__)


def run_imap_sync(storage: StorageProvider, *, limit: int) -> ImapSyncResult:
    """Un tur peste cel mult `limit` cabinete.

    Lotul este mic din același motiv ca la drive: o bătaie are timp maxim, iar
    munca începută și abandonată este cea mai proastă variantă. Ce nu apucă acum
    se ia la următoarea — fiecare cutie își ține propriul UID, deci nimic nu se
    pierde.
    """
    result = ImapSyncResult()
    with session_scope() as session:
        service = ImapSyncService(session, storage, get_imap_client())
        organizations = session.scalars(select(Organization.id).limit(limit)).all()
        for organization_id in organizations:
            result.mailboxes.extend(service.sync_organization(organization_id).mailboxes)

    if result.mailboxes:
        logger.info("imap_sync", mailboxes=len(result.mailboxes), ingested=result.ingested)
    return result


__all__ = ["run_imap_sync"]
