"""Turul automat peste toate organizațiile care au un drive conectat.

`DriveSyncService` sincronizează **o** organizație, într-o sesiune primită.
Aici se adaugă singurul lucru care lipsea ca să meargă nesupravegheat: cine
pornește turul, cu ce sesiune, și ce se întâmplă când o organizație eșuează.

**Fiecare organizație are tranzacția ei.** Un cabinet căruia i-a expirat tokenul
nu are voie să dea înapoi documentele intrate deja pentru altul. Este aceeași
regulă ca la acțiunile în masă pe documente, din același motiv.

**Nu propagă excepții.** Apelantul este un cron sau un worker: dacă ar arunca,
bătaia ar pica întreagă și nimeni nu ar afla de ce.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.microsoft import MicrosoftConnection
from app.services.microsoft.deps import get_drive_client
from app.services.microsoft.drive_sync import DriveSyncService
from app.services.microsoft.mail_sync import MailSyncService
from app.services.storage import StorageProvider

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DriveRunReport:
    organizations: int = 0
    ingested: int = 0
    failed: int = 0


def connected_organizations() -> list[uuid.UUID]:
    """Organizațiile cu un drive activ. Sesiune proprie, scurtă."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(MicrosoftConnection.organization_id).where(
                    MicrosoftConnection.is_active.is_(True)
                )
            )
        )


def run_drive_sync(storage: StorageProvider, *, limit: int | None = None) -> DriveRunReport:
    """Un tur peste toate organizațiile conectate.

    `limit` mărginește câte organizații se ating într-o bătaie: pe o platformă
    cu timp maxim de execuție, un cabinet cu multe dosare nu trebuie să lase
    celelalte cabinete nesincronizate la infinit — următoarea bătaie le ia pe
    ele, pentru că fiecare dosar își ține propriul token delta.
    """
    organizations = connected_organizations()
    if limit is not None:
        organizations = organizations[:limit]

    client = get_drive_client()
    ingested = failed = 0

    for organization_id in organizations:
        try:
            with session_scope() as session:
                drive = DriveSyncService(session, storage, client).sync_organization(
                    organization_id
                )
                # Aceeași sesiune: dosarele și cutia poștală aparțin aceluiași
                # cont, iar un tur care reușește pe jumătate nu are de ce să
                # comite jumătate.
                mail = MailSyncService(session, storage, client).sync_organization(organization_id)
            ingested += drive.ingested + mail.ingested
            failed += drive.failed + mail.failed
        except Exception:
            # O organizație care cade nu oprește restul. Urma rămâne în log; ce
            # este vizibil pentru utilizator se scrie pe conexiune, de către
            # serviciu, înainte să ajungem aici.
            logger.exception("drive_sync_crashed", organization_id=str(organization_id))
            failed += 1

    if organizations:
        logger.info(
            "drive_sync_run",
            organizations=len(organizations),
            ingested=ingested,
            failed=failed,
        )
    return DriveRunReport(organizations=len(organizations), ingested=ingested, failed=failed)


__all__ = ["DriveRunReport", "connected_organizations", "run_drive_sync"]
