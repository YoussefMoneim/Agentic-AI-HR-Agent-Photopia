"""
Shared fixtures for the leave system integration test suite.

All tests run against the real PostgreSQL database (seeded via docker-compose).
Run:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/ -v --tb=short

Key seeded data:
    EMP001: Saif Ahmed Hassan, R&D, hired 2022-03-15, manager=EMP002
    EMP002: Nourhan Hosny, HR,  hired 2021-06-01, NO MANAGER
    EMP003: Omar Alsayed,   R&D, hired 2023-01-10, manager=EMP002
    Annual balance 2026: 21 days allocated for all employees
    Leave policies: annual (90-day probation, 2-day min notice), WFH (2/week, 8/month)
"""
import os
import sys

# Add backend root to sys.path so imports resolve when running from the container
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock

import psycopg2
import pytest

import config
from audit.logger import AuditLogger
from data.postgresql import PostgreSQLDataSource
from tools.base import ToolContext
from tools.registry import build_registry


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup helper — resets leave state without touching seeded allocations
# ──────────────────────────────────────────────────────────────────────────────

def _cleanup(database_url: str, tenant_id: str) -> None:
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                # Delete in FK dependency order (workflow_events → pending_actions → workflow_instances)
                cur.execute("DELETE FROM workflow_events   WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM pending_actions   WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM workflow_instances WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM leave_requests    WHERE tenant_id = %s", (tenant_id,))
                # Reset transactional balance columns; leave allocated_days intact
                cur.execute(
                    "UPDATE leave_balances SET pending_days = 0, used_days = 0 "
                    "WHERE tenant_id = %s AND year = 2026",
                    (tenant_id,),
                )
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Session-scoped fixtures (created once per test run)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def mock_send_email_globally():
    """Prevent the test suite from sending real emails via SMTP.
    Tests that need to assert on email calls (test_email_correlation.py) patch
    send_email locally with unittest.mock.patch — those local patches take precedence
    over this session-level fixture and continue to work correctly."""
    with unittest.mock.patch("services.email.send_email", return_value=True):
        yield


@pytest.fixture(scope="session")
def database_url() -> str:
    return config.DATABASE_URL


@pytest.fixture(scope="session")
def tenant_id(database_url: str) -> str:
    """Fetch the fotopia tenant UUID from the DB — seed.sql uses gen_random_uuid()."""
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = %s", ("fotopia",))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    "Fotopia tenant not found. Did seed.sql run?\n"
                    "Try: docker compose down -v && docker compose up"
                )
            return str(row[0])
    finally:
        conn.close()


@pytest.fixture(scope="session")
def ds(database_url: str) -> PostgreSQLDataSource:
    return PostgreSQLDataSource(database_url)


@pytest.fixture(scope="session")
def registry(ds: PostgreSQLDataSource, database_url: str):
    audit_logger = AuditLogger(database_url)
    return build_registry(ds, audit_logger)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def make_jwt(tenant_id: str):
    """Factory that returns a signed JWT for any employee_code + role combo.

    Usage::
        token = make_jwt(employee_code="EMP002", role="hr_manager")
        headers = {"Authorization": f"Bearer {token}"}
    """
    from core.auth import issue_jwt

    def _make(employee_code: str, role: str) -> str:
        return issue_jwt(
            user_id=f"test-{employee_code.lower()}",
            role=role,
            tenant_id=tenant_id,
            employee_code=employee_code,
            display_name=employee_code,
        )

    return _make


# ──────────────────────────────────────────────────────────────────────────────
# Per-test fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_leave_data(database_url: str, tenant_id: str):
    """Guarantee clean leave state before and after every test."""
    _cleanup(database_url, tenant_id)
    yield
    _cleanup(database_url, tenant_id)


@pytest.fixture
def db_conn(database_url: str, tenant_id: str):
    """Raw psycopg2 connection for direct DB assertions. Auto-closed after test."""
    conn = psycopg2.connect(database_url)
    with conn.cursor() as cur:
        cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
    yield conn
    conn.close()


@pytest.fixture
def ctx(tenant_id: str):
    """
    Factory fixture for ToolContext objects.

    Usage::

        def test_something(ctx):
            emp_ctx = ctx()                                     # EMP001 employee (default)
            mgr_ctx = ctx(role="hr_manager", employee_code="EMP002")
    """
    def _make(role: str = "employee", employee_code: str = "EMP001") -> ToolContext:
        return ToolContext(
            tenant_id=tenant_id,
            user_id="test-user",
            role=role,
            employee_code=employee_code,
        )
    return _make


@pytest.fixture
def recently_hired_employee(database_url: str, tenant_id: str):
    """
    Create a temporary employee hired TODAY for probation tests.
    Deleted automatically after the test.
    """
    emp_code = "TEST_PROBATION_EMP"
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    """
                    INSERT INTO employees (tenant_id, employee_code, full_name, department,
                                          employment_type, start_date, currency)
                    VALUES (%s, %s, 'Test Probation Employee', 'R&D', 'Full-time', CURRENT_DATE, 'EGP')
                    ON CONFLICT (tenant_id, employee_code) DO NOTHING
                    """,
                    (tenant_id, emp_code),
                )
    finally:
        conn.close()

    yield emp_code

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    "DELETE FROM employees WHERE tenant_id = %s AND employee_code = %s",
                    (tenant_id, emp_code),
                )
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Direct DB helpers (used in test body, not as fixtures)
# ──────────────────────────────────────────────────────────────────────────────

def _balance_col(conn, tenant_id: str, employee_code: str,
                 leave_type_code: str, column: str, year: int = 2026) -> float:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT lb.{column}
            FROM leave_balances lb
            JOIN employees e  ON e.id  = lb.employee_id  AND e.tenant_id  = lb.tenant_id
            JOIN leave_types lt ON lt.id = lb.leave_type_id AND lt.tenant_id = lb.tenant_id
            WHERE lb.tenant_id = %s AND e.employee_code = %s
              AND lt.code = %s AND lb.year = %s
            """,
            (tenant_id, employee_code, leave_type_code, year),
        )
        row = cur.fetchone()
        return float(row[0]) if row else 0.0


def get_pending_days(conn, tenant_id: str, employee_code: str,
                     leave_type_code: str, year: int = 2026) -> float:
    return _balance_col(conn, tenant_id, employee_code, leave_type_code, "pending_days", year)


def get_used_days(conn, tenant_id: str, employee_code: str,
                  leave_type_code: str, year: int = 2026) -> float:
    return _balance_col(conn, tenant_id, employee_code, leave_type_code, "used_days", year)
