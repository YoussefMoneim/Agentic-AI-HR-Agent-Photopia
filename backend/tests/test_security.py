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
# RLS — Row-Level Security (Phase 1.5 TODO)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRowLevelSecurity:

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "RLS not yet enabled — Phase 1.5 TODO. "
            "Once FORCE RLS is added to all tenant_id tables, a query without "
            "a tenant_id filter must return 0 rows even as a DB superuser."
        ),
    )
    def test_rls_prevents_cross_tenant_query(self, database_url, tenant_id):
        """
        Direct SQL without tenant_id filter must return 0 rows when RLS is enforced.
        This test is xfail until Phase 1.5 adds FORCE ROW LEVEL SECURITY to every table.

        Current behaviour: query returns all rows (no RLS).
        Expected behaviour (Phase 1.5): query returns 0 rows (RLS filters by tenant_id).
        """
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                # This query intentionally omits the tenant_id filter.
                # With RLS enabled+forced, it should return 0 rows.
                cur.execute("SELECT COUNT(*) FROM employees")
                total = cur.fetchone()[0]
            # Phase 1.5 expectation: RLS returns 0 rows for a non-tenant session
            assert total == 0, (
                f"RLS not enforced: {total} employee rows visible without tenant filter. "
                "Add FORCE ROW LEVEL SECURITY + policy to the employees table."
            )
        finally:
            conn.close()
