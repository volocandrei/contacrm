"""Aceeași politică de parolă în amândouă limbajele (§1, §54).

`frontend/src/lib/password.ts` este portul lui `app/domain/passwords.py`, iar
`password.test.ts` este specificația executabilă. Testul de aici **citește
cazurile din fișierul TypeScript** și le rulează în Python.

**De ce nu ajunge o listă scrisă de două ori.** Ar fi trecut amândouă fericite
până când cineva ar fi schimbat una singură. Ce se apără nu este o listă, este o
promisiune: ce acceptă formularul, acceptă și serverul. Dacă browserul acceptă ce
serverul refuză, omul apasă și primește o eroare pe care formularul i-o promisese
rezolvată. Dacă refuză ce serverul acceptă, îi cerem o parolă mai grea degeaba.

Aceeași tehnică ca la `test_filenames.py`, din același motiv.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.passwords import MIN_DISTINCT, MIN_LENGTH, problems

SPEC = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "password.test.ts"

#: Identitatea contului pe care specificația verifică toate cazurile.
EMAIL = "ioana.marinescu@cabinet.ro"
FULL_NAME = "Ioana Marinescu"


@pytest.fixture(scope="module")
def spec_source() -> str:
    return SPEC.read_text(encoding="utf-8")


def _calls(source: str, block: str) -> list[tuple[str, bool]]:
    """Apelurile `passwordProblems(...)` dintr-un bloc `describe`, cu verdictul lor.

    `toHaveLength(0)` înseamnă acceptată; `not.toHaveLength(0)` înseamnă refuzată.
    Se citesc numai apelurile cu argumente literale — restul n-au ce căuta într-o
    specificație care trebuie să poată fi citită din două limbaje.
    """
    start = source.index(f'describe("{block}"')
    end = source.find("\ndescribe(", start + 1)
    chunk = source[start : end if end > 0 else len(source)]

    pattern = re.compile(
        r'passwordProblems\(\s*"((?:[^"\\]|\\.)*)"[^)]*\)[\s,)]*\.(not\.)?toHaveLength\(\s*0\s*,?\s*\)',
        re.S,
    )
    found = [(m.group(1), m.group(2) is None) for m in pattern.finditer(chunk)]
    return found


def test_the_frontend_specification_is_readable(spec_source: str) -> None:
    """Dacă fișierul se mută sau își schimbă forma, testele de mai jos ar trece gol."""
    assert SPEC.exists(), SPEC
    assert len(_calls(spec_source, "parole refuzate")) >= 5
    assert len(_calls(spec_source, "parole acceptate")) >= 4


def test_every_password_the_frontend_refuses_is_refused_here(spec_source: str) -> None:
    for password, accepted in _calls(spec_source, "parole refuzate"):
        assert not accepted, f"caz greșit citit: {password!r}"
        assert problems(password, email=EMAIL, full_name=FULL_NAME), (
            f"browserul refuză {password!r}, serverul o acceptă"
        )


def test_every_password_the_frontend_accepts_is_accepted_here(spec_source: str) -> None:
    for password, accepted in _calls(spec_source, "parole acceptate"):
        assert accepted, f"caz greșit citit: {password!r}"
        # Cazul cu „Ion Vasile" are altă identitate; îl verificăm cu a lui.
        identity = (
            ("ion@cabinet.ro", "Ion Vasile") if "campionatul" in password else (EMAIL, FULL_NAME)
        )
        assert not problems(password, email=identity[0], full_name=identity[1]), (
            f"browserul acceptă {password!r}, serverul o refuză"
        )


def test_the_thresholds_are_the_same_number_in_both(spec_source: str) -> None:
    """Pragurile sunt scrise ca cifre în amândouă. Se compară cifrele."""
    assert f"expect(MIN_LENGTH).toBe({MIN_LENGTH})" in spec_source
    assert f"expect(MIN_DISTINCT).toBe({MIN_DISTINCT})" in spec_source
