"""Ce poate face utilizatorul curent cu un document, chiar acum (§31).

Ecranul de verificare are nevoie să știe ce butoane să activeze. Ar putea deduce
singur — dar atunci regulile ciclului de viață ar exista în două limbaje, iar a
doua copie ar rămâne în urmă tăcut. Așa că le calculează backend-ul, din aceeași
mașină de stări pe care o folosesc și serviciile, și le trimite ca listă.

Lista este **ergonomie**, nu autorizare: fiecare rută își verifică din nou
permisiunea și tranziția. Un client care ignoră lista primește 403 sau 409.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from app.domain.document_state import can_transition
from app.domain.enums import DocumentStatus
from app.domain.permissions import Permission

S = DocumentStatus
P = Permission


class DocumentAction(StrEnum):
    """Numele sunt cele din interfață — `camelCase`, ca restul contractului."""

    EDIT = "edit"
    ASSIGN_CLIENT = "assignClient"
    APPROVE = "approve"
    REJECT = "reject"
    MARK_DUPLICATE = "markDuplicate"
    REPROCESS = "reprocess"
    DOWNLOAD = "download"


def _reachable(current: DocumentStatus, target: DocumentStatus, *, explicit: bool = False) -> bool:
    """Tranziție care chiar schimbă ceva.

    `can_transition` acceptă starea identică — un worker care cere `PROCESSING` pe
    un document deja `PROCESSING` nu greșește. Pentru un buton însă, „ești deja
    acolo" înseamnă că acțiunea nu are ce oferi.
    """
    if current is target:
        return False
    return can_transition(current, target, explicit_reprocess=explicit).allowed


def is_editable(status: DocumentStatus) -> bool:
    """Se mai pot corecta metadatele documentului?

    Nu, dacă a fost arhivat. Numele din arhivă codifică data, tipul, clientul,
    seria și numărul (§10): o corectură făcută pe loc ar lăsa numele să mintă
    despre conținut. Din arhivă se iese doar printr-o reprocesare explicită, care
    reface și numele, și lasă urmă în audit.
    """
    return status is not S.ARCHIVED


def reprocess_check(
    status: DocumentStatus, processing_attempts: int, *, max_attempts: int
) -> tuple[bool, str | None]:
    """Poate documentul să fie trimis din nou la procesare?

    Două condiții, nu una: starea trebuie să permită tranziția explicită, iar
    numărul de încercări trebuie să fie sub limita configurată. Un document care a
    eșuat de trei ori nu se repară a patra oară — reprocesarea la nesfârșit doar
    ascunde problema și consumă provider-ul.

    Aceeași funcție hrănește ruta de reprocesare și lista de acțiuni disponibile,
    ca interfața să nu ofere un buton pe care serverul îl refuză cu 409.
    """
    if processing_attempts >= max_attempts:
        return False, (
            f"Documentul a fost procesat de {processing_attempts} ori; "
            "limita configurată a fost atinsă."
        )
    if not _reachable(status, S.PROCESSING, explicit=True):
        return False, f"Nu se poate reprocesa din starea {status.value}."
    return True, None


def available_actions(
    status: DocumentStatus,
    permissions: Iterable[Permission],
    *,
    processing_attempts: int = 0,
    max_attempts: int,
) -> list[DocumentAction]:
    """Intersecția dintre ce permite starea și ce permite rolul.

    Ordinea este stabilă, ca răspunsurile să nu varieze între cereri identice.
    """
    granted = frozenset(permissions)
    can_read = P.DOCUMENTS_READ in granted
    can_write = P.DOCUMENTS_WRITE in granted
    can_approve = P.DOCUMENTS_APPROVE in granted

    actions: list[DocumentAction] = []

    # Editarea nu trece prin mașina de stări — dar are propria regulă, aceeași pe
    # care o aplică și serviciul: un document arhivat nu se mai corectează pe loc.
    if can_write and is_editable(status):
        actions.append(DocumentAction.EDIT)
        actions.append(DocumentAction.ASSIGN_CLIENT)

    if can_approve and _reachable(status, S.APPROVED):
        actions.append(DocumentAction.APPROVE)
    if can_approve and _reachable(status, S.REJECTED):
        actions.append(DocumentAction.REJECT)
    if can_write and _reachable(status, S.DUPLICATE):
        actions.append(DocumentAction.MARK_DUPLICATE)
    # Reprocesarea este cererea explicită care scoate un document din arhivă — dar
    # numai cât timp ruta ar accepta-o cu adevărat.
    if can_write and reprocess_check(status, processing_attempts, max_attempts=max_attempts)[0]:
        actions.append(DocumentAction.REPROCESS)
    if can_read:
        actions.append(DocumentAction.DOWNLOAD)

    return actions


__all__ = ["DocumentAction", "available_actions", "is_editable", "reprocess_check"]
