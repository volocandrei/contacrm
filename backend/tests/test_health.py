"""Health checks și igiena răspunsurilor."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings


def test_liveness_does_not_touch_dependencies(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_degraded_without_database(client: TestClient) -> None:
    """Fără Postgres pornit, `/health/ready` trebuie să spună 503, nu 200."""
    response = client.get("/health/ready")
    body = response.json()

    assert body["database"] in (True, False)
    if body["database"]:
        assert response.status_code == 200
        assert body["status"] == "ok"
    else:
        assert response.status_code == 503
        assert body["status"] == "degraded"


def test_health_is_reachable_with_and_without_version_prefix(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    assert client.get(f"{settings.api_v1_prefix}/health/live").status_code == 200


def test_info_exposes_no_secrets(client: TestClient) -> None:
    response = client.get("/health/info")
    assert response.status_code == 200

    body = response.json()
    assert body["environment"] == "development"
    assert body["ocrProvider"] == "mock"
    assert body["defaultTimezone"] == "Europe/Bucharest"

    forbidden = {"secretKey", "secret_key", "databaseUrl", "database_url", "aiApiKey"}
    assert forbidden.isdisjoint(body)
    assert settings.secret_key not in response.text


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health/live")
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_valid_incoming_request_id_is_preserved(client: TestClient) -> None:
    incoming = str(uuid.uuid4())
    response = client.get("/health/live", headers={"X-Request-ID": incoming})
    assert response.headers["X-Request-ID"] == incoming


def test_forged_request_id_is_replaced(client: TestClient) -> None:
    """Text arbitrar din exterior nu ajunge în log."""
    response = client.get("/health/live", headers={"X-Request-ID": "'; DROP TABLE documents;--"})
    assert uuid.UUID(response.headers["X-Request-ID"])
