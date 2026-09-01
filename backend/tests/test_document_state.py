"""Mașina de stări a documentului (§40).

Logică pură: nu are nevoie de bază de date, deci rulează întotdeauna.
"""

from __future__ import annotations

import pytest

from app.domain.document_state import (
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    InvalidTransitionError,
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
)
from app.domain.enums import DocumentStatus as S


class TestAllowedTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.RECEIVED, S.PROCESSING),
            (S.PROCESSING, S.REVIEW_REQUIRED),
            (S.PROCESSING, S.APPROVED),
            (S.REVIEW_REQUIRED, S.APPROVED),
            (S.REVIEW_REQUIRED, S.REJECTED),
            (S.APPROVED, S.ARCHIVED),
            (S.UNMATCHED, S.REVIEW_REQUIRED),
            (S.ERROR, S.PROCESSING),
            (S.REJECTED, S.REVIEW_REQUIRED),
            (S.DUPLICATE, S.REVIEW_REQUIRED),
        ],
    )
    def test_normal_flow_is_allowed(self, current: S, target: S) -> None:
        assert can_transition(current, target).allowed
        assert_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (S.RECEIVED, S.ARCHIVED),  # nu se sare peste procesare
            (S.RECEIVED, S.APPROVED),  # nimeni nu aprobă un document neprocesat
            (S.ARCHIVED, S.REJECTED),  # arhiva nu se respinge
            (S.ARCHIVED, S.APPROVED),
            (S.REJECTED, S.ARCHIVED),  # un document respins nu ajunge în arhivă
            (S.DUPLICATE, S.ARCHIVED),
        ],
    )
    def test_arbitrary_jumps_are_refused(self, current: S, target: S) -> None:
        assert not can_transition(current, target).allowed
        with pytest.raises(InvalidTransitionError):
            assert_transition(current, target)


class TestReprocessGuard:
    def test_archived_cannot_silently_return_to_processing(self) -> None:
        """Rearhivarea tăcută ar rescrie o probă contabilă."""
        check = can_transition(S.ARCHIVED, S.PROCESSING)
        assert not check.allowed
        assert check.reason is not None and "reprocesare" in check.reason

    def test_archived_can_be_reprocessed_when_asked_explicitly(self) -> None:
        assert can_transition(S.ARCHIVED, S.PROCESSING, explicit_reprocess=True).allowed
        assert_transition(S.ARCHIVED, S.PROCESSING, explicit_reprocess=True)

    def test_approved_reopening_also_requires_an_explicit_request(self) -> None:
        assert not can_transition(S.APPROVED, S.REVIEW_REQUIRED).allowed
        assert can_transition(S.APPROVED, S.REVIEW_REQUIRED, explicit_reprocess=True).allowed


class TestIdempotence:
    @pytest.mark.parametrize("status", list(S))
    def test_transition_to_the_same_state_is_a_no_op_not_an_error(self, status: S) -> None:
        """Workerul se bazează pe asta ca să nu proceseze de două ori (§39)."""
        check = can_transition(status, status)
        assert check.allowed
        assert check.reason == "stare neschimbată"
        assert_transition(status, status)


class TestInvariants:
    def test_every_status_has_an_entry(self) -> None:
        """Un status fără reguli ar bloca documentul definitiv."""
        for status in S:
            assert allowed_targets(status), f"{status} nu are nicio tranziție definită"

    def test_terminal_statuses_do_not_advance_on_their_own(self) -> None:
        assert is_terminal(S.ARCHIVED)
        assert is_terminal(S.REJECTED)
        # Din arhivă se iese doar prin reprocesare explicită.
        assert allowed_targets(S.ARCHIVED) == frozenset({S.PROCESSING})

    def test_open_and_terminal_do_not_overlap(self) -> None:
        assert not (OPEN_STATUSES & TERMINAL_STATUSES)

    def test_archived_is_reachable_only_from_approved(self) -> None:
        """Nimic nu ajunge în arhivă fără să fi fost aprobat."""
        sources = {status for status in S if S.ARCHIVED in allowed_targets(status)}
        assert sources == {S.APPROVED}

    def test_error_message_names_both_states(self) -> None:
        with pytest.raises(InvalidTransitionError) as caught:
            assert_transition(S.RECEIVED, S.ARCHIVED)
        message = str(caught.value)
        assert "RECEIVED" in message and "ARCHIVED" in message
