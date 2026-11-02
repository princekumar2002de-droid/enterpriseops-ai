"""Health endpoint and request-context tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.session import build_engine, get_engine
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "EnterpriseOps AI"


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/health/live")
    assert len(response.headers["X-Request-ID"]) == 32


def test_valid_incoming_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_malicious_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "x\nforged log line"})
    assert response.headers["X-Request-ID"] != "x\nforged log line"
    assert len(response.headers["X-Request-ID"]) == 32


def test_readiness_is_503_when_database_unreachable(client: TestClient) -> None:
    # Port 1 on localhost: connection refused immediately.
    dead_engine = build_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", connect_timeout_seconds=1
    )
    app.dependency_overrides[get_engine] = lambda: dead_engine
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] is False


@pytest.mark.integration
def test_readiness_is_ready_after_migrations(client: TestClient, migrated_engine: Engine) -> None:
    app.dependency_overrides[get_engine] = lambda: migrated_engine
    response = client.get("/health/ready")
    assert response.status_code == 200, response.json()
    checks = response.json()["checks"]
    assert checks["database"] is True
    assert checks["pgvector_version"]
    assert checks["migration_revision"] == "0001"


def test_openapi_schema_is_published(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/health/ready" in response.json()["paths"]
