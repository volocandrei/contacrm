"""Fixture-uri comune.

Testele din M2 nu ating Postgres: verifică scheletul HTTP, contractul de eroare și
configurarea. Testele care au nevoie de bază de date vin cu M3, pe o bază separată.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client() -> Iterator[TestClient]:
    # `raise_server_exceptions=False` lasă handler-ul de excepții să producă
    # răspunsul real, în loc ca excepția să scape în test.
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def frontend_types_source() -> str:
    """Sursa contractului pe care îl consumă frontend-ul."""
    path = REPO_ROOT / "frontend" / "src" / "api" / "types.ts"
    return path.read_text(encoding="utf-8")
