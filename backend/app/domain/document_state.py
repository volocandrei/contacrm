"""Tranzițiile permise între statusurile unui document (§40).

Statusul unui document contabil nu este un câmp liber: el spune ce s-a întâmplat
cu o probă contabilă. Un document `ARCHIVED` care redevine `PROCESSING` fără o
cerere explicită de reprocesare înseamnă că arhiva s-a schimbat pe tăcute.

Regulile trăiesc aici, nu în endpoint-uri: altfel fiecare rută nouă ar trebui să și
le amintească, iar workerul — care nu trece prin HTTP — nu le-ar avea deloc.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.domain.enums import DocumentStatus

S = DocumentStatus

# Ce tranziții sunt permise, din fiecare stare.
_ALLOWED: Mapping[DocumentStatus, frozenset[DocumentStatus]] = MappingProxyType(
    {
        # Abia primit: poate intra în procesare, sau se dovedește duplicat/nevalid
        # înainte de a ajunge acolo. Un operator care vede un fișier evident
        # nefolositor îl poate respinge fără să aștepte OCR-ul.
        S.RECEIVED: frozenset({S.PROCESSING, S.DUPLICATE, S.ERROR, S.UNMATCHED, S.REJECTED}),
        # În procesare: se termină cu bine, cere om, sau eșuează.
        S.PROCESSING: frozenset({S.REVIEW_REQUIRED, S.APPROVED, S.DUPLICATE, S.ERROR, S.UNMATCHED}),
        # Așteaptă un operator.
        S.REVIEW_REQUIRED: frozenset({S.APPROVED, S.REJECTED, S.DUPLICATE, S.PROCESSING}),
        # Clientul nu a putut fi identificat: atribuirea îl trimite la verificare.
        S.UNMATCHED: frozenset({S.REVIEW_REQUIRED, S.PROCESSING, S.REJECTED, S.DUPLICATE}),
        # Aprobat, dar încă nearhivat fizic.
        S.APPROVED: frozenset({S.ARCHIVED, S.REVIEW_REQUIRED}),
        # Starea finală. Se iese din ea doar prin reprocesare explicită.
        S.ARCHIVED: frozenset({S.PROCESSING}),
        # Respins: poate fi redeschis pentru verificare.
        S.REJECTED: frozenset({S.REVIEW_REQUIRED, S.PROCESSING}),
        # Marcat duplicat din greșeală: se poate reevalua.
        S.DUPLICATE: frozenset({S.REVIEW_REQUIRED, S.PROCESSING}),
        # Eroare de procesare: se reîncearcă.
        S.ERROR: frozenset({S.PROCESSING, S.REJECTED}),
    }
)

# Tranziții care nu se pot face automat: cer o acțiune explicită a unui om.
# `ARCHIVED → PROCESSING` este cazul care contează — rearhivarea tăcută a unui
# document deja arhivat ar rescrie o probă contabilă.
_REQUIRES_EXPLICIT_REPROCESS: frozenset[tuple[DocumentStatus, DocumentStatus]] = frozenset(
    {
        (S.ARCHIVED, S.PROCESSING),
        (S.APPROVED, S.REVIEW_REQUIRED),
    }
)

# Stări din care documentul nu mai avansează de la sine.
TERMINAL_STATUSES: frozenset[DocumentStatus] = frozenset({S.ARCHIVED, S.REJECTED})

# Stări în care un document este vizibil ca „de lucru" pentru operator.
OPEN_STATUSES: frozenset[DocumentStatus] = frozenset(
    {S.RECEIVED, S.PROCESSING, S.REVIEW_REQUIRED, S.UNMATCHED, S.ERROR}
)


class InvalidTransitionError(Exception):
    """Tranziție care ar rupe ciclul de viață al documentului."""

    def __init__(
        self, current: DocumentStatus, target: DocumentStatus, reason: str | None = None
    ) -> None:
        self.current = current
        self.target = target
        detail = reason or "tranziție nepermisă"
        super().__init__(
            f"Documentul nu poate trece din {current.value} în {target.value}: {detail}."
        )


@dataclass(frozen=True, slots=True)
class TransitionCheck:
    allowed: bool
    reason: str | None = None


def can_transition(
    current: DocumentStatus, target: DocumentStatus, *, explicit_reprocess: bool = False
) -> TransitionCheck:
    """Verifică o tranziție fără să arunce — pentru cod care vrea să decidă, nu să eșueze."""
    if current is target:
        # Idempotent: a cere starea în care ești deja nu este o eroare, dar nici o
        # tranziție. Workerul se bazează pe asta ca să nu proceseze de două ori.
        return TransitionCheck(allowed=True, reason="stare neschimbată")

    if target not in _ALLOWED.get(current, frozenset()):
        return TransitionCheck(allowed=False, reason="tranziție nepermisă")

    if (current, target) in _REQUIRES_EXPLICIT_REPROCESS and not explicit_reprocess:
        return TransitionCheck(
            allowed=False,
            reason="cere o cerere explicită de reprocesare",
        )

    return TransitionCheck(allowed=True)


def assert_transition(
    current: DocumentStatus, target: DocumentStatus, *, explicit_reprocess: bool = False
) -> None:
    """Varianta care oprește execuția. De folosit chiar înainte de a schimba starea."""
    check = can_transition(current, target, explicit_reprocess=explicit_reprocess)
    if not check.allowed:
        raise InvalidTransitionError(current, target, check.reason)


def allowed_targets(current: DocumentStatus) -> frozenset[DocumentStatus]:
    return _ALLOWED.get(current, frozenset())


def is_terminal(status: DocumentStatus) -> bool:
    return status in TERMINAL_STATUSES
