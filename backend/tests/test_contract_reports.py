"""Raportul, partajat cu backend-ul simulat (§84).

Există două implementări ale aceluiași raport: `app/services/report_service.py`,
care agregă în SQL, și oglinda din `frontend/src/api/mock/store.ts`, care ține
demonstrația în viață fără server. Două implementări ale aceleiași reguli se
despart întotdeauna — singura întrebare este dacă se află de la un test sau de la
un client.

Ce se compară aici sunt exact deciziile care s-ar putea despărți tăcut, fără să
strice nimic vizibil: câți clienți intră în clasament, ce stări înseamnă „încă în
lucru", și ce câmpuri are răspunsul.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.v1.reports import BucketOut, ReportSummaryOut
from app.services.report_service import IN_PROGRESS, TOP_CLIENTS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
STORE_TS = FRONTEND / "api" / "mock" / "store.ts"
DOMAIN_TS = FRONTEND / "types" / "domain.ts"


@pytest.fixture(scope="module")
def store_source() -> str:
    return STORE_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def domain_source() -> str:
    return DOMAIN_TS.read_text(encoding="utf-8")


def _fields(source: str, type_name: str) -> set[str]:
    """Numele câmpurilor dintr-un `export type X = { ... }`."""
    block = re.search(rf"export type {type_name} = \{{(.*?)\n\}};", source, re.DOTALL)
    assert block is not None, f"{type_name} nu a fost găsit în types/domain.ts"
    # Sar peste comentarii; numele este ce stă înaintea celui dintâi `:`.
    return {
        match.group(1)
        for line in block.group(1).splitlines()
        if (match := re.match(r"\s{2}(\w+)\??:", line))
    }


def test_the_client_ranking_is_capped_the_same_on_both_sides(store_source: str) -> None:
    """Un plafon diferit ar da două clasamente de lungimi diferite, ambele „corecte"."""
    match = re.search(r"const TOP_CLIENTS = (\d+);", store_source)
    assert match is not None, "TOP_CLIENTS nu a fost găsit în mock/store.ts"
    assert int(match.group(1)) == TOP_CLIENTS


def test_the_same_statuses_count_as_unfinished(store_source: str) -> None:
    """Dacă listele se despart, aceeași bază de date dă două rate de reușită."""
    block = re.search(
        r"const IN_PROGRESS: DocumentStatus\[\] = \[(.*?)\];", store_source, re.DOTALL
    )
    assert block is not None, "IN_PROGRESS nu a fost găsit în mock/store.ts"

    frontend = set(re.findall(r'"([A-Z_]+)"', block.group(1)))
    assert frontend == {status.value for status in IN_PROGRESS}


def test_the_summary_has_the_same_fields(domain_source: str) -> None:
    """Un câmp în plus într-o parte este un câmp lipsă în cealaltă."""
    backend = set(ReportSummaryOut.model_json_schema(by_alias=True)["properties"])
    assert _fields(domain_source, "ReportSummary") == backend


def test_the_bucket_has_the_same_fields(domain_source: str) -> None:
    backend = set(BucketOut.model_json_schema(by_alias=True)["properties"])
    assert _fields(domain_source, "ReportBucket") == backend


def test_absence_is_reported_without_a_label(domain_source: str) -> None:
    """Cum se numește lipsa este treaba interfeței, în amândouă implementările.

    Dacă `label` ar deveni obligatoriu, serverul ar fi nevoit să inventeze o
    formulare — iar atunci ar exista două surse pentru același text pe ecran.
    """
    bucket = BucketOut.model_json_schema(by_alias=True)["properties"]
    for field in ("key", "label"):
        assert {"type": "null"} in bucket[field]["anyOf"], f"{field} trebuie să accepte null"

    assert re.search(r"key: string \| null;", domain_source)
    assert re.search(r"label: string \| null;", domain_source)


def test_the_success_rate_may_be_absent(domain_source: str) -> None:
    """`null` înseamnă „nu s-a terminat nimic", nu „totul a eșuat"."""
    rate = ReportSummaryOut.model_json_schema(by_alias=True)["properties"]["successRate"]
    assert {"type": "null"} in rate["anyOf"]
    assert "successRate: number | null;" in domain_source
