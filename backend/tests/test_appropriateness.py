"""
Appropriateness layer tests — Step 6.

Two test classes cover pure logic (no DB):
  TestSensitivityMismatch — Check 1: restricted doc accessed by non-permitted role
  TestOvershareRisk       — Check 2: salary content going to low-permission recipient

Two classes require the real DB:
  TestAuditTrail          — appropriateness_flag written to workflow_events; decision recorded
  TestUnflaggedNoEvent    — clean path: no flag, no event row

Run inside Docker:
    docker exec fotopia-hr-agent-backend-1 python -m pytest tests/test_appropriateness.py -v --tb=short
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from tools.base import ToolContext
from workflow.appropriateness import (
    AppropriatenessDecision,
    check_appropriateness,
    record_appropriateness_decision,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ctx(tenant_id: str, role: str, employee_code: str = "EMP002") -> ToolContext:
    return ToolContext(
        tenant_id=tenant_id,
        user_id="test-user",
        role=role,
        employee_code=employee_code,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Check 1 — sensitivity_mismatch (access_document)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSensitivityMismatch:

    def test_restricted_doc_accessed_by_hr_staff_is_flagged(self, tenant_id):
        """hr_staff accessing a salary_certificate history must be flagged."""
        ctx = _ctx(tenant_id, "hr_staff")
        decision = check_appropriateness(
            ctx, "access_document",
            {"document_types": ["salary_certificate"]},
            None,
        )
        assert decision.flagged is True
        assert decision.flag_code == "sensitivity_mismatch"
        assert decision.severity == "warning"

    def test_restricted_doc_accessed_by_hr_manager_is_not_flagged(self, tenant_id):
        """hr_manager is permitted for restricted docs — no flag."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "access_document",
            {"document_types": ["salary_certificate"]},
            None,
        )
        assert decision.flagged is False

    def test_internal_doc_accessed_by_hr_staff_is_not_flagged(self, tenant_id):
        """hr_staff is permitted for internal docs (twimc_letter) — no flag."""
        ctx = _ctx(tenant_id, "hr_staff")
        decision = check_appropriateness(
            ctx, "access_document",
            {"document_types": ["twimc_letter"]},
            None,
        )
        assert decision.flagged is False

    def test_mixed_doc_list_with_restricted_is_flagged(self, tenant_id):
        """A list containing at least one restricted doc triggers the flag for hr_staff."""
        ctx = _ctx(tenant_id, "hr_staff")
        decision = check_appropriateness(
            ctx, "access_document",
            {"document_types": ["twimc_letter", "salary_certificate"]},
            None,
        )
        assert decision.flagged is True
        assert decision.flag_code == "sensitivity_mismatch"

    def test_empty_doc_list_is_not_flagged(self, tenant_id):
        """No documents in history → no sensitivity to check."""
        ctx = _ctx(tenant_id, "hr_staff")
        decision = check_appropriateness(
            ctx, "access_document",
            {"document_types": []},
            None,
        )
        assert decision.flagged is False


# ═══════════════════════════════════════════════════════════════════════════════
# Check 2 — overshare_risk (generate_document | send_document | notify)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOvershareRisk:

    def test_salary_doc_sent_to_unknown_recipient_is_flagged(self, tenant_id):
        """salary_certificate with recipient_role=None (external) → overshare_risk."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "send_document",
            {"document_type": "salary_certificate", "recipient_role": None},
            None,
        )
        assert decision.flagged is True
        assert decision.flag_code == "overshare_risk"
        assert decision.severity == "warning"

    def test_salary_doc_sent_to_hr_manager_is_not_flagged(self, tenant_id):
        """hr_manager recipient has salary visibility — no flag."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "send_document",
            {"document_type": "salary_certificate", "recipient_role": "hr_manager"},
            None,
        )
        assert decision.flagged is False

    def test_non_salary_doc_sent_to_unknown_is_not_flagged(self, tenant_id):
        """twimc_letter is internal but not salary-restricted — no overshare flag."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "send_document",
            {"document_type": "twimc_letter", "recipient_role": None},
            None,
        )
        assert decision.flagged is False

    def test_payload_with_salary_fields_is_flagged(self, tenant_id):
        """notify action with basic_salary in payload_fields → overshare_risk."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "notify",
            {"payload_fields": ["basic_salary", "employee_name"], "recipient_role": None},
            None,
        )
        assert decision.flagged is True
        assert decision.flag_code == "overshare_risk"

    def test_generate_salary_cert_with_restricted_recipient_not_flagged(self, tenant_id):
        """admin recipient has salary visibility — no overshare flag."""
        ctx = _ctx(tenant_id, "hr_manager")
        decision = check_appropriateness(
            ctx, "generate_document",
            {"document_type": "salary_certificate", "recipient_role": "admin"},
            None,
        )
        assert decision.flagged is False


