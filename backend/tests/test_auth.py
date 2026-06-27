"""
Integration tests for JWT authentication (Fix 2).

Tests use FastAPI's TestClient so the full HTTP stack (headers, status codes,
_build_context) is exercised without a real LLM call.

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 \
        env DEBUG_ALLOW_DEMO_ROLE=false python -m pytest tests/test_auth.py -v --tb=short
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from core.auth import issue_jwt


@pytest.fixture(scope="module")
def client():
    """TestClient runs the full app lifespan (DB connect, registry build)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def tenant_id() -> str:
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = %s", ("fotopia",))
            return str(cur.fetchone()[0])
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TestLoginEndpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoginEndpoint:

    def test_valid_credentials_return_token(self, client):
        res = client.post("/auth/login", json={"email": "saif.hassan@fotopia.ai", "password": "demo123"})
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["role"] == "employee"
        assert data["employee_code"] == "EMP001"

    def test_wrong_password_returns_401(self, client):
        res = client.post("/auth/login", json={"email": "saif.hassan@fotopia.ai", "password": "wrong"})
        assert res.status_code == 401

    def test_unknown_email_returns_401(self, client):
        res = client.post("/auth/login", json={"email": "nobody@fotopia.ai", "password": "demo123"})
        assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# TestJWTAuthentication
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTAuthentication:

    def test_valid_jwt_returns_identity(self, client, tenant_id):
        token = issue_jwt(
            user_id="test-user-emp",
            role="employee",
            tenant_id=tenant_id,
            employee_code="EMP001",
            display_name="Saif Ahmed Hassan",
        )
        res = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "employee"
        assert data["employee_code"] == "EMP001"

    def test_valid_hr_manager_jwt(self, client, tenant_id):
        token = issue_jwt(
            user_id="test-user-mgr",
            role="hr_manager",
            tenant_id=tenant_id,
            employee_code="EMP002",
            display_name="Nourhan Hosny",
        )
        res = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json()["role"] == "hr_manager"

    def test_forged_token_rejected(self, client):
        res = client.get("/api/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert res.status_code == 401

    def test_expired_token_rejected(self, client, tenant_id):
        expired_payload = {
            "sub": "test-user",
            "tenant_id": tenant_id,
            "role": "employee",
            "employee_code": "EMP001",
            "display_name": "Test",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, config.JWT_SECRET, algorithm="HS256")
        res = client.get("/api/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert res.status_code == 401

    def test_wrong_tenant_token_rejected(self, client):
        token = issue_jwt(
            user_id="test-user",
            role="employee",
            tenant_id="00000000-0000-0000-0000-000000000000",
            employee_code="EMP001",
            display_name="Test",
        )
        res = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# TestBypassClosed
# ═══════════════════════════════════════════════════════════════════════════════

class TestBypassClosed:

    def test_demo_role_without_jwt_rejected(self, client, monkeypatch):
        """With bypass OFF, unauthenticated requests must be rejected.
        Uses monkeypatch to ensure bypass is OFF regardless of env, so the test
        always exercises and verifies the closed-bypass code path."""
        monkeypatch.setattr(config, "DEBUG_ALLOW_DEMO_ROLE", False)
        # No Authorization header — must get 401, not a fallback identity
        res = client.get("/api/me")
        assert res.status_code == 401
