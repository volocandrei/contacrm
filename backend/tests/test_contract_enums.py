"""Statusurile, partajate cu frontend-ul (§53).

Backend-ul este autoritatea. Frontend-ul are aceleași liste în `types/domain.ts`,
folosite pentru badge-uri, filtre și backendul simulat. Testele astea cad când cele
două se despart — momentul în care un status ar ajunge în baza de date fără să aibă
o etichetă în interfață, sau invers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.enums import (
    TASK_STATUS_ORDER,
    ClientStatus,
    DocumentSource,
    DocumentStatus,
    PeriodStatus,
    TaskPriority,
    TaskStatus,
)
from app.domain.labels import DOCUMENT_STATUS_LABEL

DOMAIN_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "domain.ts"


@pytest.fixture(scope="module")
def domain_source() -> str:
    return DOMAIN_TS.read_text(encoding="utf-8")


def _const_list(source: str, name: str) -> set[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.DOTALL)
    assert match is not None, f"{name} nu a fost găsit în types/domain.ts"
    return set(re.findall(r'"([A-Z_]+)"', match.group(1)))


@pytest.mark.parametrize(
    ("ts_name", "enum_cls"),
    [
        ("DOCUMENT_STATUS", DocumentStatus),
        ("CLIENT_STATUS", ClientStatus),
        ("PERIOD_STATUS", PeriodStatus),
        ("DOCUMENT_SOURCE", DocumentSource),
        ("TASK_STATUS", TaskStatus),
        ("TASK_PRIORITY", TaskPriority),
    ],
)
def test_status_vocabulary_matches_frontend(
    domain_source: str, ts_name: str, enum_cls: type
) -> None:
    frontend = _const_list(domain_source, ts_name)
    backend = {member.value for member in enum_cls}
    assert frontend == backend, (
        f"{ts_name} — doar în frontend: {sorted(frontend - backend)}; "
        f"doar în backend: {sorted(backend - frontend)}"
    )


def test_every_task_status_has_a_display_order() -> None:
    """Fără asta, un status nou s-ar sorta imprevizibil pe kanban."""
    assert set(TASK_STATUS_ORDER) == set(TaskStatus)


def test_task_status_order_puts_done_last() -> None:
    assert max(TASK_STATUS_ORDER, key=lambda s: TASK_STATUS_ORDER[s]) is TaskStatus.DONE
    assert min(TASK_STATUS_ORDER, key=lambda s: TASK_STATUS_ORDER[s]) is TaskStatus.TODO


def test_field_source_vocabulary_matches_frontend(domain_source: str) -> None:
    """`FieldSource` alimentează eticheta de proveniență din ecranul de verificare."""
    match = re.search(r"export type FieldSource =([^;]+);", domain_source, re.DOTALL)
    assert match is not None, "FieldSource nu a fost găsit în types/domain.ts"

    from app.domain.enums import FieldSource

    frontend = set(re.findall(r'"([A-Z_]+)"', match.group(1)))
    assert frontend == {member.value for member in FieldSource}


def test_default_document_types_match_the_frontend_seed() -> None:
    """Codurile, etichetele și câmpurile obligatorii trebuie să fie identice.

    Frontend-ul le are în backendul simulat; backendul real le încarcă la crearea
    organizației. Dacă se despart, ecranul de verificare ar cere alte câmpuri decât
    validează serverul.
    """
    from app.domain.document_types import DEFAULT_DOCUMENT_TYPES

    seed_source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "mock" / "seed.ts"
    ).read_text(encoding="utf-8")

    block = re.search(
        r"export const DOCUMENT_TYPES: DocumentType\[\] = \[(.*?)\n\];", seed_source, re.DOTALL
    )
    assert block is not None, "DOCUMENT_TYPES nu a fost găsit în mock/seed.ts"

    frontend: dict[str, set[str]] = {}
    for entry in re.finditer(
        r'code:\s*"([A-Z_]+)".*?requiredFields:\s*\[([^\]]*)\]', block.group(1), re.DOTALL
    ):
        frontend[entry.group(1)] = set(re.findall(r'"(\w+)"', entry.group(2)))

    backend = {t.code: set(t.required_fields) for t in DEFAULT_DOCUMENT_TYPES}

    assert set(frontend) == set(backend), (
        f"doar în frontend: {sorted(set(frontend) - set(backend))}; "
        f"doar în backend: {sorted(set(backend) - set(frontend))}"
    )
    for code, fields in frontend.items():
        assert backend[code] == fields, f"{code}: câmpuri obligatorii diferite"


def test_document_status_labels_match_the_frontend() -> None:
    """Aceeași stare, același cuvânt, pe ecran și în gura asistentului.

    Etichetele au trăit doar în frontend cât timp singurul care le arăta era
    ecranul. De când asistentul spune „este la verificare", textul se compune pe
    server — iar două formulări pentru aceeași stare sunt mai rele decât una
    imperfectă: a doua nu se caută în ecran.
    """
    labels_ts = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "labels.ts"
    block = re.search(
        r"export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = \{(.*?)\n\};",
        labels_ts.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None, "DOCUMENT_STATUS_LABEL nu a fost găsit în lib/labels.ts"

    frontend = dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))
    backend = {status.value: label for status, label in DOCUMENT_STATUS_LABEL.items()}

    assert frontend == backend
