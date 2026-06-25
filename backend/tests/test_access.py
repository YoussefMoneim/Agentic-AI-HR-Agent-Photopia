"""
Unit tests for core.access.can_access() — no DB, no registry.

Tests every deny path (Gate 1, Gate 2) and every mask path (Gate 3).
Run standalone:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_access.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.access import SALARY_FIELDS, AccessDecision, can_access
from tools.base import ToolContext


def _ctx(role: str, employee_code: str = "EMP001") -> ToolContext:
    return ToolContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="user-1",
        role=role,
        employee_code=employee_code,
        display_name="Test User",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Gate 1 — RBAC
# ═══════════════════════════════════════════════════════════════════════════════

class TestGate1RBAC:

    def test_unknown_action_is_denied(self):
        d = can_access(_ctx("hr_manager"), "do_something_unknown", {})
        assert not d.allowed
        assert "unknown" in d.reason.lower()

    def test_approve_leave_employee_role_denied(self):
        d = can_access(_ctx("employee"), "approve_leave", {
            "assigned_manager_db_id": "mgr-1",
            "caller_employee_db_id": "mgr-1",
        })
        assert not d.allowed
        assert "employee" in d.reason.lower() or "not permitted" in d.reason.lower()

    def test_reject_leave_employee_role_denied(self):
        d = can_access(_ctx("employee"), "reject_leave", {
            "assigned_manager_db_id": "mgr-1",
            "caller_employee_db_id": "mgr-1",
        })
        assert not d.allowed


# ═══════════════════════════════════════════════════════════════════════════════
# Gate 2 — Row/Resource ACL
# ═══════════════════════════════════════════════════════════════════════════════

class TestGate2ResourceACL:

    # read_employee_row
    def test_employee_can_read_own_row(self):
        d = can_access(_ctx("employee", "EMP001"), "read_employee_row", {"employee_code": "EMP001"})
        assert d.allowed

    def test_employee_denied_other_employee_row(self):
        d = can_access(_ctx("employee", "EMP001"), "read_employee_row", {"employee_code": "EMP002"})
        assert not d.allowed
        assert "own" in d.reason.lower()

    def test_hr_staff_can_read_any_row(self):
        d = can_access(_ctx("hr_staff"), "read_employee_row", {"employee_code": "EMP999"})
        assert d.allowed

    def test_hr_manager_can_read_any_row(self):
        d = can_access(_ctx("hr_manager"), "read_employee_row", {"employee_code": "EMP999"})
        assert d.allowed

    # cancel_leave
    def test_employee_can_cancel_own_leave(self):
        d = can_access(_ctx("employee", "EMP001"), "cancel_leave", {"request_employee_code": "EMP001"})
        assert d.allowed

    def test_employee_denied_cancel_other_leave(self):
        d = can_access(_ctx("employee", "EMP001"), "cancel_leave", {"request_employee_code": "EMP002"})
        assert not d.allowed

    def test_hr_staff_can_cancel_any_leave(self):
        d = can_access(_ctx("hr_staff"), "cancel_leave", {"request_employee_code": "EMP999"})
        assert d.allowed

    # approve_leave
    def test_correct_manager_can_approve(self):
        d = can_access(_ctx("hr_manager"), "approve_leave", {
            "assigned_manager_db_id": "db-uuid-42",
            "caller_employee_db_id": "db-uuid-42",
        })
        assert d.allowed

    def test_wrong_manager_denied_approve(self):
        d = can_access(_ctx("hr_manager"), "approve_leave", {
            "assigned_manager_db_id": "db-uuid-42",
            "caller_employee_db_id": "db-uuid-99",
        })
        assert not d.allowed
        assert "assigned approver" in d.reason.lower()

    def test_approve_with_no_manager_assigned_is_allowed(self):
        """If assigned_manager_db_id is None/missing, skip the assignment check."""
        d = can_access(_ctx("hr_manager"), "approve_leave", {
            "assigned_manager_db_id": None,
            "caller_employee_db_id": "db-uuid-99",
        })
        assert d.allowed

    # read_leave_balance
    def test_employee_can_read_own_leave_balance(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_balance", {"employee_code": "EMP001"})
        assert d.allowed

    def test_employee_denied_other_leave_balance(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_balance", {"employee_code": "EMP002"})
        assert not d.allowed

    def test_hr_staff_can_read_any_leave_balance(self):
        d = can_access(_ctx("hr_staff"), "read_leave_balance", {"employee_code": "EMP999"})
        assert d.allowed

    # read_leave_eligibility
    def test_employee_can_read_own_eligibility(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_eligibility", {"employee_code": "EMP001"})
        assert d.allowed

    def test_employee_denied_other_eligibility(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_eligibility", {"employee_code": "EMP002"})
        assert not d.allowed

    # read_leave_requests
    def test_employee_can_read_own_leave_requests(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_requests", {"employee_code": "EMP001"})
        assert d.allowed

    def test_employee_denied_other_leave_requests(self):
        d = can_access(_ctx("employee", "EMP001"), "read_leave_requests", {"employee_code": "EMP002"})
        assert not d.allowed

    def test_hr_can_read_all_leave_requests_no_target(self):
        """HR with employee_code=None means 'list all' — allowed."""
        d = can_access(_ctx("hr_manager"), "read_leave_requests", {"employee_code": None})
        assert d.allowed


# ═══════════════════════════════════════════════════════════════════════════════
# Gate 3 — Field Masking
# ═══════════════════════════════════════════════════════════════════════════════

class TestGate3FieldMasking:

    def test_hr_staff_salary_fields_masked(self):
        d = can_access(_ctx("hr_staff"), "read_employee_row", {"employee_code": "EMP001"})
        assert d.allowed
        assert SALARY_FIELDS <= d.masked_fields, (
            f"Expected all salary fields to be masked for hr_staff. Got: {d.masked_fields}"
        )

    def test_employee_own_row_no_masking(self):
        d = can_access(_ctx("employee", "EMP001"), "read_employee_row", {"employee_code": "EMP001"})
        assert d.allowed
        assert len(d.masked_fields) == 0, f"Employee reading own row must not have fields masked. Got: {d.masked_fields}"

    def test_hr_manager_no_masking(self):
        d = can_access(_ctx("hr_manager"), "read_employee_row", {"employee_code": "EMP001"})
        assert d.allowed
        assert len(d.masked_fields) == 0

    def test_admin_no_masking(self):
        d = can_access(_ctx("admin"), "read_employee_row", {"employee_code": "EMP001"})
        assert d.allowed
        assert len(d.masked_fields) == 0

    def test_masked_fields_is_frozenset(self):
        """Callers iterate masked_fields; must be a frozenset."""
        d = can_access(_ctx("hr_staff"), "read_employee_row", {"employee_code": "EMP001"})
        assert isinstance(d.masked_fields, frozenset)
