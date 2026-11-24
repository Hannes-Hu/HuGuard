"""
Integration tests for the FastAPI endpoints.

We use TestClient (synchronous) for simple endpoint tests and
AsyncClient for the SSE streaming endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.audit import AuditStatus


@pytest.fixture
def client() -> TestClient:
    # We patch get_graph and close_graph so the test lifespan doesn't touch the live db
    with patch("app.main.get_graph", new_callable=AsyncMock) as mock_graph, \
         patch("app.main.close_graph", new_callable=AsyncMock):
        mock_graph.return_value = MagicMock()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAuditStartEndpoint:
    def test_start_with_valid_snippet_returns_202_and_thread_id(
        self, client: TestClient
    ) -> None:
        payload = {
            "source_code": "x = 1\ny = 2\n",
            "filename": "test.py",
            "language": "python",
        }
        response = client.post("/api/v1/audit/start", json=payload)
        assert response.status_code == 202
        body = response.json()
        assert "thread_id" in body
        assert body["status"] == AuditStatus.PENDING.value
        # thread_id should be a valid UUID4 format
        import uuid
        uuid.UUID(body["thread_id"])  # raises if invalid

    def test_start_with_empty_source_returns_422(self, client: TestClient) -> None:
        payload = {"source_code": "", "filename": "test.py"}
        response = client.post("/api/v1/audit/start", json=payload)
        assert response.status_code == 422

    def test_start_missing_source_code_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/v1/audit/start", json={"filename": "test.py"})
        assert response.status_code == 422


class TestApproveEndpoint:
    def test_approve_nonexistent_thread_returns_404(self, client: TestClient) -> None:
        with patch(
            "app.routers.audit.resume_after_approval",
            new_callable=AsyncMock,
            side_effect=ValueError("No checkpoint found for thread_id='ghost-thread'"),
        ):
            response = client.post(
                "/api/v1/audit/ghost-thread/approve",
                json={"decision": "approve"},
            )
        assert response.status_code == 404

    def test_approve_wrong_state_thread_returns_409(self, client: TestClient) -> None:
        with patch(
            "app.routers.audit.resume_after_approval",
            new_callable=AsyncMock,
            side_effect=ValueError("Thread 'x' is not awaiting approval (status=running)"),
        ):
            response = client.post(
                "/api/v1/audit/x/approve",
                json={"decision": "reject", "comment": "not ready"},
            )
        assert response.status_code == 409

    def test_invalid_decision_value_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/audit/some-thread/approve",
            json={"decision": "maybe"},
        )
        assert response.status_code == 422
