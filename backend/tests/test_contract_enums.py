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
