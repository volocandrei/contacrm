"""Contractul dintre backend și frontend.

Testele de aici există ca cele două jumătăți să nu se despartă în tăcere. Dacă
cineva adaugă un cod de eroare într-o parte și uită de cealaltă, aici se vede.
"""

from __future__ import annotations

import re

from app.core.errors import ErrorCode
from app.schemas.common import PageParams, Paginated


def test_error_codes_match_frontend(frontend_types_source: str) -> None:
    """`ErrorCode` trebuie să fie identic cu `API_ERROR_CODES` din types.ts."""
    block = re.search(
        r"export const API_ERROR_CODES = \[(.*?)\] as const;",
        frontend_types_source,
        re.DOTALL,
    )
    assert block is not None, "API_ERROR_CODES nu a fost găsit în frontend/src/api/types.ts"

    frontend_codes = set(re.findall(r'"([A-Z_]+)"', block.group(1)))
    backend_codes = {code.value for code in ErrorCode}

    assert frontend_codes == backend_codes, (
        f"doar în frontend: {sorted(frontend_codes - backend_codes)}; "
        f"doar în backend: {sorted(backend_codes - frontend_codes)}"
    )


def test_paginated_serialises_as_camel_case() -> None:
    """Frontend-ul citește `pageSize` și `totalPages`, nu snake_case."""
    page = Paginated[str].build(items=["a", "b"], total=7, params=PageParams(page=1, page_size=2))
    payload = page.model_dump(by_alias=True)

    assert set(payload) == {"items", "page", "pageSize", "total", "totalPages"}
    assert payload["totalPages"] == 4
    assert payload["pageSize"] == 2


def test_total_pages_is_at_least_one_when_empty() -> None:
    """O listă goală are o pagină, nu zero — altfel paginarea din UI arată `1 / 0`."""
    page = Paginated[str].build(items=[], total=0, params=PageParams())
    assert page.model_dump(by_alias=True)["totalPages"] == 1


def test_page_params_reject_oversized_page_size() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PageParams(page=1, page_size=10_000)


def test_error_response_shape_matches_frontend(client) -> None:  # type: ignore[no-untyped-def]
    """`ApiError` din frontend citește exact `code`, `message` și `details`."""
    response = client.get("/api/v1/health/nu-exista")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert isinstance(body["message"], str) and body["message"]
    assert "details" in body
    assert body["requestId"] == response.headers["X-Request-ID"]


def test_settings_expose_the_same_keys_on_both_sides() -> None:
    """Backendul simulat publica aceeasi suprafata de configurare ca serverul.

    Daca listele se despart, ecranul de setari arata in demonstratie alte randuri
    decat in aplicatie — iar cine il vede la client crede ca a vazut sistemul.
    """
    import re
    from pathlib import Path

    from app.api.v1.settings import EXPOSED

    store = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "mock" / "store.ts"
    block = re.search(
        r"export function listSettings\(\): SettingEntry\[\] \{(.*?)\n\}",
        store.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None, "listSettings nu a fost gasit in mock/store.ts"

    frontend = set(re.findall(r'key: "([A-Z_]+)"', block.group(1)))
    assert frontend == {key for key, _, _ in EXPOSED}


def test_setting_groups_match_the_frontend() -> None:
    """`SETTING_GROUPS` din domain.ts este oglinda lui `SettingGroup`."""
    import re
    from pathlib import Path

    from app.api.v1.settings import SettingGroup

    domain = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "domain.ts"
    block = re.search(
        r"export const SETTING_GROUPS = \[(.*?)\] as const;",
        domain.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None, "SETTING_GROUPS nu a fost gasit in types/domain.ts"

    frontend = set(re.findall(r'"([A-Z_]+)"', block.group(1)))
    assert frontend == {group.value for group in SettingGroup}