# ═══════════════════════════════════════════════════════════════════════════════
# Audit trail — requires real DB (registry + ds fixtures from conftest)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditTrail:

    def _seed_salary_cert(self, registry, tenant_id):
        """Generate a salary cert as hr_manager (no flag) to populate audit_log."""
        mgr_ctx = ToolContext(
            tenant_id=tenant_id, user_id="test-user",
            role="hr_manager", employee_code="EMP002",
        )
        result = registry.execute(
            "generate_salary_certificate", {"employee_code": "EMP001"}, mgr_ctx
        )
        assert result.success, f"Salary cert generation failed: {result.error}"

    def test_flag_writes_workflow_event_with_null_human_decision(
        self, registry, ds, tenant_id, db_conn
    ):
        """hr_staff accessing docs for employee with a salary cert must write
        a workflow_events row with human_decision=null."""
        self._seed_salary_cert(registry, tenant_id)

        staff_ctx = ToolContext(
            tenant_id=tenant_id, user_id="test-user",
            role="hr_staff", employee_code="EMP002",
        )
        result = registry.execute(
            "get_employee_documents", {"employee_code": "EMP001"}, staff_ctx
        )
        assert result.success, f"get_employee_documents failed: {result.error}"

        flag = (result.data or {}).get("appropriateness_flag")
        assert flag is not None, "Expected appropriateness_flag in result data"
        assert flag["flagged"] is True
        assert flag["flag_code"] == "sensitivity_mismatch"
        event_id = flag["event_id"]
        assert event_id, "event_id must be present in appropriateness_flag"

        # Verify workflow_events row was written with human_decision: null
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, data
                FROM workflow_events
                WHERE id = %s::uuid AND tenant_id = %s
                """,
                (event_id, tenant_id),
            )
            row = cur.fetchone()
        assert row is not None, "workflow_events row was not written"
        assert row[0] == "appropriateness_flag"
        assert row[1].get("human_decision") is None, (
            "human_decision must be null until the human responds"
        )

    def test_record_proceeded_updates_event(self, registry, ds, tenant_id, db_conn):
        """record_appropriateness_decision(..., 'proceeded') sets human_decision='proceeded'."""
        self._seed_salary_cert(registry, tenant_id)

        staff_ctx = ToolContext(
            tenant_id=tenant_id, user_id="test-user",
            role="hr_staff", employee_code="EMP002",
        )
        result = registry.execute(
            "get_employee_documents", {"employee_code": "EMP001"}, staff_ctx
        )
        event_id = result.data["appropriateness_flag"]["event_id"]

        record_appropriateness_decision(tenant_id, event_id, "proceeded", ds)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM workflow_events WHERE id = %s::uuid AND tenant_id = %s",
                (event_id, tenant_id),
            )
            data = cur.fetchone()[0]
        assert data.get("human_decision") == "proceeded"

    def test_record_cancelled_updates_event(self, registry, ds, tenant_id, db_conn):
        """record_appropriateness_decision(..., 'cancelled') sets human_decision='cancelled'."""
        self._seed_salary_cert(registry, tenant_id)

        staff_ctx = ToolContext(
            tenant_id=tenant_id, user_id="test-user",
            role="hr_staff", employee_code="EMP002",
        )
        result = registry.execute(
            "get_employee_documents", {"employee_code": "EMP001"}, staff_ctx
        )
        event_id = result.data["appropriateness_flag"]["event_id"]

        record_appropriateness_decision(tenant_id, event_id, "cancelled", ds)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM workflow_events WHERE id = %s::uuid AND tenant_id = %s",
                (event_id, tenant_id),
            )
            data = cur.fetchone()[0]
        assert data.get("human_decision") == "cancelled"

    def test_unflagged_action_writes_no_appropriateness_event(
        self, registry, tenant_id, db_conn
    ):
        """hr_manager generating a salary cert must NOT produce an appropriateness_flag event."""
        mgr_ctx = ToolContext(
            tenant_id=tenant_id, user_id="test-user",
            role="hr_manager", employee_code="EMP002",
        )
        result = registry.execute(
            "generate_salary_certificate", {"employee_code": "EMP001"}, mgr_ctx
        )
        assert result.success
        # No appropriateness_flag in the result
        assert (result.data or {}).get("appropriateness_flag") is None

        # No appropriateness_flag row in workflow_events
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM workflow_events
                WHERE tenant_id = %s AND event_type = 'appropriateness_flag'
                """,
                (tenant_id,),
            )
            count = cur.fetchone()[0]
        assert count == 0, f"Expected 0 appropriateness_flag events, found {count}"
