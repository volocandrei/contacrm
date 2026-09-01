"""Regulile perioadei contabile (ADR-008, §18, §19).

Două lucruri, amândouă pure:

1. **Din ce se derivă luna contabilă.** Decizia este a ADR-008, nu a codului: implicit
   luna documentului, cu „luna primirii" ca alternativă configurabilă. Fără dată nu se
   derivă nimic.
2. **Când este o lună completă.** Regulile sunt portul contractului din
   `frontend/src/api/mock/seed.ts`; ultimele teste citesc pragurile **direct din
   sursa TypeScript**, ca portul să cadă dacă specificația se schimbă, în loc să
   rămână în urmă în tăcere.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.domain.enums import PeriodStatus
from app.domain.periods import (
    PARTIAL_THRESHOLD,
    ChecklistEntry,
    ReferencePeriodStrategy,
    derive_period_status,
    derive_reference_month,
    is_valid_reference_month,
    missing_entries,
    period_progress,
    split_reference_month,
)

SEED_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "mock" / "seed.ts"


def entry(code: str, expected: int, received: int) -> ChecklistEntry:
    return ChecklistEntry(
        document_type=code,
        document_type_label=code.title(),
        expected_min_count=expected,
        received_count=received,
    )


# ── Din ce se derivă luna ────────────────────────────────────────────────────


class TestDeriveReferenceMonth:
    def test_the_default_is_the_month_on_the_document(self) -> None:
        assert (
            derive_reference_month(
                document_date=date(2026, 8, 30),
                received_at=datetime(2026, 9, 3, tzinfo=UTC),
            )
            == "2026-08"
        )

    def test_the_alternative_is_the_month_it_arrived(self) -> None:
        """Unele cabinete lucrează așa. Este o setare, nu o ramură prin cod."""
        assert (
            derive_reference_month(
                document_date=date(2026, 8, 30),
                received_at=datetime(2026, 9, 3, tzinfo=UTC),
                strategy=ReferencePeriodStrategy.RECEIVED_AT,
            )
            == "2026-09"
        )

    def test_without_a_date_nothing_is_derived(self) -> None:
        """O lună greșită este mai rea decât una absentă: absența se vede."""
        assert (
            derive_reference_month(document_date=None, received_at=datetime(2026, 9, 3, tzinfo=UTC))
            is None
        )

    def test_the_receipt_strategy_also_refuses_to_guess(self) -> None:
        assert (
            derive_reference_month(
                document_date=date(2026, 8, 30),
                received_at=None,
                strategy=ReferencePeriodStrategy.RECEIVED_AT,
            )
            is None
        )

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (date(2026, 1, 1), "2026-01"),
            (date(2026, 12, 31), "2026-12"),
            (date(999, 5, 9), "0999-05"),
        ],
    )
    def test_the_format_is_always_yyyy_mm(self, value: date, expected: str) -> None:
        assert derive_reference_month(document_date=value, received_at=None) == expected

    @pytest.mark.parametrize("good", ["2026-01", "2026-12", "1999-06"])
    def test_valid_months_are_accepted(self, good: str) -> None:
        assert is_valid_reference_month(good)

    @pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "26-01", "", "../..", None])
    def test_anything_else_is_refused(self, bad: str | None) -> None:
        assert not is_valid_reference_month(bad)

    def test_splitting_gives_back_year_and_month(self) -> None:
        assert split_reference_month("2026-08") == (2026, 8)


# ── Când este o lună completă ────────────────────────────────────────────────


class TestProgress:
    def test_an_extra_invoice_does_not_cover_a_missing_statement(self) -> None:
        """Numărul care măsoară progresul este min(primite, cerute), per tip."""
        checklist = [entry("FACTURA_INTRARE", 5, 20), entry("EXTRAS_CONT", 1, 0)]
        progress = period_progress(checklist)
        assert progress.satisfied == 5
        assert progress.expected == 6

    def test_an_empty_checklist_expects_nothing(self) -> None:
        assert period_progress([]) == period_progress([])
        assert period_progress([]).expected == 0

    def test_missing_lists_only_what_is_short(self) -> None:
        checklist = [entry("A", 2, 2), entry("B", 3, 1)]
        assert [item.document_type for item in missing_entries(checklist)] == ["B"]


class TestPeriodStatus:
    def test_a_closed_month_is_finalized_whatever_the_checklist_says(self) -> None:
        assert derive_period_status([entry("A", 5, 0)], 0, is_closed=True) is PeriodStatus.FINALIZED

    def test_nothing_received_means_not_started(self) -> None:
        assert (
            derive_period_status([entry("A", 5, 0)], 0, is_closed=False) is PeriodStatus.NOT_STARTED
        )

    def test_without_a_checklist_nothing_can_be_complete(self) -> None:
        """Dacă nu se așteaptă nimic, luna colectează — nu este „gata"."""
        assert derive_period_status([], 12, is_closed=False) is PeriodStatus.COLLECTING

    def test_complete_requires_every_item_not_a_total(self) -> None:
        """Ăsta este semnalul după care se închide luna. Dacă minte, se închide o
        lună cu documente obligatorii lipsă."""
        almost = [entry("FACTURA_INTRARE", 5, 50), entry("EXTRAS_CONT", 1, 0)]
        assert derive_period_status(almost, 50, is_closed=False) is not PeriodStatus.COMPLETE

        done = [entry("FACTURA_INTRARE", 5, 5), entry("EXTRAS_CONT", 1, 1)]
        assert derive_period_status(done, 6, is_closed=False) is PeriodStatus.COMPLETE

    def test_past_the_threshold_the_month_reads_as_in_progress(self) -> None:
        checklist = [entry("A", 5, 4), entry("B", 5, 3)]  # 7/10
        assert derive_period_status(checklist, 7, is_closed=False) is PeriodStatus.PARTIAL

    def test_below_the_threshold_it_is_still_collecting(self) -> None:
        checklist = [entry("A", 5, 1), entry("B", 5, 1)]  # 2/10
        assert derive_period_status(checklist, 2, is_closed=False) is PeriodStatus.COLLECTING


# ── Contract cu specificația din frontend ────────────────────────────────────


@pytest.fixture(scope="module")
def seed_source() -> str:
    return SEED_TS.read_text(encoding="utf-8")


def test_the_partial_threshold_matches_the_frontend(seed_source: str) -> None:
    """Pragul trăiește într-un singur loc conceptual, chiar dacă în două limbaje."""
    match = re.search(r"satisfied / expected >= ([\d.]+)", seed_source)
    assert match is not None, "pragul PARTIAL nu a fost găsit în mock/seed.ts"
    assert float(match.group(1)) == PARTIAL_THRESHOLD


def test_the_status_ladder_matches_the_frontend(seed_source: str) -> None:
    """Aceleași stări, în aceeași ordine de decizie."""
    block = re.search(r"export function derivePeriodStatus\((.*?)\n\}", seed_source, re.DOTALL)
    assert block is not None, "derivePeriodStatus nu a fost găsit în mock/seed.ts"

    returned = re.findall(r'return "([A-Z_]+)"', block.group(1))
    assert returned == ["FINALIZED", "NOT_STARTED", "COLLECTING", "COMPLETE"]
    assert {status in {s.value for s in PeriodStatus} for status in returned} == {True}


def test_progress_is_capped_the_same_way_in_both(seed_source: str) -> None:
    """`Math.min(primite, cerute)` — nu totalul primit."""
    assert "Math.min(item.receivedCount, item.expectedMinCount)" in seed_source
