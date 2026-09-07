"""Ziua cabinetului, in cele doua nopti in care difera de UTC.

Testele de aici sunt scurte pentru ca greseala este scurta: doua ore. Ce nu este
scurt este ce se intampla din cauza ei, si de aceea fiecare caz este numit dupa
paguba, nu dupa functie.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core import clock


def frozen(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(clock, "now", lambda: moment)


class TestTheOfficeCalendar:
    def test_at_half_past_one_in_summer_the_office_is_already_on_the_next_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vara Bucurestiul merge cu trei ore inaintea UTC.

        La 22:30 UTC pe 31 august, in cabinet este 1 septembrie, ora 01:30. Un
        onorariu marcat platit atunci trebuie sa cada in septembrie: scris pe 31
        august, ar intra intr-o luna pe care cabinetul o inchisese.
        """
        frozen(monkeypatch, datetime(2026, 8, 31, 22, 30, tzinfo=UTC))

        assert clock.today() == date(2026, 9, 1)
        # Ce spunea codul inainte, si de ce nu era acelasi lucru.
        assert clock.now().date() == date(2026, 8, 31)

    def test_at_half_past_midnight_in_winter_it_is_also_the_next_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Iarna diferenta este de doua ore, nu de trei. Tot se schimba ziua."""
        frozen(monkeypatch, datetime(2026, 1, 31, 22, 30, tzinfo=UTC))

        assert clock.today() == date(2026, 2, 1)

    def test_the_deadline_day_is_read_as_the_office_reads_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Termenul este 25. Pe 26 la 01:30 el a trecut, si trebuie sa se vada.

        Aici statea reminderul: comparat cu ziua UTC, 25, regula „nu se scrie dupa
        termen" nu se aplica inca — iar clientul primea un mesaj care ii cerea
        documentele „ca sa depunem la timp", a doua zi dupa termen.
        """
        frozen(monkeypatch, datetime(2026, 9, 25, 22, 30, tzinfo=UTC))
        deadline = date(2026, 9, 25)

        assert clock.today() > deadline
        assert not clock.now().date() > deadline

    def test_during_the_day_the_two_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Restul zilei nu se schimba nimic — altfel ar fi fost o mutare, nu o reparatie."""
        frozen(monkeypatch, datetime(2026, 9, 25, 8, 0, tzinfo=UTC))

        assert clock.today() == clock.now().date() == date(2026, 9, 25)
