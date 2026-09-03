"""Rapoartele (§84).

Aceeași permisiune ca documentele, deliberat: un raport este o numărătoare peste
documente, iar cine are voie să le vadă are voie să le și numere. O permisiune
separată ar fi sunat mai riguros și n-ar fi apărat nimic — datele sunt aceleași,
doar agregate.

Agregarea se face în SQL (`ReportService`), nu aici și nici în interfață. Ruta
doar traduce filtre în argumente și rezultatul în JSON.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import DbSession, require_permission
from app.api.v1.periods import REFERENCE_MONTH
from app.core.errors import ValidationError
from app.domain.permissions import Permission
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.report_service import Bucket, ReportService, ReportSummary

router = APIRouter(prefix="/reports", tags=["reports"])

ReportReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]


class BucketOut(ApiModel):
    """O linie de clasament.

    `key` și `label` sunt amândouă `null` când gruparea este „nimic" — document
    fără client, fără tip, fără lună. Interfața decide cum numește absența; dacă
    formularea ar veni și de aici, ar exista două surse pentru același text.
    """

    key: str | None
    label: str | None
    count: int


class ReportSummaryOut(ApiModel):
    total: int
    processed: int
    failed: int
    duplicates: int
    # `null` când nu s-a terminat încă nimic. Zero ar însemna „totul a eșuat".
    success_rate: float | None
    by_status: list[BucketOut]
    by_month: list[BucketOut]
    by_type: list[BucketOut]
    by_client: list[BucketOut]
    client_count: int


class ReportFilters(ApiModel):
    """Model, nu parametri separați: numele din query trebuie să fie camelCase.

    Declarați unul câte unul ar rămâne `snake_case`, iar filtrul ar fi ignorat în
    tăcere — nu o eroare, ci un raport care răspunde la altă întrebare decât cea
    pusă.
    """

    from_month: str | None = Field(default=None, pattern=REFERENCE_MONTH)
    to_month: str | None = Field(default=None, pattern=REFERENCE_MONTH)
    client_id: uuid.UUID | None = None


def _to_bucket(bucket: Bucket) -> BucketOut:
    return BucketOut(key=bucket.key, label=bucket.label, count=bucket.count)


def _to_summary(summary: ReportSummary) -> ReportSummaryOut:
    return ReportSummaryOut(
        total=summary.total,
        processed=summary.processed,
        failed=summary.failed,
        duplicates=summary.duplicates,
        success_rate=summary.success_rate,
        by_status=[_to_bucket(b) for b in summary.by_status],
        by_month=[_to_bucket(b) for b in summary.by_month],
        by_type=[_to_bucket(b) for b in summary.by_type],
        by_client=[_to_bucket(b) for b in summary.by_client],
        client_count=summary.client_count,
    )


@router.get("/summary", response_model=ReportSummaryOut)
def summary(
    session: DbSession,
    user: ReportReader,
    filters: Annotated[ReportFilters, Query()],
) -> ReportSummaryOut:
    if filters.from_month and filters.to_month and filters.from_month > filters.to_month:
        # Un interval întors ar da tăcut zero rezultate, care se citește ca „nu
        # aveți documente" în loc de „ai greșit intervalul".
        raise ValidationError(
            "Luna de început este după luna de sfârșit.",
            details={"fromMonth": ["Trebuie să fie anterioară lunii de sfârșit."]},
        )

    return _to_summary(
        ReportService(session, user.organization_id).summary(
            from_month=filters.from_month,
            to_month=filters.to_month,
            client_id=filters.client_id,
        )
    )
