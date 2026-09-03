"""Antetele de securitate stau pe **orice** răspuns (§42).

Existau deja, dar numai în două locuri: pe fișierele servite și în `vercel.json`.
O instalare pe serverul cabinetului — `docker compose`, adică exact varianta din
documentație — nu avea niciunul. Verificat pe un server pornit: `X-Content-Type-
Options`, `Referrer-Policy` și `Content-Security-Policy` lipseau de pe toate
răspunsurile JSON.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Environment, settings
from app.core.middleware import HSTS_HEADER, SECURITY_HEADERS


@pytest.mark.parametrize("header", sorted(SECURITY_HEADERS))
def test_headers_are_present_on_a_normal_response(client: TestClient, header: str) -> None:
    response = client.get("/health/live")
    assert response.headers.get(header) == SECURITY_HEADERS[header]


@pytest.mark.parametrize("header", sorted(SECURITY_HEADERS))
def test_headers_are_present_on_an_error_response(client: TestClient, header: str) -> None:
    """Și pe erori. Un 401 este exact răspunsul pe care îl vede un atacator."""
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers.get(header) == SECURITY_HEADERS[header]


def test_hsts_only_outside_development(client: TestClient) -> None:
    """Pe `http://localhost`, HSTS ar face browserul să refuze development-ul.

    Antetul se ține minte: odată primit, browserul refuză orice cerere necriptată
    către aceeași gazdă, luni de zile. Pe localhost asta blochează munca.
    """
    response = client.get("/health/live")
    if settings.environment is Environment.DEVELOPMENT:
        assert HSTS_HEADER not in response.headers
    else:  # pragma: no cover — suita rulează în development
        assert response.headers[HSTS_HEADER].startswith("max-age=")


def test_file_delivery_keeps_its_own_stricter_policy() -> None:
    """Previzualizarea are politica ei; antetul global nu are voie s-o slăbească.

    Fișierul servit poartă `sandbox` — un PDF cu JavaScript nu trebuie să poată
    face nimic. Iar încadrarea trebuie să rămână posibilă de pe aceeași origine,
    altfel `DENY`-ul global ar goli chiar ecranul de verificare.
    """
    from app.services.document_delivery import SECURITY_HEADERS as FILE_HEADERS

    assert "sandbox" in FILE_HEADERS["Content-Security-Policy"]
    assert FILE_HEADERS["X-Frame-Options"] == "SAMEORIGIN"
