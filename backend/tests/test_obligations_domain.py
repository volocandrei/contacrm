"""Aritmetica termenelor, fără bază de date.

Aici nu se testează nicio regulă fiscală — nu există niciuna în cod. Se testează
că un calendar se calculează corect: în ce luni se încheie o perioadă, la câte
luni după cade termenul, și ce se întâmplă cu o zi care nu există în luna aceea.

Ultimul punct este cel care s-ar strica tăcut. Un termen pe 30 într-o lună cu 28
de zile trebuie să existe undeva; dacă dispare, dispare exact în luna în care
cineva îl caută.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import ObligationFrequency
from app.domain.obligations import (
    DEFAULT_OBLIGATIONS,
    ObligationSeed,
    closes_a_period,
    deadline_for,
    due_between,
)


class TestWhenAPeriodEnds:
    def test_every_month_closes_a_monthly_period(self) -> None:
        assert all(closes_a_period(ObligationFrequency.MONTHLY, month) for month in range(1, 13))

    def test_only_four_months_close_a_quarter(self) -> None:
        closing = [
            month for month in range(1, 13) if closes_a_period(ObligationFrequency.QUARTERLY, month)
        ]
        assert closing == [3, 6, 9, 12]

    def test_only_december_closes_a_year(self) -> None:
        closing = [
            month for month in range(1, 13) if closes_a_period(ObligationFrequency.ANNUAL, month)
        ]
        assert closing == [12]


class TestTheDeadlineItself:
    def test_it_falls_in_the_month_after_the_period(self) -> None:
        """Documentele lui august se declară în septembrie."""
        deadline = deadline_for(
            ObligationFrequency.MONTHLY, "2026-08", months_after=1, deadline_day=25
        )

        assert deadline == date(2026, 9, 25)

    def test_december_rolls_into_the_next_year(self) -> None:
        deadline = deadline_for(
            ObligationFrequency.MONTHLY, "2026-12", months_after=1, deadline_day=25
        )

        assert deadline == date(2027, 1, 25)

    def test_a_day_that_does_not_exist_is_clamped_not_dropped(self) -> None:
        """Un termen pe 30 nu are ce căuta în februarie.

        Retezat la ultima zi a lunii, nu sărit: un termen care **dispare** exact
        în luna în care cade este mai rău decât unul mutat cu două zile, fiindcă
        nu se vede că lipsește.
        """
        deadline = deadline_for(
            ObligationFrequency.MONTHLY, "2027-01", months_after=1, deadline_day=30
        )

        assert deadline == date(2027, 2, 28)

    def test_a_leap_february_keeps_its_extra_day(self) -> None:
        deadline = deadline_for(
            ObligationFrequency.MONTHLY, "2028-01", months_after=1, deadline_day=31
        )

        assert deadline == date(2028, 2, 29)

    def test_an_annual_deadline_can_sit_months_later(self) -> None:
        """Situațiile financiare: cinci luni după închiderea anului."""
        deadline = deadline_for(
            ObligationFrequency.ANNUAL, "2026-12", months_after=5, deadline_day=30
        )

        assert deadline == date(2027, 5, 30)


class TestTheWindow:
    def test_it_lists_every_monthly_deadline_in_order(self) -> None:
        found = due_between(
            ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
            since=date(2026, 9, 1),
            until=date(2026, 11, 30),
        )

        assert [(due.period, due.deadline) for due in found] == [
            ("2026-08", date(2026, 9, 25)),
            ("2026-09", date(2026, 10, 25)),
            ("2026-10", date(2026, 11, 25)),
        ]

    def test_a_quarter_produces_one_deadline_not_three(self) -> None:
        found = due_between(
            ObligationFrequency.QUARTERLY,
            months_after=1,
            deadline_day=25,
            since=date(2026, 7, 1),
            until=date(2026, 12, 31),
        )

        assert [due.period for due in found] == ["2026-06", "2026-09"]

    def test_the_period_is_named_after_the_month_it_closes(self) -> None:
        """Trimestrul III 2026 este `2026-09`, nu `2026-07`.

        Perioada se numește după ce acoperă: cine se uită la un termen vrea să
        știe ce închide, nu când a început.
        """
        found = due_between(
            ObligationFrequency.QUARTERLY,
            months_after=1,
            deadline_day=25,
            since=date(2026, 10, 1),
            until=date(2026, 10, 31),
        )

        assert [due.period for due in found] == ["2026-09"]

    def test_a_deadline_already_past_is_still_found(self) -> None:
        """Fereastra pornește din urmă, altfel întârziatele ar dispărea.

        Un termen ratat nu se rezolvă trecând timpul, iar o listă care ar începe
        de azi l-ar ascunde exact pe cel care contează cel mai mult.
        """
        found = due_between(
            ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
            since=date(2026, 5, 1),
            until=date(2026, 9, 10),
        )

        assert [due.period for due in found] == ["2026-04", "2026-05", "2026-06", "2026-07"]

    def test_a_long_offset_does_not_lose_the_period(self) -> None:
        """Cu cinci luni decalaj, perioada este cu mult înaintea ferestrei.

        Prima variantă pornea căutarea de la începutul ferestrei minus o lună și
        pierdea exact obligațiile cu termen îndepărtat — bilanțul, adică singura
        care se uită cel mai ușor.
        """
        found = due_between(
            ObligationFrequency.ANNUAL,
            months_after=5,
            deadline_day=30,
            since=date(2027, 5, 1),
            until=date(2027, 6, 30),
        )

        assert [(due.period, due.deadline) for due in found] == [("2026-12", date(2027, 5, 30))]

    def test_a_reversed_window_finds_nothing_instead_of_looping(self) -> None:
        assert (
            due_between(
                ObligationFrequency.MONTHLY,
                months_after=1,
                deadline_day=25,
                since=date(2026, 9, 30),
                until=date(2026, 9, 1),
            )
            == []
        )

    def test_a_single_day_window_finds_the_deadline_that_falls_on_it(self) -> None:
        found = due_between(
            ObligationFrequency.MONTHLY,
            months_after=1,
            deadline_day=25,
            since=date(2026, 9, 25),
            until=date(2026, 9, 25),
        )

        assert [due.period for due in found] == ["2026-08"]


class TestTheStartingCatalogue:
    """Catalogul este conținut inițial, nu o afirmație despre lege.

    Ce se apără aici este doar coerența lui: coduri unice, zile care există,
    decalaje care nu cer o declarație înainte de sfârșitul perioadei.
    """

    def test_the_codes_are_unique(self) -> None:
        codes = [seed.code for seed in DEFAULT_OBLIGATIONS]

        assert len(codes) == len(set(codes))

    @pytest.mark.parametrize("seed", DEFAULT_OBLIGATIONS, ids=lambda s: s.code)
    def test_every_entry_produces_a_real_date(self, seed: ObligationSeed) -> None:
        """O zi inexistentă ar arunca `ValueError` la prima deschidere a ecranului."""
        deadline = deadline_for(
            seed.frequency,
            "2027-01",
            months_after=seed.months_after,
            deadline_day=seed.deadline_day,
        )

        assert deadline > date(2027, 1, 1)
