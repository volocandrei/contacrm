"""Onorariile cabinetului.

Ecranul răspunde la trei întrebări, în ordinea în care le pune un cabinet la
început de lună: **cât am de încasat, de la cine, și ce a rămas neîncasat din
lunile trecute.**

Permisiunile sunt proprii (`fees:read`, `fees:manage`) și le au doar
administratorii — motivul stă în `app/domain/permissions.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import Field

from app.api.deps import DbSession, require_permission
from app.api.route import CommittingRoute
from app.api.v1.periods import REFERENCE_MONTH
from app.domain.permissions import Permission
from app.models.fee import DEFAULT_CURRENCY, ClientFee
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.fees import Arrear, FeeRow, FeeService, FeeTotals

router = APIRouter(route_class=CommittingRoute, prefix="/fees", tags=["fees"])

FeeReader = Annotated[User, require_permission(Permission.FEES_READ)]
FeeManager = Annotated[User, require_permission(Permission.FEES_MANAGE)]


class FeeRowOut(ApiModel):
    client_id: uuid.UUID
    client_name: str
    configured: Decimal | None
    amount: Decimal | None
    currency: str
    paid_on: date | None
    paid_by_name: str | None
    note: str | None
    is_generated: bool
    is_paid: bool


class FeeTotalsOut(ApiModel):
    currency: str
    billed: Decimal
    collected: Decimal
    outstanding: Decimal


class ArrearOut(ApiModel):
    client_id: uuid.UUID
    client_name: str
    period: str
    amount: Decimal
    currency: str


class FeeMonthOut(ApiModel):
    """Tot ce afișează ecranul, într-un singur răspuns.

    Rândurile, cifrele și restanțele se citesc împreună: trei cereri separate ar
    fi putut ajunge pe ecran în trei stări diferite ale aceleiași luni.
    """

    reference_month: str
    rows: list[FeeRowOut]
    #: Câte o linie pe monedă. Adunarea lor ar da un număr fără sens.
    totals: list[FeeTotalsOut]
    unpaid_clients: int
    arrears: list[ArrearOut]


class ClientFeeOut(ApiModel):
    client_id: uuid.UUID
    amount: Decimal | None
    currency: str
    starts_on: date | None
    note: str | None


class ClientFeeIn(ApiModel):
    """Onorariul convenit. `amount = null` îl șterge."""

    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default=DEFAULT_CURRENCY, min_length=3, max_length=3)
    starts_on: date | None = None
    note: str | None = Field(default=None, max_length=255)


class MonthQuery(ApiModel):
    """Luna, ca model — parametrii declarați unul câte unul rămân `snake_case`."""

    reference_month: str = Field(pattern=REFERENCE_MONTH)


class GenerateIn(ApiModel):
    reference_month: str = Field(pattern=REFERENCE_MONTH)


class PaymentIn(ApiModel):
    client_id: uuid.UUID
    reference_month: str = Field(pattern=REFERENCE_MONTH)
    paid_on: date | None = None
    note: str | None = Field(default=None, max_length=255)


class PaymentKey(ApiModel):
    client_id: uuid.UUID
    reference_month: str = Field(pattern=REFERENCE_MONTH)


def _row_out(row: FeeRow) -> FeeRowOut:
    return FeeRowOut(
        client_id=row.client_id,
        client_name=row.client_name,
        configured=row.configured,
        amount=row.amount,
        currency=row.currency,
        paid_on=row.paid_on,
        paid_by_name=row.paid_by_name,
        note=row.note,
        is_generated=row.is_generated,
        is_paid=row.is_paid,
    )


def _totals_out(totals: FeeTotals) -> FeeTotalsOut:
    return FeeTotalsOut(
        currency=totals.currency,
        billed=totals.billed,
        collected=totals.collected,
        outstanding=totals.outstanding,
    )


def _arrear_out(row: Arrear) -> ArrearOut:
    return ArrearOut(
        client_id=row.client_id,
        client_name=row.client_name,
        period=row.period,
        amount=row.amount,
        currency=row.currency,
    )


def _month_out(service: FeeService, reference_month: str) -> FeeMonthOut:
    """Un singur loc care compune ecranul, ca toate rutele să spună la fel."""
    rows = service.month(reference_month)
    return FeeMonthOut(
        reference_month=reference_month,
        rows=[_row_out(row) for row in rows],
        totals=[_totals_out(item) for item in service.totals(rows)],
        unpaid_clients=service.unpaid_count(rows),
        arrears=[_arrear_out(row) for row in service.arrears(reference_month)],
    )


def _client_fee_out(client_id: uuid.UUID, fee: ClientFee | None) -> ClientFeeOut:
    """Clientul fără onorariu stabilit nu este o eroare, ci starea în care începe."""
    if fee is None:
        return ClientFeeOut(
            client_id=client_id,
            amount=None,
            currency=DEFAULT_CURRENCY,
            starts_on=None,
            note=None,
        )
    return ClientFeeOut(
        client_id=client_id,
        amount=fee.amount,
        currency=fee.currency,
        starts_on=fee.starts_on,
        note=fee.note,
    )


@router.get("", response_model=FeeMonthOut)
def fee_month(
    session: DbSession, user: FeeReader, filters: Annotated[MonthQuery, Query()]
) -> FeeMonthOut:
    return _month_out(FeeService(session, user.organization_id), filters.reference_month)


@router.post("/generate", response_model=FeeMonthOut)
def generate(session: DbSession, user: FeeManager, payload: GenerateIn) -> FeeMonthOut:
    """Deschide luna: creează rândurile lipsă, fără să le atingă pe cele existente."""
    service = FeeService(session, user.organization_id)
    created = service.generate(payload.reference_month, today=datetime.now(UTC).date())

    if created:
        AuditService(session).record(
            organization_id=user.organization_id,
            action="FEES_GENERATED",
            entity_type="FeeEntry",
            entity_id=payload.reference_month,
            user_id=user.id,
            user_name=user.full_name,
            # Câte, nu cât: jurnalul spune cine a făcut ce, nu sumele (§33).
            detail=f"{created} rânduri",
        )
    return _month_out(service, payload.reference_month)


@router.get("/clients/{client_id}", response_model=ClientFeeOut)
def client_fee(session: DbSession, user: FeeReader, client_id: uuid.UUID) -> ClientFeeOut:
    return _client_fee_out(
        client_id, FeeService(session, user.organization_id).for_client(client_id)
    )


@router.put("/clients/{client_id}", response_model=ClientFeeOut)
def set_client_fee(
    session: DbSession, user: FeeManager, client_id: uuid.UUID, payload: ClientFeeIn
) -> ClientFeeOut:
    service = FeeService(session, user.organization_id)
    fee = service.set_for_client(
        client_id,
        amount=payload.amount,
        currency=payload.currency,
        starts_on=payload.starts_on,
        note=payload.note,
    )

    AuditService(session).record(
        organization_id=user.organization_id,
        action="CLIENT_FEE_SET" if fee else "CLIENT_FEE_CLEARED",
        entity_type="Client",
        entity_id=str(client_id),
        user_id=user.id,
        user_name=user.full_name,
    )
    return _client_fee_out(client_id, fee)


@router.post("/payments", response_model=FeeRowOut, status_code=status.HTTP_201_CREATED)
def mark_paid(session: DbSession, user: FeeManager, payload: PaymentIn) -> FeeRowOut:
    """Marchează încasarea. Ziua implicită este azi — cea în care s-a văzut extrasul."""
    service = FeeService(session, user.organization_id)
    service.mark_paid(
        payload.client_id,
        payload.reference_month,
        paid_on=payload.paid_on or datetime.now(UTC).date(),
        user=user,
        note=payload.note,
    )

    AuditService(session).record(
        organization_id=user.organization_id,
        action="FEE_PAID",
        entity_type="FeeEntry",
        entity_id=f"{payload.client_id}:{payload.reference_month}",
        user_id=user.id,
        user_name=user.full_name,
    )
    return _row_out(service.row(payload.client_id, payload.reference_month))


@router.delete("/payments", response_model=FeeRowOut)
def unmark_paid(
    session: DbSession, user: FeeManager, key: Annotated[PaymentKey, Query()]
) -> FeeRowOut:
    """Anulează o încasare marcată din greșeală."""
    service = FeeService(session, user.organization_id)
    service.unmark(key.client_id, key.reference_month)

    AuditService(session).record(
        organization_id=user.organization_id,
        action="FEE_PAYMENT_REMOVED",
        entity_type="FeeEntry",
        entity_id=f"{key.client_id}:{key.reference_month}",
        user_id=user.id,
        user_name=user.full_name,
    )
    return _row_out(service.row(key.client_id, key.reference_month))


__all__ = ["router"]
