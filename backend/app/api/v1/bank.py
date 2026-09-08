"""Extrasele bancare și reconcilierea lor (§11-§15).

Trei lucruri, în ordinea în care le face un cabinet: se **importă** extrasul, se
**caută** ce factură a plătit fiecare rând, se **confirmă**.

**Permisiunile.** Extrasele sunt documente contabile ale clientului, deci se citesc
cu `documents:read` și se scriu cu `documents:write`. Nu au permisiuni proprii: un
operator care poate încărca facturi poate încărca și un extras, iar unul care nu
poate scrie documente nu are ce căuta în reconciliere.

**Ce nu face niciuna dintre rutele astea: nu leagă nimic singură.** `/suggestions`
citește și propune; legătura se scrie numai din `/match`, la cererea explicită a
cuiva. Motivul stă în `app/domain/bank_matching.py`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, client_ip, require_permission
from app.api.route import CommittingRoute
from app.core.errors import ValidationError
from app.domain.enums import BankDirection, BankTransactionStatus, ImportOutcome
from app.domain.permissions import Permission
from app.models.bank import BankStatement, BankTransaction
from app.models.client import Client
from app.models.user import User
from app.schemas.common import ApiModel
from app.services.audit import AuditService
from app.services.bank_import import BankImportService
from app.services.bank_reconciliation import ReconciliationService
from app.services.excel_csv import decode

router = APIRouter(route_class=CommittingRoute, prefix="/bank", tags=["banca"])

BankReader = Annotated[User, require_permission(Permission.DOCUMENTS_READ)]
BankWriter = Annotated[User, require_permission(Permission.DOCUMENTS_WRITE)]


# ── Ce iese ──────────────────────────────────────────────────────────────────


class StatementOut(ApiModel):
    id: uuid.UUID
    client_id: uuid.UUID | None
    client_name: str | None
    bank_name: str | None
    iban: str | None
    statement_number: str | None
    currency: str | None
    period_start: date
    period_end: date
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transaction_count: int
    #: Câte rânduri mai așteaptă un om. Este singurul număr după care se alege
    #: extrasul de deschis.
    open_count: int


class MatchOut(ApiModel):
    """O legătură confirmată: pe ce document, cât, și de ce s-a propus."""

    document_id: uuid.UUID
    document_number: str | None
    amount: Decimal
    confidence: float | None
    reasons: str | None


class TransactionOut(ApiModel):
    id: uuid.UUID
    statement_id: uuid.UUID
    client_id: uuid.UUID | None
    position: int
    booking_date: date
    value_date: date | None
    description: str | None
    amount: Decimal
    currency: str | None
    direction: BankDirection
    counterparty_name: str | None
    counterparty_iban: str | None
    reference: str | None
    status: BankTransactionStatus
    note: str | None
    #: Cât din tranzacție este deja pus pe facturi, și cât a rămas.
    allocated: Decimal
    unallocated: Decimal
    matches: list[MatchOut]


class SuggestionOut(ApiModel):
    """O propunere. **Nu** o legătură — se scrie doar dacă cineva apasă."""

    document_id: uuid.UUID
    document_number: str | None
    document_date: str | None
    partner_name: str | None
    total: Decimal | None
    #: Cât s-ar aloca la apăsare: minimul dintre restul plății și restul facturii.
    amount: Decimal
    score: float
    #: De ce. Fără ele, propunerea nu se poate verifica, deci nu se poate folosi.
    reasons: list[str]


class ImportRowOut(ApiModel):
    line: int
    outcome: ImportOutcome
    amount: str | None
    description: str | None
    note: str | None


class ImportResultOut(ApiModel):
    """Ce s-ar întâmpla (previzualizare) sau ce s-a întâmplat (import)."""

    applied: bool
    statement_id: uuid.UUID | None
    created: int
    skipped: int
    failed: int
    #: Diferența dintre soldul final declarat și cel care iese din tranzacții.
    #: Zero este răspunsul bun; altceva înseamnă că fișierul este incomplet.
    balance_gap: Decimal | None
    rows: list[ImportRowOut]


# ── Ce intră ─────────────────────────────────────────────────────────────────


class MatchIn(ApiModel):
    document_id: uuid.UUID
    #: Gol înseamnă „cât încape": minimul dintre restul plății și restul facturii.
    amount: Decimal | None = None


class IgnoreIn(ApiModel):
    note: str | None = Field(default=None, max_length=512)


class StatementFilters(ApiModel):
    """Filtrele listei de extrase.

    **Model, nu parametri declarați unul câte unul.** Aceia rămân `snake_case`,
    iar contractul este camelCase în ambele direcții: `?clientId=...` trimis de
    interfață nu s-ar potrivi cu `client_id` așteptat de rută, iar FastAPI l-ar
    **ignora în tăcere**. Un filtru ignorat nu dă eroare — răspunde la altă
    întrebare. Aceeași lecție ca la filtrele de rapoarte și la ștergerea unei
    depuneri.
    """

    client_id: uuid.UUID | None = None


class TransactionFilters(ApiModel):
    """Filtrele listei de tranzacții.

    Aici defectul a fost real, nu teoretic: ecranul de bancă cerea
    `?statementId=...`, ruta aștepta `statement_id`, iar parametrul se pierdea.
    Rezultatul: reconcilierea arăta **toate** tranzacțiile cabinetului, nu pe
    cele ale extrasului ales — iar cine bifa „fără nepotriviri" o făcea uitându-se
    la altceva.
    """

    statement_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    status: BankTransactionStatus | None = None


class ImportFilters(ApiModel):
    """Ce se știe despre extras înainte de a-l citi.

    `apply=false` nu scrie nimic: aceeași rută răspunde la „ce s-ar întâmpla" și
    la „fă-o", ca ecranul să nu poată arăta altceva decât face butonul.
    """

    apply: bool = False
    client_id: uuid.UUID | None = None
    iban: str | None = None
    bank_name: str | None = None
    statement_number: str | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None


# ── Rute ─────────────────────────────────────────────────────────────────────


@router.get("/statements", response_model=list[StatementOut])
def list_statements(
    session: DbSession,
    user: BankReader,
    filters: Annotated[StatementFilters, Query()],
) -> list[StatementOut]:
    """Extrasele importate, cel mai recent întâi."""
    stmt = select(BankStatement).where(BankStatement.organization_id == user.organization_id)
    if filters.client_id is not None:
        stmt = stmt.where(BankStatement.client_id == filters.client_id)

    names = {
        row.id: row.name
        for row in session.scalars(
            select(Client).where(Client.organization_id == user.organization_id)
        )
    }

    found = session.scalars(stmt.order_by(BankStatement.period_end.desc())).all()
    return [
        StatementOut(
            id=statement.id,
            client_id=statement.client_id,
            client_name=names.get(statement.client_id) if statement.client_id else None,
            bank_name=statement.bank_name,
            iban=statement.iban,
            statement_number=statement.statement_number,
            currency=statement.currency,
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
            transaction_count=len(statement.transactions),
            open_count=sum(
                1
                for item in statement.transactions
                if item.status
                in (BankTransactionStatus.UNMATCHED, BankTransactionStatus.NEEDS_REVIEW)
            ),
        )
        for statement in found
    ]


@router.post(
    "/statements/import",
    response_model=ImportResultOut,
    status_code=status.HTTP_200_OK,
)
def import_statement(
    session: DbSession,
    user: BankWriter,
    request: Request,
    file: Annotated[UploadFile, File()],
    filters: Annotated[ImportFilters, Query()],
) -> ImportResultOut:
    """Citește un extras. `apply=false` nu scrie nimic — spune doar ce s-ar întâmpla.

    Aceeași funcție pentru previzualizare și pentru import, ca ecranul să nu poată
    arăta altceva decât face butonul.
    """
    text = decode(file.file.read())
    plan = BankImportService(session, user.organization_id).plan(
        text,
        actor=user,
        client_id=filters.client_id,
        iban=filters.iban,
        bank_name=filters.bank_name,
        statement_number=filters.statement_number,
        opening_balance=filters.opening_balance,
        closing_balance=filters.closing_balance,
        apply=filters.apply,
    )

    if filters.apply:
        AuditService(session).record(
            organization_id=user.organization_id,
            action="BANK_STATEMENT_IMPORTED",
            entity_type="BankStatement",
            entity_id=str(plan.statement_id) if plan.statement_id else None,
            user_id=user.id,
            user_name=user.full_name,
            detail=f"{plan.created} tranzacții noi, {plan.skipped} existente",
            ip=client_ip(request),
        )

    return ImportResultOut(
        applied=filters.apply,
        statement_id=plan.statement_id,
        created=plan.created,
        skipped=plan.skipped,
        failed=plan.failed,
        balance_gap=plan.balance_gap,
        rows=[
            ImportRowOut(
                line=row.line,
                outcome=row.outcome,
                amount=row.amount,
                description=row.description,
                note=row.note,
            )
            for row in plan.rows
        ],
    )


#: Câte rânduri poate întoarce o singură cerere de tranzacții.
#:
#: Un extras lunar are zeci, cel mult sute de rânduri; ecranul cere întotdeauna
#: unul anume. Plafonul apără cazul în care cineva cheamă ruta **fără filtru**
#: pe un cabinet cu un an de extrase: fără el, răspunsul ar fi zeci de mii de
#: rânduri, fiecare cu legăturile lui.
MAX_TRANSACTIONS = 10**9


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    session: DbSession,
    user: BankReader,
    filters: Annotated[TransactionFilters, Query()],
) -> list[TransactionOut]:
    """Rândurile din extras, în ordinea din fișier.

    **Nu trunchiază niciodată în tăcere.** Peste `MAX_TRANSACTIONS`, cererea este
    refuzată cu un mesaj care spune ce filtru să pună — o listă tăiată la o mie
    ar arăta exact ca una completă, iar într-o reconciliere bancară rândul care
    lipsește este chiar cel căutat.
    """
    stmt = select(BankTransaction).where(BankTransaction.organization_id == user.organization_id)
    if filters.statement_id is not None:
        stmt = stmt.where(BankTransaction.statement_id == filters.statement_id)
    if filters.client_id is not None:
        stmt = stmt.where(BankTransaction.client_id == filters.client_id)
    if filters.status is not None:
        stmt = stmt.where(BankTransaction.status == filters.status)

    service = ReconciliationService(session, user.organization_id)
    found = session.scalars(
        stmt.order_by(BankTransaction.booking_date, BankTransaction.position)
        # `selectinload`, nu lene: fără el, fiecare rând își cerea singur
        # legăturile — patruzeci de tranzacții însemnau patruzeci de interogări
        # în plus, iar un an de extrase, câteva mii. O interogare, nu N.
        .options(selectinload(BankTransaction.matches))
        .limit(MAX_TRANSACTIONS + 1)
    ).all()

    if len(found) > MAX_TRANSACTIONS:
        raise ValidationError(
            f"Prea multe tranzacții pentru o singură cerere (peste {MAX_TRANSACTIONS}). "
            "Alege un extras sau un client.",
            details={"statementId": ["Filtrează după extras sau după client."]},
        )

    return [_transaction_out(service, item) for item in found]


@router.get("/transactions/{transaction_id}/suggestions", response_model=list[SuggestionOut])
def suggestions(
    session: DbSession, user: BankReader, transaction_id: uuid.UUID
) -> list[SuggestionOut]:
    """Ce facturi ar putea fi plata asta, cu motivele fiecăreia.

    Ruta **citește**. Nimic nu se leagă din ea, oricât de sigură ar fi propunerea.
    """
    service = ReconciliationService(session, user.organization_id)
    transaction = service.transaction(transaction_id)
    return [
        SuggestionOut(
            document_id=item.document_id,
            document_number=item.document_number,
            document_date=item.document_date,
            partner_name=item.partner_name,
            total=item.total,
            amount=item.amount,
            score=item.score,
            reasons=list(item.reasons),
        )
        for item in service.propose(transaction)
    ]


@router.post("/transactions/{transaction_id}/match", response_model=TransactionOut)
def match(
    session: DbSession,
    user: BankWriter,
    request: Request,
    transaction_id: uuid.UUID,
    payload: MatchIn,
) -> TransactionOut:
    """Leagă tranzacția de un document. Confirmarea unui om, nu a sistemului."""
    service = ReconciliationService(session, user.organization_id)
    transaction = service.match(
        transaction_id,
        payload.document_id,
        payload.amount,
        actor=user,
        ip=client_ip(request),
    )
    return _transaction_out(service, transaction)


@router.delete("/transactions/{transaction_id}/match/{document_id}", response_model=TransactionOut)
def unmatch(
    session: DbSession,
    user: BankWriter,
    request: Request,
    transaction_id: uuid.UUID,
    document_id: uuid.UUID,
) -> TransactionOut:
    """Scoate o legătură. Reconcilierea trebuie să fie reversibilă."""
    service = ReconciliationService(session, user.organization_id)
    transaction = service.unmatch(transaction_id, document_id, actor=user, ip=client_ip(request))
    return _transaction_out(service, transaction)


@router.post("/transactions/{transaction_id}/ignore", response_model=TransactionOut)
def ignore(
    session: DbSession,
    user: BankWriter,
    request: Request,
    transaction_id: uuid.UUID,
    payload: IgnoreIn,
) -> TransactionOut:
    """Scoate rândul din lista de lucru, cu un motiv scris.

    Un comision bancar nu este „nepotrivit", este lămurit. Fără starea asta, lista
    nu s-ar goli niciodată — iar o listă care nu se golește nu se mai deschide.
    """
    service = ReconciliationService(session, user.organization_id)
    transaction = service.ignore(transaction_id, payload.note, actor=user, ip=client_ip(request))
    return _transaction_out(service, transaction)


@router.post("/transactions/{transaction_id}/reopen", response_model=TransactionOut)
def reopen(
    session: DbSession, user: BankWriter, request: Request, transaction_id: uuid.UUID
) -> TransactionOut:
    """Readuce în lista de lucru un rând marcat lămurit din greșeală."""
    service = ReconciliationService(session, user.organization_id)
    transaction = service.reopen(transaction_id, actor=user, ip=client_ip(request))
    return _transaction_out(service, transaction)


def _transaction_out(
    service: ReconciliationService, transaction: BankTransaction
) -> TransactionOut:
    numbers = _document_numbers(service, transaction)
    return TransactionOut(
        id=transaction.id,
        statement_id=transaction.statement_id,
        client_id=transaction.client_id,
        position=transaction.position,
        booking_date=transaction.booking_date,
        value_date=transaction.value_date,
        description=transaction.description,
        amount=transaction.amount,
        currency=transaction.currency,
        direction=transaction.direction,
        counterparty_name=transaction.counterparty_name,
        counterparty_iban=transaction.counterparty_iban,
        reference=transaction.reference,
        status=transaction.status,
        note=transaction.note,
        allocated=service.allocated(transaction),
        unallocated=service.unallocated(transaction),
        matches=[
            MatchOut(
                document_id=item.document_id,
                document_number=numbers.get(item.document_id),
                amount=item.amount,
                confidence=item.confidence,
                reasons=item.reasons,
            )
            for item in transaction.matches
        ],
    )


def _document_numbers(
    service: ReconciliationService, transaction: BankTransaction
) -> dict[uuid.UUID, str | None]:
    """Numerele documentelor legate, într-o singură interogare.

    Cerut per legătură, un ecran cu cincizeci de tranzacții ar fi făcut o
    interogare pentru fiecare rând al fiecărei tranzacții.
    """
    from app.models.document import Document

    ids = [item.document_id for item in transaction.matches]
    if not ids:
        return {}
    rows = service.session.execute(
        select(Document.id, Document.document_number).where(Document.id.in_(ids))
    ).all()
    return {row[0]: row[1] for row in rows}


__all__ = ["router"]
