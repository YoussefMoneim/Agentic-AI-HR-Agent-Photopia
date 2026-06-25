"""
Registry-level security tests.

These tests exercise the ToolRegistry (the security boundary) rather than calling
tools directly. They verify the "policy before prompt" architecture:
    1. get_specs_for_role() filters the tool list BEFORE the LLM sees it
    2. execute() re-checks the role at execution time (defence in depth)
    3. Every denied call is written to audit_log

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_security.py -v --tb=short
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2
import pytest

import config
from tests.conftest import get_pending_days


# ═══════════════════════════════════════════════════════════════════════════════
# Registry role visibility — "policy before prompt"
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleToolVisibility:
    """
    get_specs_for_role() is called BEFORE the LLM call to filter the tool list.
    The LLM must never see tools it cannot call — this prevents prompt-injection
    tricks that ask the LLM to use a tool it shouldn't know about.
    """

    def test_employee_role_does_not_see_approval_tools(self, registry):
        """Employee tool list must exclude approve, reject, get_pending_approvals."""
        names = {s["name"] for s in registry.get_specs_for_role("employee")}
        assert "approve_leave_request"   not in names, "employee must not see approve"
        assert "reject_leave_request"    not in names, "employee must not see reject"
        assert "get_pending_approvals"   not in names, "employee must not see pending approvals"

    def test_employee_role_sees_own_tools(self, registry):
        """Employee must see the tools they need: submit, check_balance, check_eligibility."""
        names = {s["name"] for s in registry.get_specs_for_role("employee")}
        assert "submit_leave_request"    in names
        assert "check_leave_balance"     in names
        assert "check_leave_eligibility" in names
        assert "cancel_leave_request"    in names

    def test_hr_manager_sees_approval_tools(self, registry):
        """HR manager must see approve, reject, get_pending_approvals."""
        names = {s["name"] for s in registry.get_specs_for_role("hr_manager")}
        assert "approve_leave_request"   in names
        assert "reject_leave_request"    in names
        assert "get_pending_approvals"   in names

    def test_hr_manager_sees_employee_tools_too(self, registry):
        """HR manager also has access to employee-facing read tools."""
        names = {s["name"] for s in registry.get_specs_for_role("hr_manager")}
        assert "check_leave_balance"     in names
        assert "check_leave_eligibility" in names
        assert "get_leave_requests"      in names


# ═══════════════════════════════════════════════════════════════════════════════
# Registry execution — defence in depth (second check at execute time)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistryDeniesAtExecution:
    """
    Even if a caller somehow bypasses get_specs_for_role(), execute() re-checks
    the role and denies calls from unauthorised roles.
    """

    def test_employee_cannot_execute_approve(self, registry, ctx):
        """Registry denies approve_leave_request for employee role at execution time."""
        emp_ctx = ctx()
        result = registry.execute("approve_leave_request", {"request_id": "fake-id"}, emp_ctx)
        assert not result.success
        assert "not permitted" in result.error.lower() or "denied" in result.error.lower()

    def test_employee_cannot_execute_reject(self, registry, ctx):
        """Registry denies reject_leave_request for employee role."""
        emp_ctx = ctx()
        result = registry.execute(
            "reject_leave_request",
            {"request_id": "fake-id", "comment": "trying anyway"},
            emp_ctx,
        )
        assert not result.success
        assert "not permitted" in result.error.lower() or "denied" in result.error.lower()

    def test_employee_cannot_execute_get_pending_approvals(self, registry, ctx):
        """Registry denies get_pending_approvals for employee role."""
        emp_ctx = ctx()
        result = registry.execute("get_pending_approvals", {}, emp_ctx)
        assert not result.success

    def test_unknown_tool_name_is_rejected(self, registry, ctx):
        """Calling a non-existent tool returns an error and does not raise an exception."""
        result = registry.execute("nonexistent_tool", {}, ctx())
        assert not result.success
        assert "unknown" in result.error.lower() or "nonexistent" in result.error.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Audit log — every call must be recorded (Rule 8: never bypass the registry)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditLog:

    def test_denied_call_written_to_audit_log(self, registry, ctx, database_url, tenant_id):
        """
        When the registry denies a call, it must write a row to audit_log
        with action='decision_denied'.
        """
        import time
        emp_ctx = ctx()

        # Record a timestamp so we can find only the rows written by this test
        before_ts = time.time()

        registry.execute("approve_leave_request", {"request_id": "fake-id"}, emp_ctx)

        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    """
                    SELECT action, outcome, actor_role
                    FROM audit_log
                    WHERE tenant_id = %s
                      AND tool_name = 'approve_leave_request'
                      AND actor_role = 'employee'
                      AND EXTRACT(EPOCH FROM created_at) > %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (tenant_id, before_ts),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "Denied call was not written to audit_log"
        action, outcome, actor_role = row
        assert action == "decision_denied", f"Expected action='decision_denied', got '{action}'"
        assert actor_role == "employee"

    def test_allowed_call_written_to_audit_log(self, registry, ctx, database_url, tenant_id):
        """Successful tool calls must also be recorded in audit_log."""
        import time
        before_ts = time.time()
        emp_ctx = ctx()

        registry.execute("check_leave_balance", {}, emp_ctx)

        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SET app.current_tenant_id = %s", (tenant_id,))
                cur.execute(
                    """
                    SELECT action, outcome
                    FROM audit_log
                    WHERE tenant_id = %s
                      AND tool_name = 'check_leave_balance'
                      AND actor_role = 'employee'
                      AND EXTRACT(EPOCH FROM created_at) > %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (tenant_id, before_ts),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, "Allowed call was not written to audit_log"
        action, outcome = row
        assert outcome == "success", f"Expected outcome='success', got '{outcome}'"


# ═══════════════════════════════════════════════════════════════════════════════
# RLS — Row-Level Security
# ═══════════════════════════════════════════════════════════════════════════════

TENANT_TABLES = [
    "users", "employees", "leave_types", "leave_balances",
    "leave_requests", "leave_policies", "workflow_instances",
    "pending_actions", "workflow_events", "audit_log",
]


class TestRowLevelSecurity:

    def test_rls_prevents_cross_tenant_query(self, database_url):
        """Direct SQL without tenant variable must return 0 rows (fail-closed)."""
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SET ROLE fotopia_app")  # non-superuser; subject to RLS
                cur.execute("SELECT COUNT(*) FROM employees")
                assert cur.fetchone()[0] == 0, (
                    "RLS not enforced: employee rows visible without tenant variable. "
                    "Run migration 001_add_rls.sql to enable FORCE ROW LEVEL SECURITY."
                )
        finally:
            conn.close()


class TestRLSEnforced:
    """CI guardrail: all tenant tables must have ENABLE + FORCE RLS."""

    def test_all_tenant_tables_have_force_rls(self, database_url):
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                for table in TENANT_TABLES:
                    cur.execute(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE relname = %s AND relkind = 'r'",
                        (table,),
                    )
                    row = cur.fetchone()
                    assert row and row[0] and row[1], (
                        f"{table}: relrowsecurity={row[0] if row else 'missing'}, "
                        f"relforcerowsecurity={row[1] if row else 'missing'} — both must be True"
                    )
        finally:
            conn.close()

    def test_no_tenant_set_returns_zero_rows(self, database_url):
        """Unset tenant variable → 0 rows across all tenant tables (fail-closed)."""
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SET ROLE fotopia_app")  # non-superuser; subject to RLS
                for table in TENANT_TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    assert cur.fetchone()[0] == 0, (
                        f"{table}: rows visible without tenant variable — RLS not enforced"
                    )
        finally:
            conn.close()

    def test_wrong_tenant_returns_zero_rows(self, database_url):
        """Fake tenant UUID → 0 rows (cross-tenant isolation)."""
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SET ROLE fotopia_app")  # non-superuser; subject to RLS
                cur.execute(
                    "SET app.current_tenant_id = %s",
                    ("00000000-0000-0000-0000-000000000000",),
                )
                cur.execute("SELECT COUNT(*) FROM employees")
                assert cur.fetchone()[0] == 0, "Cross-tenant isolation not enforced"
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Field masking — salary null for hr_staff, visible for hr_manager/admin/employee
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldMasking:

    def test_hr_staff_get_employee_data_salary_is_null(self, registry, ctx):
        """hr_staff calling get_employee_data must receive null salary fields."""
        staff_ctx = ctx(role="hr_staff")
        result = registry.execute("get_employee_data", {"employee_code": "EMP001"}, staff_ctx)
        assert result.success, f"Expected success but got: {result.error}"
        emp = result.data["employee"]
        for field in ("basic_salary", "housing_allowance", "transport_allowance", "total_salary"):
            assert emp.get(field) is None, (
                f"hr_staff must not see {field} — got {emp.get(field)!r}"
            )

    def test_employee_get_own_data_salary_is_not_null(self, registry, ctx):
        """An employee reading their own record must see their salary fields."""
        emp_ctx = ctx(role="employee")
        result = registry.execute("get_employee_data", {"employee_code": "EMP001"}, emp_ctx)
        assert result.success, f"Expected success but got: {result.error}"
        emp = result.data["employee"]
        assert emp.get("basic_salary") is not None, "Employee must see own basic_salary"

    def test_hr_manager_get_employee_data_salary_is_not_null(self, registry, ctx):
        """hr_manager must see salary fields — no masking for this role."""
        mgr_ctx = ctx(role="hr_manager")
        result = registry.execute("get_employee_data", {"employee_code": "EMP001"}, mgr_ctx)
        assert result.success, f"Expected success but got: {result.error}"
        emp = result.data["employee"]
        assert emp.get("basic_salary") is not None, "hr_manager must see basic_salary"

    def test_hr_staff_cannot_call_calculate_end_of_service(self, registry, ctx):
        """calculate_end_of_service is gated to hr_manager/admin only (Gate 1)."""
        staff_ctx = ctx(role="hr_staff")
        result = registry.execute(
            "calculate_end_of_service",
            {"employee_code": "EMP001", "last_working_day": "2025-12-31"},
            staff_ctx,
        )
        assert not result.success
        assert "not permitted" in (result.error or "").lower() or "denied" in (result.error or "").lower()
