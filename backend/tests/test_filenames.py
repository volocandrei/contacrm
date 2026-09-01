"""Numele de fișier și căile de arhivă (§10, §11, R7).

Două straturi de verificare:

1. **Cazurile din `frontend/src/lib/filename.test.ts`, rulate în Python.** Fișierul
   acela este specificația executabilă a regulii; aceleași intrări trebuie să dea
   aceleași ieșiri aici. Cazurile simple se citesc chiar din el, ca o modificare a
   specificației să spargă portul, nu să-l lase în urmă în tăcere.
2. Cazuri suplimentare pentru lucruri pe care doar backendul le poate face greșit.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.domain.filenames import (
    FilenameInput,
    build_archive_path,
    build_document_filename,
    normalize_extension,
    sanitize_segment,
)

SPEC = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "filename.test.ts"

BACKSLASH = chr(92)


@pytest.fixture(scope="module")
def spec_source() -> str:
    return SPEC.read_text(encoding="utf-8")


def _unescape(literal: str) -> str:
    """Traduce un literal TypeScript simplu în textul pe care îl reprezintă."""
    return (
        literal.replace(BACKSLASH * 2, BACKSLASH)
        .replace(BACKSLASH + '"', '"')
        .replace(BACKSLASH + "'", "'")
    )


def _cases(source: str, function: str) -> list[tuple[str, str]]:
    """Perechile `expect(fn("intrare")).toBe("ieșire")` dintr-un fișier de test TS.

    Doar forma cu un singur argument literal — restul cazurilor sunt portate de mână
    mai jos, pentru că nu se pot citi mecanic.
    """
    pattern = re.compile(
        rf'expect\({function}\("((?:[^"\\]|\\.)*)"\)\)\.toBe\("((?:[^"\\]|\\.)*)"\)'
    )
    return [(_unescape(m.group(1)), _unescape(m.group(2))) for m in pattern.finditer(source)]


# ── Cazurile citite direct din specificația frontend ─────────────────────────


def test_the_frontend_specification_is_readable(spec_source: str) -> None:
    """Dacă fișierul se mută sau își schimbă forma, testele de mai jos ar trece gol."""
    assert len(_cases(spec_source, "sanitizeSegment")) >= 6
    assert len(_cases(spec_source, "buildDocumentFilename")) == 0  # ia obiecte, nu string-uri


def test_sanitize_segment_matches_the_frontend_cases(spec_source: str) -> None:
    for value, expected in _cases(spec_source, "sanitizeSegment"):
        assert sanitize_segment(value) == expected, f"sanitizeSegment({value!r})"


def test_archive_path_matches_the_frontend_cases(spec_source: str) -> None:
    pattern = re.compile(
        r'expect\(buildArchivePath\("((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)"\)\)'
        r'\.toBe\("((?:[^"\\]|\\.)*)"\)'
    )
    found = 0
    for match in pattern.finditer(spec_source):
        month, client, expected = (_unescape(g) for g in match.groups())
        assert build_archive_path(month, client) == expected, f"({month!r}, {client!r})"
        found += 1
    assert found >= 3


# ── sanitize_segment ─────────────────────────────────────────────────────────


class TestSanitizeSegment:
    def test_romanian_diacritics_are_folded(self) -> None:
        assert sanitize_segment("Șerbănescu Țară SRL") == "SerbanescuTaraSRL"
        assert sanitize_segment("ăâîșț ĂÂÎȘȚ") == "aaistAAIST"

    def test_path_separators_are_removed_in_both_forms(self) -> None:
        assert sanitize_segment("a/b") == "ab"
        assert sanitize_segment(f"a{BACKSLASH}b") == "ab"
        assert sanitize_segment(f"..{BACKSLASH}..{BACKSLASH}etc") == "etc"
        assert sanitize_segment("../../etc") == "etc"

    def test_windows_illegal_and_control_characters_are_removed(self) -> None:
        assert sanitize_segment('a<b>c:d"e|f?g*h') == "abcdefgh"
        assert sanitize_segment(f"a{chr(0)}b{chr(31)}c") == "abc"

    def test_hyphen_and_underscore_survive(self) -> None:
        """Apar în serii reale; a le elimina ar schimba identitatea documentului."""
        assert sanitize_segment("FCT-2026_A") == "FCT-2026_A"

    def test_reserved_windows_names_are_escaped(self) -> None:
        assert sanitize_segment("CON") == "_CON"
        assert sanitize_segment("nul") == "_nul"
        assert sanitize_segment("LPT1") == "_LPT1"

    def test_never_returns_an_empty_segment(self) -> None:
        assert sanitize_segment("") == "_"
        assert sanitize_segment("///") == "_"

    def test_no_leading_or_trailing_dot_or_space(self) -> None:
        assert sanitize_segment("  .nume.  ") == "nume"

    def test_length_limit(self) -> None:
        assert len(sanitize_segment("x" * 200)) == 60
        assert len(sanitize_segment("x" * 200, 10)) == 10


class TestNormalizeExtension:
    def test_content_type_beats_the_extension_the_sender_chose(self) -> None:
        assert normalize_extension("factura.exe", "application/pdf") == "pdf"
        assert normalize_extension("poza.pdf", "image/jpeg") == "jpg"

    def test_only_allowed_extensions_pass(self) -> None:
        assert normalize_extension("factura.PDF") == "pdf"
        assert normalize_extension("script.exe") == "pdf"
        assert normalize_extension("fara-extensie") == "pdf"


# ── build_document_filename ──────────────────────────────────────────────────


def base_input(**overrides: object) -> FilenameInput:
    data: dict[str, object] = {
        "document_date": "2026-08-14",
        "document_type_label": "Factură",
        "client_name": "Alfa Prod SRL",
        "series": "FCT",
        "document_number": "1024",
        "original_filename": "scan.PDF",
    }
    data.update(overrides)
    return FilenameInput(**data)  # type: ignore[arg-type]


class TestBuildDocumentFilename:
    def test_follows_the_convention(self) -> None:
        assert build_document_filename(base_input()) == (
            "2026-08-14_Factura_AlfaProdSRL_FCT1024.pdf"
        )

    def test_the_last_segment_is_omitted_without_series_and_number(self) -> None:
        assert build_document_filename(base_input(series=None, document_number=None)) == (
            "2026-08-14_Factura_AlfaProdSRL.pdf"
        )

    def test_a_missing_date_is_marked_not_invented(self) -> None:
        assert build_document_filename(base_input(document_date=None)).startswith("fara-data_")
        # Respectă formatul, dar februarie nu are 30 de zile.
        assert build_document_filename(base_input(document_date="2026-02-30")).startswith(
            "fara-data_"
        )

    def test_collision_suffix(self) -> None:
        assert build_document_filename(base_input(collision_suffix=2)) == (
            "2026-08-14_Factura_AlfaProdSRL_FCT1024_2.pdf"
        )

    def test_no_path_separator_survives_the_client_name(self) -> None:
        hostile = build_document_filename(
            base_input(client_name=f"..{BACKSLASH}..{BACKSLASH}windows{BACKSLASH}system32")
        )
        assert "/" not in hostile
        assert BACKSLASH not in hostile

    def test_a_real_date_object_is_accepted(self) -> None:
        """Backendul ține data ca `date`, nu ca text — spre deosebire de frontend."""
        assert build_document_filename(base_input(document_date=date(2026, 8, 14))) == (
            "2026-08-14_Factura_AlfaProdSRL_FCT1024.pdf"
        )

    def test_the_name_stays_within_the_length_limit(self) -> None:
        name = build_document_filename(
            base_input(client_name="x" * 300, document_type_label="y" * 300)
        )
        assert len(name) <= 180
        assert name.endswith(".pdf")


# ── build_archive_path ───────────────────────────────────────────────────────


class TestBuildArchivePath:
    def test_builds_year_month_client(self) -> None:
        assert build_archive_path("2026-08", "Alfa Prod SRL") == "/ARHIVA/2026/08/AlfaProdSRL/"

    def test_cannot_escape_the_root_through_the_client_name(self) -> None:
        path = build_archive_path("2026-08", f"..{BACKSLASH}..{BACKSLASH}Beta")
        assert path == "/ARHIVA/2026/08/Beta/"
        assert BACKSLASH not in path
        assert len([p for p in path.split("/") if p]) == 4

    def test_cannot_escape_the_root_through_the_reference_month(self) -> None:
        assert build_archive_path("../../etc", "Alfa") == "/ARHIVA/fara-perioada/00/Alfa/"
        assert build_archive_path("2026-13", "Alfa") == "/ARHIVA/2026/00/Alfa/"

    def test_missing_period_or_client_is_marked_explicitly(self) -> None:
        assert build_archive_path(None, None) == "/ARHIVA/fara-perioada/00/ClientNeidentificat/"

    @pytest.mark.parametrize(
        "hostile",
        ["2026-08", "../..", "..", "", "2026-8", "0000-00", "9999-12"],
    )
    def test_always_four_segments_under_the_root(self, hostile: str) -> None:
        path = build_archive_path(hostile, "..")
        assert path.startswith("/ARHIVA/")
        assert ".." not in path
        assert len([p for p in path.split("/") if p]) == 4
