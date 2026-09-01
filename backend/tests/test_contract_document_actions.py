"""Ciclul de viață al documentului, partajat cu frontend-ul (§31, §53).

Backend-ul este autoritatea: `app/domain/document_state.py` decide ce tranziții sunt
permise, iar `app/domain/document_actions.py` traduce asta în butoane. Backendul
simulat din browser are aceleași reguli scrise în TypeScript, ca ecranul de
verificare să se poarte identic în ambele moduri.

Testele astea cad exact în momentul în care cele două se despart — adică atunci când
interfața ar începe să ofere un buton pe care serverul îl refuză.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.document_actions import DocumentAction
from app.domain.document_state import allowed_targets
from app.domain.enums import DocumentErrorCode, DocumentStatus

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
STORE_TS = FRONTEND / "api" / "mock" / "store.ts"
DOMAIN_TS = FRONTEND / "types" / "domain.ts"


@pytest.fixture(scope="module")
def store_source() -> str:
    return STORE_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def domain_source() -> str:
    return DOMAIN_TS.read_text(encoding="utf-8")


def _frontend_transitions(source: str) -> dict[str, set[str]]:
    block = re.search(
        r"const ALLOWED_TRANSITIONS: Record<DocumentStatus, DocumentStatus\[\]> = \{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    assert block is not None, "ALLOWED_TRANSITIONS nu a fost găsit în mock/store.ts"

    table: dict[str, set[str]] = {}
    for line in re.finditer(r"(\w+):\s*\[([^\]]*)\]", block.group(1)):
        table[line.group(1)] = set(re.findall(r'"([A-Z_]+)"', line.group(2)))
    return table


def test_every_status_has_a_row_in_the_frontend_table(store_source: str) -> None:
    assert set(_frontend_transitions(store_source)) == {s.value for s in DocumentStatus}


@pytest.mark.parametrize("status", list(DocumentStatus))
def test_allowed_transitions_are_identical(store_source: str, status: DocumentStatus) -> None:
    frontend = _frontend_transitions(store_source)[status.value]
    backend = {target.value for target in allowed_targets(status)}
    assert frontend == backend, (
        f"{status.value} — doar în frontend: {sorted(frontend - backend)}; "
        f"doar în backend: {sorted(backend - frontend)}"
    )


def test_action_vocabulary_matches_frontend(domain_source: str) -> None:
    match = re.search(r"export const DOCUMENT_ACTION = \[(.*?)\] as const;", domain_source, re.S)
    assert match is not None, "DOCUMENT_ACTION nu a fost găsit în types/domain.ts"

    frontend = set(re.findall(r'"(\w+)"', match.group(1)))
    assert frontend == {action.value for action in DocumentAction}


def test_error_code_vocabulary_matches_frontend(domain_source: str) -> None:
    """Codul se persistă; textul afișat se traduce în interfață."""
    pattern = r"export const DOCUMENT_ERROR_CODE = \[(.*?)\] as const;"
    match = re.search(pattern, domain_source, re.S)
    assert match is not None, "DOCUMENT_ERROR_CODE nu a fost găsit în types/domain.ts"

    frontend = set(re.findall(r'"([A-Z_]+)"', match.group(1)))
    assert frontend == {code.value for code in DocumentErrorCode}


def test_every_error_code_has_a_romanian_label() -> None:
    """Un cod fără etichetă ar apărea pe ecran ca `EXTRACTION_FAILED`."""
    review_page = (FRONTEND / "features" / "documents" / "review-page.tsx").read_text(
        encoding="utf-8"
    )
    block = re.search(
        r"const ERROR_LABEL: Record<DocumentErrorCode, string> = \{(.*?)\n\};",
        review_page,
        re.DOTALL,
    )
    assert block is not None, "ERROR_LABEL nu a fost găsit în review-page.tsx"

    labelled = set(re.findall(r"(\w+):", block.group(1)))
    assert labelled == {code.value for code in DocumentErrorCode}
