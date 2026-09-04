"""Motorul de intenții și bariera de permisiuni, fără bază de date.

Bariera merită test propriu. În configurația de azi niciun rol nu duce lipsă de
vreo permisiune cerută de unelte — deci ramura de refuz nu se poate atinge prin
API, dar există tocmai pentru unealta care se va adăuga mâine. Un cod de apărare
netestat este cod care nu apără.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.permissions import Permission, RoleCode, permissions_for
from app.services.assistant.base import AssistantContext
from app.services.assistant.rules import extract_client, extract_month, normalise
from app.services.assistant.tools import allowed_tools, run_tool


def context(*permissions: Permission) -> AssistantContext:
    return AssistantContext(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        user_name="Cine Întreabă",
        permissions=frozenset(permissions),
    )


class TestThePermissionGate:
    def test_a_tool_does_not_run_without_its_permission(self) -> None:
        """Refuzul vine **înaintea** interogării: sesiunea nici nu este atinsă."""
        empty = context()

        result = run_tool("workload", None, empty, "")  # type: ignore[arg-type]

        assert "documents:read" in result.text
        assert result.links == []

    def test_the_refusal_names_what_is_missing(self) -> None:
        """Ca omul să știe pe cine să întrebe, nu să creadă că nu există date."""
        result = run_tool("find_client", None, context(), "")  # type: ignore[arg-type]

        assert "clients:read" in result.text
        assert "nu pot răspunde" in result.text

    def test_an_unknown_tool_is_a_programming_error(self) -> None:
        with pytest.raises(KeyError):
            run_tool("stergi_tot", None, context(), "")  # type: ignore[arg-type]

    @pytest.mark.parametrize("role", list(RoleCode))
    def test_every_role_gets_at_least_one_capability(self, role: RoleCode) -> None:
        """Un chat care nu poate face nimic pentru un rol nu trebuie oferit acelui rol."""
        available = allowed_tools(context(*permissions_for(role)))

        assert available, f"{role.value} nu are nicio unealtă"

    def test_the_offer_shrinks_with_the_role(self) -> None:
        viewer = allowed_tools(context(*permissions_for(RoleCode.VIEWER)))
        admin = allowed_tools(context(*permissions_for(RoleCode.ADMIN)))

        assert len(viewer) <= len(admin)


class TestReadingTheQuestion:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Șerban", "serban"),
            ("CÂTE", "cate"),
            ("lipsește", "lipseste"),
        ],
    )
    def test_diacritics_do_not_matter(self, written: str, expected: str) -> None:
        """Într-un chat se scrie repede și fără diacritice."""
        assert normalise(written) == expected

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("ce lipsește pe 2026-08?", "2026-08"),
            ("documente lipsă august", "2026-08"),
            ("ce lipsește?", ""),
        ],
    )
    def test_the_month_is_read_when_written(self, question: str, expected: str) -> None:
        found = extract_month(question)
        if expected:
            assert found.endswith(expected[-3:])
        else:
            assert found == ""

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("deschide Alfa Conta SRL", "Alfa Conta SRL"),
            ("ce lipsește la Beta Prod", "Beta Prod"),
            ("clientul Gamma", "Gamma"),
        ],
    )
    def test_the_firm_is_what_remains(self, question: str, expected: str) -> None:
        """Nu încearcă să fie deșteaptă: taie comanda și lasă restul uneltei."""
        assert extract_client(question) == expected
