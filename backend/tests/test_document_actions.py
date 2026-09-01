"""Acțiunile disponibile pentru un document (§31).

Lista trimisă interfeței trebuie să spună exact ce ar accepta serverul: dacă
promite un buton pe care ruta îl respinge cu 409, operatorul învață să nu aibă
încredere în interfață. Testele de aici leagă lista de mașina de stări, nu de o a
doua listă scrisă de mână.
"""

from __future__ import annotations

import pytest

from app.domain.document_actions import DocumentAction, available_actions, reprocess_check
from app.domain.document_state import can_transition
from app.domain.enums import DocumentStatus
from app.domain.permissions import ROLE_PERMISSIONS, Permission, RoleCode

ALL_PERMISSIONS = frozenset(Permission)
S = DocumentStatus

# Limita din configurarea implicită; testele care o vizează o dau explicit.
MAX_ATTEMPTS = 3


def actions(
    status: DocumentStatus,
    role: RoleCode = RoleCode.ADMIN,
    *,
    processing_attempts: int = 0,
    max_attempts: int = MAX_ATTEMPTS,
) -> set[DocumentAction]:
    return set(
        available_actions(
            status,
            ROLE_PERMISSIONS[role],
            processing_attempts=processing_attempts,
            max_attempts=max_attempts,
        )
    )


def all_actions(status: DocumentStatus) -> list[DocumentAction]:
    return available_actions(
        status, ALL_PERMISSIONS, processing_attempts=0, max_attempts=MAX_ATTEMPTS
    )


class TestStateGating:
    def test_document_in_review_can_be_approved_rejected_or_marked_duplicate(self) -> None:
        assert {
            DocumentAction.APPROVE,
            DocumentAction.REJECT,
            DocumentAction.MARK_DUPLICATE,
        } <= actions(S.REVIEW_REQUIRED)

    def test_freshly_received_document_cannot_be_approved(self) -> None:
        # Nimic nu a fost citit încă: nu există ce aproba.
        assert DocumentAction.APPROVE not in actions(S.RECEIVED)

    def test_document_being_processed_cannot_be_reprocessed(self) -> None:
        assert DocumentAction.REPROCESS not in actions(S.PROCESSING)

    def test_archived_document_can_only_be_reprocessed(self) -> None:
        available = actions(S.ARCHIVED)
        assert DocumentAction.REPROCESS in available
        assert DocumentAction.APPROVE not in available
        assert DocumentAction.REJECT not in available

    def test_approved_document_is_not_offered_approval_again(self) -> None:
        assert DocumentAction.APPROVE not in actions(S.APPROVED)

    def test_rejected_document_is_not_offered_rejection_again(self) -> None:
        assert DocumentAction.REJECT not in actions(S.REJECTED)

    def test_document_already_marked_duplicate_is_not_offered_it_again(self) -> None:
        assert DocumentAction.MARK_DUPLICATE not in actions(S.DUPLICATE)

    def test_failed_document_can_be_retried_or_rejected(self) -> None:
        available = actions(S.ERROR)
        assert DocumentAction.REPROCESS in available
        assert DocumentAction.REJECT in available


class TestPermissionGating:
    def test_operator_cannot_approve_or_reject(self) -> None:
        available = actions(S.REVIEW_REQUIRED, RoleCode.OPERATOR)
        assert DocumentAction.APPROVE not in available
        assert DocumentAction.REJECT not in available
        # Dar poate corecta câmpurile — asta e munca lui.
        assert DocumentAction.EDIT in available

    def test_viewer_can_only_read(self) -> None:
        assert actions(S.REVIEW_REQUIRED, RoleCode.VIEWER) == {DocumentAction.DOWNLOAD}

    def test_reviewer_can_approve(self) -> None:
        assert DocumentAction.APPROVE in actions(S.REVIEW_REQUIRED, RoleCode.REVIEWER)

    def test_without_read_permission_nothing_is_offered(self) -> None:
        assert available_actions(S.REVIEW_REQUIRED, frozenset(), max_attempts=MAX_ATTEMPTS) == []


class TestConsistencyWithStateMachine:
    """Lista nu are voie să se desprindă de mașina de stări."""

    @pytest.mark.parametrize("status", list(DocumentStatus))
    def test_approve_is_offered_exactly_when_the_transition_is_allowed(
        self, status: DocumentStatus
    ) -> None:
        offered = DocumentAction.APPROVE in all_actions(status)
        reachable = status is not S.APPROVED and can_transition(status, S.APPROVED).allowed
        assert offered is reachable

    @pytest.mark.parametrize("status", list(DocumentStatus))
    def test_reject_is_offered_exactly_when_the_transition_is_allowed(
        self, status: DocumentStatus
    ) -> None:
        offered = DocumentAction.REJECT in all_actions(status)
        reachable = status is not S.REJECTED and can_transition(status, S.REJECTED).allowed
        assert offered is reachable

    @pytest.mark.parametrize("status", list(DocumentStatus))
    def test_order_is_stable(self, status: DocumentStatus) -> None:
        assert all_actions(status) == all_actions(status)


class TestReprocessLimit:
    """Un document care a eșuat de trei ori nu se repară a patra oară."""

    def test_reprocess_is_not_offered_once_the_limit_is_reached(self) -> None:
        assert DocumentAction.REPROCESS not in actions(S.ERROR, processing_attempts=MAX_ATTEMPTS)

    def test_reprocess_is_still_offered_below_the_limit(self) -> None:
        assert DocumentAction.REPROCESS in actions(S.ERROR, processing_attempts=MAX_ATTEMPTS - 1)

    def test_the_refusal_explains_itself(self) -> None:
        allowed, reason = reprocess_check(S.ERROR, MAX_ATTEMPTS, max_attempts=MAX_ATTEMPTS)
        assert not allowed
        assert reason is not None
        assert str(MAX_ATTEMPTS) in reason

    def test_a_state_that_forbids_it_gives_a_different_reason(self) -> None:
        allowed, reason = reprocess_check(S.PROCESSING, 0, max_attempts=MAX_ATTEMPTS)
        assert not allowed
        assert reason is not None
        assert "PROCESSING" in reason
