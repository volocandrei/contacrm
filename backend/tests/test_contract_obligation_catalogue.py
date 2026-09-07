"""Catalogul de declarații, în amândouă backend-urile (§14, §53).

**Ce s-a întâmplat fără testul acesta.** Catalogul real avea unsprezece
declarații; cel simulat, șase. D390 și SAF-T lipseau din backendul simulat — nu
pentru că cineva ar fi decis că demonstrația nu are nevoie de ele, ci pentru că
au fost adăugate pe server și nimeni nu a fost obligat să le adauge și dincolo.
Un catalog mai sărac în demonstrație nu se vede: ecranul arată corect, doar
despre mai puține declarații.

Ce se compară este **regula**, nu textul: codul, periodicitatea, decalajul în
luni și ziua. Eticheta rămâne text de interfață și se poate scrie altfel.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.obligations import DEFAULT_OBLIGATIONS, ObligationSeed

STORE_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "mock" / "store.ts"

#: Un rând din catalogul simulat, cu cele patru câmpuri care sunt regulă.
_ROW = re.compile(
    r'code:\s*"(?P<code>[A-Z0-9_]+)".*?'
    r'frequency:\s*"(?P<frequency>[A-Z_]+)".*?'
    r"monthsAfter:\s*(?P<months>\d+).*?"
    r"deadlineDay:\s*(?P<day>\d+)",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def mock_catalogue() -> dict[str, tuple[str, int, int]]:
    source = STORE_TS.read_text(encoding="utf-8")
    start = source.index("const obligationTypes: ObligationType[] = [")
    end = source.index("\n];", start)
    block = source[start:end]

    found = {
        match["code"]: (match["frequency"], int(match["months"]), int(match["day"]))
        for match in _ROW.finditer(block)
    }
    assert found, "nu s-a citit niciun rând din catalogul simulat"
    return found


def test_every_obligation_exists_in_both(mock_catalogue: dict[str, tuple[str, int, int]]) -> None:
    real = {seed.code for seed in DEFAULT_OBLIGATIONS}

    assert real == set(mock_catalogue), "catalogul simulat s-a despărțit de cel real"


@pytest.mark.parametrize("seed", DEFAULT_OBLIGATIONS, ids=lambda seed: seed.code)
def test_the_rule_is_the_same_on_both_sides(
    seed: ObligationSeed, mock_catalogue: dict[str, tuple[str, int, int]]
) -> None:
    """Periodicitatea, decalajul și ziua — nu eticheta, care este text."""
    assert mock_catalogue[seed.code] == (
        seed.frequency.value,
        seed.months_after,
        seed.deadline_day,
    )
